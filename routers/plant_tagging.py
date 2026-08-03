"""
routers/plant_tagging.py
Individual plant/tree tagging, geo-tagging, packhouse/greenhouse/storage infrastructure mapping,
asset geo-tagging.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from database import blank_to_none
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
from typing import Optional

router = APIRouter(prefix="/api/plant-tags", tags=["plant_tagging"])
_ready = False


def _ensure(db: Session):
    global _ready
    if _ready:
        return
    stmts = [
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='PlantTag')
        CREATE TABLE PlantTag (
            TagID            INT IDENTITY PRIMARY KEY,
            BusinessID       INT NOT NULL,
            FieldID          INT NULL,
            TagCode          NVARCHAR(100) NOT NULL,
            Species          NVARCHAR(300) NULL,
            Variety          NVARCHAR(300) NULL,
            PlantedDate      DATE NULL,
            AgeYears         DECIMAL(6,2) NULL,
            LocationLat      DECIMAL(11,8) NULL,
            LocationLng      DECIMAL(11,8) NULL,
            RowNum           INT NULL,
            PositionInRow    INT NULL,
            PlotCode         NVARCHAR(100) NULL,
            Status           NVARCHAR(50) NOT NULL DEFAULT 'active',
            RootStock        NVARCHAR(200) NULL,
            GraftedDate      DATE NULL,
            Notes            NVARCHAR(MAX) NULL,
            CreatedAt        DATETIME2 DEFAULT GETDATE(),
            UpdatedAt        DATETIME2 DEFAULT GETDATE()
        )""",
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='PlantTagEvent')
        CREATE TABLE PlantTagEvent (
            EventID      INT IDENTITY PRIMARY KEY,
            TagID        INT NOT NULL,
            EventType    NVARCHAR(100) NOT NULL,
            EventDate    DATE NOT NULL,
            Value        NVARCHAR(300) NULL,
            Unit         NVARCHAR(50)  NULL,
            Notes        NVARCHAR(MAX) NULL,
            LoggedBy     NVARCHAR(200) NULL,
            CreatedAt    DATETIME2 DEFAULT GETDATE()
        )""",
        """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='FarmAsset')
        CREATE TABLE FarmAsset (
            AssetID        INT IDENTITY PRIMARY KEY,
            BusinessID     INT NOT NULL,
            AssetType      NVARCHAR(100) NOT NULL,
            AssetName      NVARCHAR(300) NOT NULL,
            AssetCode      NVARCHAR(100) NULL,
            Description    NVARCHAR(MAX) NULL,
            LocationLat    DECIMAL(11,8) NULL,
            LocationLng    DECIMAL(11,8) NULL,
            LocationLabel  NVARCHAR(300) NULL,
            Status         NVARCHAR(50) NOT NULL DEFAULT 'operational',
            Capacity       NVARCHAR(200) NULL,
            CapacityUnit   NVARCHAR(50)  NULL,
            InstallDate    DATE NULL,
            LastInspection DATE NULL,
            NextInspection DATE NULL,
            Notes          NVARCHAR(MAX) NULL,
            CreatedAt      DATETIME2 DEFAULT GETDATE(),
            UpdatedAt      DATETIME2 DEFAULT GETDATE()
        )""",
    ]
    for s in stmts:
        db.execute(text(s))
    db.commit()
    _ready = True


# ─── Plant Tags ───────────────────────────────────────────────────────────────

@router.get("")
def list_tags(business_id: int = Query(...), field_id: Optional[int] = None,
              species: Optional[str] = None, status: Optional[str] = None,
              db: Session = Depends(get_db)):
    _ensure(db)
    q = "SELECT * FROM PlantTag WHERE BusinessID=:bid"
    params = {"bid": business_id}
    if field_id:
        q += " AND FieldID=:fid"; params["fid"] = field_id
    if species:
        q += " AND Species LIKE :sp"; params["sp"] = f"%{species}%"
    if status:
        q += " AND Status=:st"; params["st"] = status
    q += " ORDER BY RowNum ASC, PositionInRow ASC, TagCode ASC"
    rows = db.execute(text(q), params).fetchall()
    return [dict(r._mapping) for r in rows]


@router.get("/{tag_id}")
def get_tag(tag_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure(db)
    tag = db.execute(text("SELECT * FROM PlantTag WHERE TagID=:tid AND BusinessID=:bid"),
                     {"tid": tag_id, "bid": business_id}).fetchone()
    if not tag:
        raise HTTPException(404, "Tag not found")
    events = db.execute(text("SELECT * FROM PlantTagEvent WHERE TagID=:tid ORDER BY EventDate DESC"),
                        {"tid": tag_id}).fetchall()
    return {"tag": dict(tag._mapping), "events": [dict(r._mapping) for r in events]}


@router.post("")
def create_tag(body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure(db)
    r = db.execute(text("""
        INSERT INTO PlantTag (BusinessID,FieldID,TagCode,Species,Variety,PlantedDate,AgeYears,
            LocationLat,LocationLng,RowNum,PositionInRow,PlotCode,Status,RootStock,GraftedDate,Notes)
        OUTPUT INSERTED.TagID
        VALUES (:bid,:fid,:code,:sp,:var,:pd,:age,:lat,:lng,:row,:pos,:plot,:st,:rs,:gd,:notes)
    """), {
        "bid": body["BusinessID"], "fid": body.get("FieldID"), "code": body["TagCode"],
        "sp": body.get("Species"), "var": body.get("Variety"),
        "pd": body.get("PlantedDate"), "age": body.get("AgeYears"),
        "lat": body.get("LocationLat"), "lng": body.get("LocationLng"),
        "row": body.get("RowNum"), "pos": body.get("PositionInRow"),
        "plot": body.get("PlotCode"), "st": body.get("Status", "active"),
        "rs": body.get("RootStock"), "gd": body.get("GraftedDate"),
        "notes": body.get("Notes"),
    }).fetchone()
    db.commit()
    return {"TagID": r[0]}


@router.put("/{tag_id}")
def update_tag(tag_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    db.execute(text("""
        UPDATE PlantTag SET Species=:sp, Variety=:var, PlantedDate=:pd, AgeYears=:age,
            LocationLat=:lat, LocationLng=:lng, RowNum=:row, PositionInRow=:pos,
            PlotCode=:plot, Status=:st, RootStock=:rs, GraftedDate=:gd,
            Notes=:notes, UpdatedAt=GETDATE()
        WHERE TagID=:tid AND BusinessID=:bid
    """), {
        "sp": body.get("Species"), "var": body.get("Variety"),
        "pd": body.get("PlantedDate"), "age": body.get("AgeYears"),
        "lat": body.get("LocationLat"), "lng": body.get("LocationLng"),
        "row": body.get("RowNum"), "pos": body.get("PositionInRow"),
        "plot": body.get("PlotCode"), "st": body.get("Status"),
        "rs": body.get("RootStock"), "gd": body.get("GraftedDate"),
        "notes": body.get("Notes"), "tid": tag_id, "bid": body["BusinessID"],
    })
    db.commit()
    return {"ok": True}


@router.delete("/{tag_id}")
def delete_tag(tag_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM PlantTag WHERE TagID=:tid AND BusinessID=:bid"),
               {"tid": tag_id, "bid": business_id})
    db.commit()
    return {"ok": True}


# ─── Tag Events ───────────────────────────────────────────────────────────────

@router.post("/{tag_id}/events")
def add_event(tag_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure(db)
    r = db.execute(text("""
        INSERT INTO PlantTagEvent (TagID,EventType,EventDate,Value,Unit,Notes,LoggedBy)
        OUTPUT INSERTED.EventID
        VALUES (:tid,:et,:dt,:val,:unit,:notes,:by)
    """), {
        "tid": tag_id, "et": body["EventType"], "dt": body["EventDate"],
        "val": body.get("Value"), "unit": body.get("Unit"),
        "notes": body.get("Notes"), "by": body.get("LoggedBy"),
    }).fetchone()
    db.commit()
    return {"EventID": r[0]}


# ─── Farm Assets (geo-tagged infrastructure) ──────────────────────────────────

@router.get("/assets/list")
def list_assets(business_id: int = Query(...), asset_type: Optional[str] = None,
                db: Session = Depends(get_db)):
    _ensure(db)
    q = "SELECT * FROM FarmAsset WHERE BusinessID=:bid"
    params = {"bid": business_id}
    if asset_type:
        q += " AND AssetType=:at"; params["at"] = asset_type
    q += " ORDER BY AssetType, AssetName"
    rows = db.execute(text(q), params).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/assets")
def create_asset(body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure(db)
    r = db.execute(text("""
        INSERT INTO FarmAsset (BusinessID,AssetType,AssetName,AssetCode,Description,
            LocationLat,LocationLng,LocationLabel,Status,Capacity,CapacityUnit,
            InstallDate,LastInspection,NextInspection,Notes)
        OUTPUT INSERTED.AssetID
        VALUES (:bid,:at,:name,:code,:desc,:lat,:lng,:loc,:st,:cap,:cpu,:inst,:li,:ni,:notes)
    """), {
        "bid": body["BusinessID"], "at": body["AssetType"], "name": body["AssetName"],
        "code": body.get("AssetCode"), "desc": body.get("Description"),
        "lat": body.get("LocationLat"), "lng": body.get("LocationLng"),
        "loc": body.get("LocationLabel"), "st": body.get("Status", "operational"),
        "cap": body.get("Capacity"), "cpu": body.get("CapacityUnit"),
        "inst": body.get("InstallDate"), "li": body.get("LastInspection"),
        "ni": body.get("NextInspection"), "notes": body.get("Notes"),
    }).fetchone()
    db.commit()
    return {"AssetID": r[0]}


@router.put("/assets/{asset_id}")
def update_asset(asset_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    db.execute(text("""
        UPDATE FarmAsset SET AssetType=:at, AssetName=:name, AssetCode=:code, Description=:desc,
            LocationLat=:lat, LocationLng=:lng, LocationLabel=:loc, Status=:st,
            Capacity=:cap, CapacityUnit=:cpu, InstallDate=:inst,
            LastInspection=:li, NextInspection=:ni, Notes=:notes, UpdatedAt=GETDATE()
        WHERE AssetID=:aid AND BusinessID=:bid
    """), {
        "at": body.get("AssetType"), "name": body.get("AssetName"), "code": body.get("AssetCode"),
        "desc": body.get("Description"), "lat": body.get("LocationLat"), "lng": body.get("LocationLng"),
        "loc": body.get("LocationLabel"), "st": body.get("Status"),
        "cap": body.get("Capacity"), "cpu": body.get("CapacityUnit"),
        "inst": body.get("InstallDate"), "li": body.get("LastInspection"),
        "ni": body.get("NextInspection"), "notes": body.get("Notes"),
        "aid": asset_id, "bid": body["BusinessID"],
    })
    db.commit()
    return {"ok": True}


@router.delete("/assets/{asset_id}")
def delete_asset(asset_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM FarmAsset WHERE AssetID=:aid AND BusinessID=:bid"),
               {"aid": asset_id, "bid": business_id})
    db.commit()
    return {"ok": True}


# ─── Summary ─────────────────────────────────────────────────────────────────

@router.get("/summary/dashboard")
def tagging_summary(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure(db)
    tags = db.execute(text("""
        SELECT COUNT(*) AS Total,
            SUM(CASE WHEN Status='active' THEN 1 ELSE 0 END) AS Active,
            COUNT(DISTINCT Species) AS UniqueSpecies,
            SUM(CASE WHEN LocationLat IS NOT NULL THEN 1 ELSE 0 END) AS GeoTagged
        FROM PlantTag WHERE BusinessID=:bid
    """), {"bid": business_id}).fetchone()
    assets = db.execute(text("""
        SELECT COUNT(*) AS TotalAssets, COUNT(DISTINCT AssetType) AS AssetTypes
        FROM FarmAsset WHERE BusinessID=:bid
    """), {"bid": business_id}).fetchone()
    return {**dict(tags._mapping), **dict(assets._mapping)} if tags and assets else {}
