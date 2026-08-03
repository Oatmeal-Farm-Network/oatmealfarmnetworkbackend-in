from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
from typing import Optional

router = APIRouter(prefix="/api/field-health", tags=["field_health"])


def _safe(db, sql, params):
    try:
        return db.execute(text(sql), params).fetchall()
    except Exception:
        return []


def _safe_scalar(db, sql, params, default=None):
    try:
        return db.execute(text(sql), params).scalar() or default
    except Exception:
        return default


@router.get("/fields-overview")
def fields_overview(business_id: int, db: Session = Depends(get_db)):
    """Per-field health summary cards — aggregates across all modules."""
    # Collect distinct fields referenced in any module
    field_map = {}
    for tbl, id_col, name_col in [
        ("SprayApplication",  "FieldID", "FieldName"),
        ("ScoutingRecord",    "FieldID", "FieldName"),
        ("FieldActivity",     "FieldID", "FieldName"),
        ("SoilTest",          "FieldID", "FieldName"),
        ("NutrientApplication","FieldID","FieldName"),
    ]:
        rows = _safe(db, f"SELECT DISTINCT {id_col}, {name_col} FROM {tbl} "
                        f"WHERE BusinessID = :bid AND {id_col} IS NOT NULL", {"bid": business_id})
        for r in rows:
            fid = r[0]
            if fid and fid not in field_map:
                field_map[fid] = r[1] or f"Field {fid}"

    # Also pull from IrrigationZone
    rows = _safe(db, "SELECT DISTINCT FieldID, ZoneName FROM IrrigationZone "
                     "WHERE BusinessID = :bid AND FieldID IS NOT NULL", {"bid": business_id})
    for r in rows:
        if r[0] and r[0] not in field_map:
            field_map[r[0]] = r[1] or f"Field {r[0]}"

    result = []
    for fid, fname in field_map.items():
        bid = business_id

        # Latest scouting severity
        scout = _safe(db, """
            SELECT TOP 1 MaxSeverity, ScoutingDate FROM ScoutingRecord
            WHERE BusinessID = :bid AND FieldID = :fid
            ORDER BY ScoutingDate DESC
        """, {"bid": bid, "fid": fid})
        scout = scout[0] if scout else None

        # Latest soil test rating
        soil = _safe(db, """
            SELECT TOP 1 TestDate, OverallRating FROM SoilTest
            WHERE BusinessID = :bid AND FieldID = :fid
            ORDER BY TestDate DESC
        """, {"bid": bid, "fid": fid})
        soil = soil[0] if soil else None

        # PHI-active spray applications (harvest withheld)
        phi_count = _safe_scalar(db, """
            SELECT COUNT(*) FROM SprayApplication
            WHERE BusinessID = :bid AND FieldID = :fid
              AND PHI_Days IS NOT NULL
              AND DATEADD(day, PHI_Days, ApplicationDate) > CAST(GETDATE() AS DATE)
        """, {"bid": bid, "fid": fid}, 0)

        # Last field activity
        act = _safe(db, """
            SELECT TOP 1 ActivityDate, ActivityType FROM FieldActivity
            WHERE BusinessID = :bid AND FieldID = :fid
            ORDER BY ActivityDate DESC
        """, {"bid": bid, "fid": fid})
        act = act[0] if act else None

        # Last irrigation
        irr = _safe(db, """
            SELECT TOP 1 ie.EventDate, ie.AmountMm
            FROM IrrigationEvent ie
            JOIN IrrigationZone iz ON iz.ZoneID = ie.ZoneID
            WHERE iz.BusinessID = :bid AND iz.FieldID = :fid
            ORDER BY ie.EventDate DESC
        """, {"bid": bid, "fid": fid})
        irr = irr[0] if irr else None

        # Active scouting alerts
        alert_count = _safe_scalar(db, """
            SELECT COUNT(*) FROM ScoutingAlert
            WHERE BusinessID = :bid AND FieldID = :fid AND IsAcknowledged = 0
        """, {"bid": bid, "fid": fid}, 0)

        result.append({
            "field_id": fid,
            "field_name": fname,
            "scouting_severity": scout[0] if scout else None,
            "scouting_date": str(scout[1]) if scout else None,
            "soil_rating": soil[1] if soil else None,
            "soil_test_date": str(soil[0]) if soil else None,
            "phi_active_count": phi_count,
            "last_activity_date": str(act[0]) if act else None,
            "last_activity_type": act[1] if act else None,
            "last_irrigation_date": str(irr[0]) if irr else None,
            "last_irrigation_mm": float(irr[1]) if irr else None,
            "active_alert_count": alert_count,
        })

    result.sort(key=lambda x: x["field_name"] or "")
    return result


@router.get("/timeline")
def field_timeline(
    business_id: int,
    field_id: Optional[int] = None,
    days: int = Query(90, ge=7, le=365),
    db: Session = Depends(get_db),
):
    """Unified event timeline across all modules, optionally filtered to one field."""
    bid = business_id
    fid_filter = "AND FieldID = :fid" if field_id else ""
    fid_param = {"bid": bid, "days": days, **({"fid": field_id} if field_id else {})}

    events = []

    # Spray applications
    rows = _safe(db, f"""
        SELECT ApplicationDate as event_date, 'spray' as event_type,
               FieldName as field_name, FieldID as field_id,
               ProductName as title,
               COALESCE(CAST(ApplicationRate AS NVARCHAR),'') + ' ' + COALESCE(ApplicationUnit,'') as detail
        FROM SprayApplication
        WHERE BusinessID = :bid
          AND ApplicationDate >= DATEADD(day, -:days, CAST(GETDATE() AS DATE))
          {fid_filter}
    """, fid_param)
    for r in rows:
        events.append({"event_date": str(r[0]), "event_type": r[1], "field_name": r[2],
                        "field_id": r[3], "title": r[4], "detail": (r[5] or "").strip()})

    # Scouting records
    rows = _safe(db, f"""
        SELECT sr.ScoutingDate, 'scouting', sr.FieldName, sr.FieldID,
               'Scouting: ' + COALESCE(sr.CropName,''),
               'Max severity: ' + CAST(COALESCE(sr.MaxSeverity,0) AS NVARCHAR)
        FROM ScoutingRecord sr
        WHERE sr.BusinessID = :bid
          AND sr.ScoutingDate >= DATEADD(day, -:days, CAST(GETDATE() AS DATE))
          {fid_filter}
    """, fid_param)
    for r in rows:
        events.append({"event_date": str(r[0]), "event_type": r[1], "field_name": r[2],
                        "field_id": r[3], "title": r[4], "detail": r[5]})

    # Irrigation events
    irr_fid = "AND iz.FieldID = :fid" if field_id else ""
    rows = _safe(db, f"""
        SELECT ie.EventDate, 'irrigation', iz.ZoneName, iz.FieldID,
               'Irrigation: ' + iz.ZoneName,
               CAST(ie.AmountMm AS NVARCHAR) + ' mm'
        FROM IrrigationEvent ie
        JOIN IrrigationZone iz ON iz.ZoneID = ie.ZoneID
        WHERE iz.BusinessID = :bid
          AND ie.EventDate >= DATEADD(day, -:days, CAST(GETDATE() AS DATE))
          {irr_fid}
    """, fid_param)
    for r in rows:
        events.append({"event_date": str(r[0]), "event_type": r[1], "field_name": r[2],
                        "field_id": r[3], "title": r[4], "detail": r[5]})

    # Field activities
    rows = _safe(db, f"""
        SELECT ActivityDate, 'activity', FieldName, FieldID,
               ActivityType, COALESCE(Description,'')
        FROM FieldActivity
        WHERE BusinessID = :bid
          AND ActivityDate >= DATEADD(day, -:days, CAST(GETDATE() AS DATE))
          {fid_filter}
    """, fid_param)
    for r in rows:
        events.append({"event_date": str(r[0]), "event_type": r[1], "field_name": r[2],
                        "field_id": r[3], "title": r[4], "detail": r[5]})

    # Nutrient applications
    rows = _safe(db, f"""
        SELECT AppDate, 'nutrient', FieldName, FieldID,
               'Nutrient: ' + COALESCE(ProductName,''),
               COALESCE(ApplicationMethod,'')
        FROM NutrientApplication
        WHERE BusinessID = :bid
          AND AppDate >= DATEADD(day, -:days, CAST(GETDATE() AS DATE))
          {fid_filter}
    """, fid_param)
    for r in rows:
        events.append({"event_date": str(r[0]), "event_type": r[1], "field_name": r[2],
                        "field_id": r[3], "title": r[4], "detail": r[5]})

    events.sort(key=lambda x: x["event_date"], reverse=True)
    return events


@router.get("/summary")
def field_summary(business_id: int, field_id: int, db: Session = Depends(get_db)):
    """Detailed health panel for a single field."""
    bid = business_id
    fid = field_id

    # Recent sprays (5)
    sprays = [dict(r._mapping) for r in _safe(db, """
        SELECT TOP 5 ApplicationDate, ProductName, ApplicationRate, ApplicationUnit, PHI_Days
        FROM SprayApplication
        WHERE BusinessID = :bid AND FieldID = :fid
        ORDER BY ApplicationDate DESC
    """, {"bid": bid, "fid": fid})]

    # Latest soil test + results
    soil_rows = _safe(db, """
        SELECT TOP 1 TestID, TestDate, OverallRating, LabName FROM SoilTest
        WHERE BusinessID = :bid AND FieldID = :fid
        ORDER BY TestDate DESC
    """, {"bid": bid, "fid": fid})
    soil_test = None
    if soil_rows:
        r = soil_rows[0]
        soil_test = {"test_id": r[0], "test_date": str(r[1]), "overall_rating": r[2], "lab_name": r[3]}
        nutrient_rows = _safe(db, """
            SELECT Nutrient, Value, Unit, Rating FROM SoilTestResult WHERE TestID = :tid
        """, {"tid": r[0]})
        soil_test["results"] = [{"nutrient": nr[0], "value": nr[1], "unit": nr[2], "rating": nr[3]}
                                 for nr in nutrient_rows]

    # Active alerts
    alerts = [{"severity": r[0], "pest_name": r[1], "created_at": str(r[2])}
              for r in _safe(db, """
        SELECT TOP 5 Severity, PestName, CreatedAt FROM ScoutingAlert
        WHERE BusinessID = :bid AND FieldID = :fid AND IsAcknowledged = 0
        ORDER BY Severity DESC
    """, {"bid": bid, "fid": fid})]

    # 90-day irrigation totals
    irr_rows = _safe(db, """
        SELECT SUM(ie.AmountMm), COUNT(*)
        FROM IrrigationEvent ie
        JOIN IrrigationZone iz ON iz.ZoneID = ie.ZoneID
        WHERE iz.BusinessID = :bid AND iz.FieldID = :fid
          AND ie.EventDate >= DATEADD(day, -90, CAST(GETDATE() AS DATE))
    """, {"bid": bid, "fid": fid})
    water = {"total_mm": float(irr_rows[0][0] or 0), "events": irr_rows[0][1] or 0} if irr_rows else None

    # Nutrient N/P/K applied YTD
    nutr_rows = _safe(db, """
        SELECT SUM(NRate_kg_ha), SUM(PRate_kg_ha), SUM(KRate_kg_ha), SUM(SRate_kg_ha)
        FROM NutrientApplication
        WHERE BusinessID = :bid AND FieldID = :fid
          AND AppDate >= DATEADD(day, -365, CAST(GETDATE() AS DATE))
    """, {"bid": bid, "fid": fid})
    nutrients_ytd = None
    if nutr_rows and nutr_rows[0][0] is not None:
        r = nutr_rows[0]
        nutrients_ytd = {
            "N_kg_ha": float(r[0] or 0), "P_kg_ha": float(r[1] or 0),
            "K_kg_ha": float(r[2] or 0), "S_kg_ha": float(r[3] or 0),
        }

    return {
        "field_id": fid,
        "spray_applications": sprays,
        "soil_test": soil_test,
        "active_alerts": alerts,
        "irrigation_90d": water,
        "nutrients_ytd": nutrients_ytd,
    }
