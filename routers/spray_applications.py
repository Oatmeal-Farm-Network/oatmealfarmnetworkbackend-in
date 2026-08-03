from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime
from dependencies import get_raw_conn, get_current_user

router = APIRouter(prefix="/api/spray", tags=["spray_applications"])
_ddl_done = False

EPA_STATUSES = ["registered", "restricted_use", "organic_approved", "discontinued"]
APPLICATION_METHODS = ["ground_boom", "air_blast", "aerial", "banded", "hand_spray", "drip_injection", "fertigation"]
ENTRY_RESTRICTION = [0, 4, 12, 24, 48, 72, 168]  # REI hours


def _ensure_tables(db):
    global _ddl_done
    if _ddl_done:
        return
    cur = db.cursor()
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='ChemicalProduct')
    CREATE TABLE ChemicalProduct (
        ProductID INT IDENTITY PRIMARY KEY,
        BusinessID INT NOT NULL,
        ProductName NVARCHAR(150) NOT NULL,
        ActiveIngredient NVARCHAR(300),
        RegistrationNumber NVARCHAR(80),
        EpaStatus NVARCHAR(30),
        ProductType NVARCHAR(60),
        ManufacturerName NVARCHAR(150),
        PHIDays INT,
        REIHours INT,
        DefaultRatePerHa DECIMAL(10,4),
        DefaultRateUnit NVARCHAR(20),
        Notes NVARCHAR(500),
        IsActive BIT NOT NULL DEFAULT 1,
        CreatedAt DATETIME NOT NULL DEFAULT GETDATE()
    )""")
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='SprayApplication')
    CREATE TABLE SprayApplication (
        ApplicationID INT IDENTITY PRIMARY KEY,
        BusinessID INT NOT NULL,
        ApplicationDate DATE NOT NULL,
        FieldID NVARCHAR(80),
        FieldName NVARCHAR(120),
        AreaTreatedHa DECIMAL(10,4),
        CropName NVARCHAR(100),
        GrowthStage NVARCHAR(80),
        ApplicationMethod NVARCHAR(60),
        EquipmentUsed NVARCHAR(200),
        OperatorName NVARCHAR(150),
        WeatherTempC DECIMAL(5,1),
        WeatherWindKph DECIMAL(5,1),
        WeatherHumidityPct DECIMAL(5,1),
        WeatherConditions NVARCHAR(100),
        TotalWaterUsedL DECIMAL(10,2),
        WaterVolumePerHaL DECIMAL(8,2),
        PestTargeted NVARCHAR(200),
        CropObservations NVARCHAR(500),
        PHIDate DATE,
        REIExpiry DATETIME,
        IsComplete BIT NOT NULL DEFAULT 0,
        Notes NVARCHAR(1000),
        CreatedAt DATETIME NOT NULL DEFAULT GETDATE()
    )""")
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='SprayApplicationProduct')
    CREATE TABLE SprayApplicationProduct (
        LineID INT IDENTITY PRIMARY KEY,
        ApplicationID INT NOT NULL,
        BusinessID INT NOT NULL,
        ProductID INT,
        ProductNameOverride NVARCHAR(150),
        RatePerHa DECIMAL(10,4),
        RateUnit NVARCHAR(20),
        TotalAmountUsed DECIMAL(10,4),
        TotalAmountUnit NVARCHAR(20),
        BatchLotNumber NVARCHAR(80),
        CostPerUnit DECIMAL(10,4),
        TotalCost DECIMAL(12,2)
    )""")
    db.commit()
    _ddl_done = True


class ProductIn(BaseModel):
    product_name: str
    active_ingredient: Optional[str] = None
    registration_number: Optional[str] = None
    epa_status: Optional[str] = None
    product_type: Optional[str] = None
    manufacturer_name: Optional[str] = None
    phi_days: Optional[int] = None
    rei_hours: Optional[int] = None
    default_rate_per_ha: Optional[float] = None
    default_rate_unit: Optional[str] = None
    notes: Optional[str] = None


class ApplicationProductLine(BaseModel):
    product_id: Optional[int] = None
    product_name_override: Optional[str] = None
    rate_per_ha: Optional[float] = None
    rate_unit: Optional[str] = "L/ha"
    total_amount_used: Optional[float] = None
    total_amount_unit: Optional[str] = None
    batch_lot_number: Optional[str] = None
    cost_per_unit: Optional[float] = None
    total_cost: Optional[float] = None


class ApplicationIn(BaseModel):
    application_date: date
    field_id: Optional[str] = None
    field_name: Optional[str] = None
    area_treated_ha: Optional[float] = None
    crop_name: Optional[str] = None
    growth_stage: Optional[str] = None
    application_method: Optional[str] = None
    equipment_used: Optional[str] = None
    operator_name: Optional[str] = None
    weather_temp_c: Optional[float] = None
    weather_wind_kph: Optional[float] = None
    weather_humidity_pct: Optional[float] = None
    weather_conditions: Optional[str] = None
    total_water_used_l: Optional[float] = None
    water_volume_per_ha_l: Optional[float] = None
    pest_targeted: Optional[str] = None
    crop_observations: Optional[str] = None
    notes: Optional[str] = None
    products: List[ApplicationProductLine] = []


# ── Chemical product library ──────────────────────────────────────────────────

@router.get("/products")
def list_products(db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("SELECT * FROM ChemicalProduct WHERE BusinessID=? AND IsActive=1 ORDER BY ProductName", [bid])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.post("/products", status_code=201)
def create_product(body: ProductIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("""
        INSERT INTO ChemicalProduct
            (BusinessID,ProductName,ActiveIngredient,RegistrationNumber,EpaStatus,ProductType,
             ManufacturerName,PHIDays,REIHours,DefaultRatePerHa,DefaultRateUnit,Notes)
        OUTPUT INSERTED.ProductID VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, [bid, body.product_name, body.active_ingredient, body.registration_number,
          body.epa_status, body.product_type, body.manufacturer_name,
          body.phi_days, body.rei_hours, body.default_rate_per_ha,
          body.default_rate_unit, body.notes])
    pid = cur.fetchone()[0]
    db.commit()
    return {"product_id": pid}


@router.patch("/products/{product_id}")
def update_product(product_id: int, body: ProductIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("SELECT ProductID FROM ChemicalProduct WHERE ProductID=? AND BusinessID=?", [product_id, bid])
    if not cur.fetchone():
        raise HTTPException(404, "Product not found")
    cur.execute("""
        UPDATE ChemicalProduct SET
            ProductName=?, ActiveIngredient=?, RegistrationNumber=?, EpaStatus=?,
            ProductType=?, ManufacturerName=?, PHIDays=?, REIHours=?,
            DefaultRatePerHa=?, DefaultRateUnit=?, Notes=?
        WHERE ProductID=? AND BusinessID=?
    """, [body.product_name, body.active_ingredient, body.registration_number, body.epa_status,
          body.product_type, body.manufacturer_name, body.phi_days, body.rei_hours,
          body.default_rate_per_ha, body.default_rate_unit, body.notes, product_id, bid])
    db.commit()
    return {"ok": True}


# ── Spray applications ────────────────────────────────────────────────────────

@router.post("/applications", status_code=201)
def create_application(body: ApplicationIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()

    # Derive PHI date and REI expiry from worst-case product line
    phi_date = None
    rei_expiry = None
    for p in body.products:
        if p.product_id:
            cur.execute("SELECT PHIDays, REIHours FROM ChemicalProduct WHERE ProductID=? AND BusinessID=?", [p.product_id, bid])
            row = cur.fetchone()
            if row:
                from datetime import timedelta as _td
                if row[0]:
                    candidate = body.application_date + _td(days=int(row[0]))
                    phi_date = max(phi_date, candidate) if phi_date else candidate
                if row[1]:
                    candidate = datetime.combine(body.application_date, datetime.min.time()) + _td(hours=int(row[1]))
                    rei_expiry = max(rei_expiry, candidate) if rei_expiry else candidate

    cur.execute("""
        INSERT INTO SprayApplication
            (BusinessID,ApplicationDate,FieldID,FieldName,AreaTreatedHa,CropName,GrowthStage,
             ApplicationMethod,EquipmentUsed,OperatorName,WeatherTempC,WeatherWindKph,
             WeatherHumidityPct,WeatherConditions,TotalWaterUsedL,WaterVolumePerHaL,
             PestTargeted,CropObservations,PHIDate,REIExpiry,Notes)
        OUTPUT INSERTED.ApplicationID VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, [bid, str(body.application_date), body.field_id, body.field_name, body.area_treated_ha,
          body.crop_name, body.growth_stage, body.application_method, body.equipment_used,
          body.operator_name, body.weather_temp_c, body.weather_wind_kph, body.weather_humidity_pct,
          body.weather_conditions, body.total_water_used_l, body.water_volume_per_ha_l,
          body.pest_targeted, body.crop_observations,
          str(phi_date) if phi_date else None,
          rei_expiry.isoformat() if rei_expiry else None, body.notes])
    app_id = cur.fetchone()[0]

    for p in body.products:
        cur.execute("""
            INSERT INTO SprayApplicationProduct
                (ApplicationID,BusinessID,ProductID,ProductNameOverride,RatePerHa,RateUnit,
                 TotalAmountUsed,TotalAmountUnit,BatchLotNumber,CostPerUnit,TotalCost)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, [app_id, bid, p.product_id, p.product_name_override, p.rate_per_ha, p.rate_unit,
              p.total_amount_used, p.total_amount_unit, p.batch_lot_number, p.cost_per_unit, p.total_cost])

    db.commit()
    return {"application_id": app_id}


@router.get("/applications")
def list_applications(
    field_id: Optional[str] = None,
    crop_name: Optional[str] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    limit: int = 100,
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    filters = ["a.BusinessID=?"]
    params: list = [bid]
    if field_id:
        filters.append("a.FieldID=?"); params.append(field_id)
    if crop_name:
        filters.append("a.CropName=?"); params.append(crop_name)
    if from_date:
        filters.append("a.ApplicationDate>=?"); params.append(str(from_date))
    if to_date:
        filters.append("a.ApplicationDate<=?"); params.append(str(to_date))
    cur.execute(f"""
        SELECT a.*,
            (SELECT COUNT(*) FROM SprayApplicationProduct WHERE ApplicationID=a.ApplicationID) AS ProductCount
        FROM SprayApplication a
        WHERE {' AND '.join(filters)}
        ORDER BY a.ApplicationDate DESC
        OFFSET 0 ROWS FETCH NEXT ? ROWS ONLY
    """, params + [limit])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.get("/applications/{app_id}")
def get_application(app_id: int, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("SELECT * FROM SprayApplication WHERE ApplicationID=? AND BusinessID=?", [app_id, bid])
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Application not found")
    cols = [c[0] for c in cur.description]
    app = dict(zip(cols, row))
    cur.execute("""
        SELECT sap.*, cp.ProductName AS LibraryName, cp.ActiveIngredient, cp.PHIDays, cp.REIHours
        FROM SprayApplicationProduct sap
        LEFT JOIN ChemicalProduct cp ON cp.ProductID=sap.ProductID
        WHERE sap.ApplicationID=? AND sap.BusinessID=?
    """, [app_id, bid])
    cols2 = [c[0] for c in cur.description]
    app["products"] = [dict(zip(cols2, r)) for r in cur.fetchall()]
    return app


@router.patch("/applications/{app_id}/complete")
def mark_complete(app_id: int, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("SELECT ApplicationID FROM SprayApplication WHERE ApplicationID=? AND BusinessID=?", [app_id, bid])
    if not cur.fetchone():
        raise HTTPException(404, "Application not found")
    cur.execute("UPDATE SprayApplication SET IsComplete=1 WHERE ApplicationID=?", [app_id])
    db.commit()
    return {"ok": True}


@router.get("/phi-calendar")
def phi_calendar(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    """Return applications with upcoming PHI dates for harvest planning."""
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    f = from_date or date.today()
    t = to_date or date(f.year, 12, 31)
    cur.execute("""
        SELECT ApplicationID, ApplicationDate, FieldName, CropName, PestTargeted,
               PHIDate, REIExpiry, IsComplete
        FROM SprayApplication
        WHERE BusinessID=? AND PHIDate IS NOT NULL
          AND PHIDate BETWEEN ? AND ?
        ORDER BY PHIDate ASC
    """, [bid, str(f), str(t)])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.get("/summary")
def summary(
    field_id: Optional[str] = None,
    season: Optional[str] = None,
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    year = int(season) if season else date.today().year
    filters = ["a.BusinessID=?", "YEAR(a.ApplicationDate)=?"]
    params: list = [bid, year]
    if field_id:
        filters.append("a.FieldID=?"); params.append(field_id)
    cur.execute(f"""
        SELECT
            COUNT(DISTINCT a.ApplicationID) AS TotalApplications,
            ROUND(SUM(a.AreaTreatedHa),2) AS TotalAreaHa,
            ROUND(SUM(sap.TotalCost),2) AS TotalChemicalCost,
            COUNT(DISTINCT a.FieldID) AS FieldsSpayed,
            COUNT(DISTINCT sap.ProductID) AS UniqueProducts
        FROM SprayApplication a
        LEFT JOIN SprayApplicationProduct sap ON sap.ApplicationID=a.ApplicationID
        WHERE {' AND '.join(filters)}
    """, params)
    row = cur.fetchone()
    cols = [c[0] for c in cur.description]
    totals = dict(zip(cols, row)) if row else {}

    cur.execute(f"""
        SELECT cp.ProductName, COUNT(*) AS Uses,
               ROUND(SUM(sap.TotalAmountUsed),2) AS TotalAmount, sap.TotalAmountUnit,
               ROUND(SUM(sap.TotalCost),2) AS TotalCost
        FROM SprayApplicationProduct sap
        JOIN SprayApplication a ON a.ApplicationID=sap.ApplicationID
        LEFT JOIN ChemicalProduct cp ON cp.ProductID=sap.ProductID
        WHERE a.BusinessID=? AND YEAR(a.ApplicationDate)=?
        GROUP BY cp.ProductName, sap.TotalAmountUnit
        ORDER BY TotalCost DESC
    """, [bid, year])
    cols2 = [c[0] for c in cur.description]
    by_product = [dict(zip(cols2, r)) for r in cur.fetchall()]

    return {"year": year, "totals": totals, "by_product": by_product}
