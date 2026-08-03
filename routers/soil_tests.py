from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import date
from dependencies import get_raw_conn, get_current_user

router = APIRouter(prefix="/api/soil-tests", tags=["soil_tests"])
_ddl_done = False

NUTRIENTS = ["pH", "EC", "OC", "N_total", "P_Colwell", "P_Bray", "K", "Ca", "Mg", "Na", "S",
             "Zn", "B", "Mn", "Fe", "Cu", "Mo", "CEC", "ESP", "SAR"]
RATINGS = ["very_low", "low", "optimal", "high", "very_high"]
SAMPLE_TYPES = ["composite", "single_point", "grid", "zone_management"]

# Rough optimal ranges for common nutrients (example values — lab-specific)
OPTIMAL_RANGES = {
    "pH": (6.0, 7.2),
    "P_Colwell": (30, 80),
    "K": (120, 300),
    "Ca": (1500, 4000),
    "Mg": (120, 400),
    "Zn": (1.0, 5.0),
    "B": (0.5, 2.0),
    "S": (10, 40),
    "OC": (2.0, 6.0),
}


def _rate(nutrient: str, value: float) -> str:
    rng = OPTIMAL_RANGES.get(nutrient)
    if not rng:
        return "unknown"
    lo, hi = rng
    if value < lo * 0.6:
        return "very_low"
    if value < lo:
        return "low"
    if value <= hi:
        return "optimal"
    if value <= hi * 1.5:
        return "high"
    return "very_high"


def _ensure_tables(db):
    global _ddl_done
    if _ddl_done:
        return
    cur = db.cursor()
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='SoilTest')
    CREATE TABLE SoilTest (
        TestID INT IDENTITY PRIMARY KEY,
        BusinessID INT NOT NULL,
        FieldID NVARCHAR(80),
        FieldName NVARCHAR(120),
        SampleDate DATE NOT NULL,
        LabName NVARCHAR(150),
        LabReference NVARCHAR(80),
        SampleType NVARCHAR(40),
        DepthCmTop INT NOT NULL DEFAULT 0,
        DepthCmBottom INT NOT NULL DEFAULT 30,
        CropName NVARCHAR(100),
        TargetYield NVARCHAR(80),
        GPS_Lat DECIMAL(10,7),
        GPS_Lon DECIMAL(10,7),
        Notes NVARCHAR(1000),
        CreatedAt DATETIME NOT NULL DEFAULT GETDATE()
    )""")
    cur.execute("""
    IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='SoilTestResult')
    CREATE TABLE SoilTestResult (
        ResultID INT IDENTITY PRIMARY KEY,
        TestID INT NOT NULL,
        BusinessID INT NOT NULL,
        Nutrient NVARCHAR(40) NOT NULL,
        Value DECIMAL(12,4) NOT NULL,
        Unit NVARCHAR(20),
        Rating NVARCHAR(20),
        Recommendation NVARCHAR(500),
        AmendmentProductSuggested NVARCHAR(200),
        AmendmentRatePerHa DECIMAL(10,3),
        AmendmentRateUnit NVARCHAR(20)
    )""")
    db.commit()
    _ddl_done = True


class ResultIn(BaseModel):
    nutrient: str
    value: float
    unit: Optional[str] = None
    rating: Optional[str] = None
    recommendation: Optional[str] = None
    amendment_product_suggested: Optional[str] = None
    amendment_rate_per_ha: Optional[float] = None
    amendment_rate_unit: Optional[str] = None


class TestIn(BaseModel):
    field_id: Optional[str] = None
    field_name: Optional[str] = None
    sample_date: date
    lab_name: Optional[str] = None
    lab_reference: Optional[str] = None
    sample_type: Optional[str] = None
    depth_cm_top: int = 0
    depth_cm_bottom: int = 30
    crop_name: Optional[str] = None
    target_yield: Optional[str] = None
    gps_lat: Optional[float] = None
    gps_lon: Optional[float] = None
    notes: Optional[str] = None
    results: List[ResultIn] = []


@router.post("/tests", status_code=201)
def create_test(body: TestIn, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("""
        INSERT INTO SoilTest
            (BusinessID,FieldID,FieldName,SampleDate,LabName,LabReference,SampleType,
             DepthCmTop,DepthCmBottom,CropName,TargetYield,GPS_Lat,GPS_Lon,Notes)
        OUTPUT INSERTED.TestID VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, [bid, body.field_id, body.field_name, str(body.sample_date), body.lab_name,
          body.lab_reference, body.sample_type, body.depth_cm_top, body.depth_cm_bottom,
          body.crop_name, body.target_yield, body.gps_lat, body.gps_lon, body.notes])
    tid = cur.fetchone()[0]
    for r in body.results:
        rating = r.rating or _rate(r.nutrient, r.value)
        cur.execute("""
            INSERT INTO SoilTestResult
                (TestID,BusinessID,Nutrient,Value,Unit,Rating,Recommendation,
                 AmendmentProductSuggested,AmendmentRatePerHa,AmendmentRateUnit)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, [tid, bid, r.nutrient, r.value, r.unit, rating, r.recommendation,
              r.amendment_product_suggested, r.amendment_rate_per_ha, r.amendment_rate_unit])
    db.commit()
    return {"test_id": tid}


@router.get("/tests")
def list_tests(
    field_id: Optional[str] = None,
    from_date: Optional[date] = None,
    limit: int = 100,
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    filters = ["t.BusinessID=?"]
    params: list = [bid]
    if field_id:
        filters.append("t.FieldID=?"); params.append(field_id)
    if from_date:
        filters.append("t.SampleDate>=?"); params.append(str(from_date))
    cur.execute(f"""
        SELECT t.*,
            (SELECT COUNT(*) FROM SoilTestResult WHERE TestID=t.TestID) AS ResultCount,
            (SELECT COUNT(*) FROM SoilTestResult WHERE TestID=t.TestID AND Rating IN ('very_low','low')) AS LowCount
        FROM SoilTest t
        WHERE {' AND '.join(filters)}
        ORDER BY t.SampleDate DESC
        OFFSET 0 ROWS FETCH NEXT ? ROWS ONLY
    """, params + [limit])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.get("/tests/{test_id}")
def get_test(test_id: int, db=Depends(get_raw_conn), user=Depends(get_current_user)):
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("SELECT * FROM SoilTest WHERE TestID=? AND BusinessID=?", [test_id, bid])
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Test not found")
    cols = [c[0] for c in cur.description]
    test = dict(zip(cols, row))
    cur.execute("SELECT * FROM SoilTestResult WHERE TestID=? ORDER BY Nutrient", [test_id])
    cols2 = [c[0] for c in cur.description]
    test["results"] = [dict(zip(cols2, r)) for r in cur.fetchall()]
    test["deficiencies"] = [r for r in test["results"] if r["Rating"] in ("very_low", "low")]
    return test


@router.get("/by-field")
def by_field(db=Depends(get_raw_conn), user=Depends(get_current_user)):
    """Latest test per field with deficiency count."""
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("""
        SELECT t.FieldID, t.FieldName,
               MAX(t.SampleDate) AS LatestTestDate,
               COUNT(DISTINCT t.TestID) AS TotalTests,
               SUM(CASE WHEN r.Rating IN ('very_low','low') THEN 1 ELSE 0 END) AS DeficiencyCount
        FROM SoilTest t
        LEFT JOIN SoilTestResult r ON r.TestID=t.TestID
        WHERE t.BusinessID=?
        GROUP BY t.FieldID, t.FieldName
        ORDER BY LatestTestDate DESC
    """, [bid])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.get("/trends")
def trends(
    field_id: Optional[str] = None,
    nutrient: Optional[str] = None,
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    """Nutrient value trends over time for a field."""
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    filters = ["t.BusinessID=?"]
    params: list = [bid]
    if field_id:
        filters.append("t.FieldID=?"); params.append(field_id)
    if nutrient:
        filters.append("r.Nutrient=?"); params.append(nutrient)
    cur.execute(f"""
        SELECT t.FieldName, t.SampleDate, r.Nutrient, r.Value, r.Unit, r.Rating
        FROM SoilTest t
        JOIN SoilTestResult r ON r.TestID=t.TestID
        WHERE {' AND '.join(filters)}
        ORDER BY t.FieldID, r.Nutrient, t.SampleDate ASC
    """, params)
    cols = [c[0] for c in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    # Group by nutrient
    grouped: dict = {}
    for row in rows:
        key = row["Nutrient"]
        grouped.setdefault(key, []).append(row)
    return {"trends": grouped, "nutrients": list(grouped.keys())}


@router.get("/deficiency-report")
def deficiency_report(db=Depends(get_raw_conn), user=Depends(get_current_user)):
    """Most recent test per field — nutrients rated very_low or low."""
    _ensure_tables(db)
    bid = user["BusinessID"]
    cur = db.cursor()
    cur.execute("""
        SELECT r.Nutrient, r.Value, r.Unit, r.Rating, r.Recommendation,
               r.AmendmentProductSuggested, r.AmendmentRatePerHa, r.AmendmentRateUnit,
               t.FieldName, t.CropName, t.SampleDate
        FROM SoilTestResult r
        JOIN SoilTest t ON t.TestID=r.TestID
        WHERE t.BusinessID=? AND r.Rating IN ('very_low','low')
          AND t.TestID IN (
              SELECT TOP 1 TestID FROM SoilTest WHERE BusinessID=t.BusinessID AND FieldID=t.FieldID
              ORDER BY SampleDate DESC
          )
        ORDER BY r.Rating, r.Nutrient
    """, [bid])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]
