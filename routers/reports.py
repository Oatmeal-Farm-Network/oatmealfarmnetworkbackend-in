"""
Report & Export Center — returns CSV downloads for key farm records.
No new tables needed; aggregates existing data.
"""
import csv
import io
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from dependencies import get_raw_conn, get_current_user

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _csv_response(rows: list, headers: list, filename: str) -> StreamingResponse:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    w.writerows(rows)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/spray-register")
def spray_register(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    """Chemical spray register — all applications with products in date range."""
    bid = user["BusinessID"]
    cur = db.cursor()
    f = from_date or date(date.today().year, 1, 1)
    t = to_date or date.today()
    try:
        cur.execute("""
            SELECT a.ApplicationDate, a.FieldName, a.CropName, a.GrowthStage,
                   a.AreaHa, a.CarrierVolumeL, a.OperatorName, a.WeatherConditions,
                   p.ProductName, p.ActiveIngredient, p.EpaStatus,
                   ap.RatePerHa, ap.RateUnit, ap.TotalQuantity,
                   ap.PhiDays, ap.ReiHours,
                   a.PhiClearanceDate, a.Notes
            FROM SprayApplication a
            JOIN SprayApplicationProduct ap ON ap.ApplicationID = a.ApplicationID
            JOIN ChemicalProduct p ON p.ProductID = ap.ProductID
            WHERE a.BusinessID=? AND a.ApplicationDate BETWEEN ? AND ?
            ORDER BY a.ApplicationDate DESC, a.FieldName, p.ProductName
        """, [bid, str(f), str(t)])
        rows = cur.fetchall()
    except Exception:
        rows = []
    headers = [
        "Date", "Field", "Crop", "Growth Stage", "Area (ha)", "Carrier (L)",
        "Operator", "Weather", "Product", "Active Ingredient", "EPA Status",
        "Rate/ha", "Rate Unit", "Total Qty", "PHI (days)", "REI (hours)",
        "PHI Clearance Date", "Notes",
    ]
    return _csv_response([list(r) for r in rows], headers,
                         f"spray_register_{f}_{t}.csv")


@router.get("/soil-tests")
def soil_tests_export(
    field_id: Optional[str] = None,
    from_date: Optional[date] = None,
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    bid = user["BusinessID"]
    cur = db.cursor()
    params = [bid]
    extra = ""
    if field_id:
        extra += " AND t.FieldID=?"; params.append(field_id)
    if from_date:
        extra += " AND t.SampleDate>=?"; params.append(str(from_date))
    try:
        cur.execute(f"""
            SELECT t.SampleDate, t.FieldName, t.CropName, t.LabName, t.LabReference,
                   t.SampleType, t.DepthCmTop, t.DepthCmBottom,
                   r.Nutrient, r.Value, r.Unit, r.Rating,
                   r.Recommendation, r.AmendmentProductSuggested,
                   r.AmendmentRatePerHa, r.AmendmentRateUnit
            FROM SoilTest t
            JOIN SoilTestResult r ON r.TestID=t.TestID
            WHERE t.BusinessID=? {extra}
            ORDER BY t.SampleDate DESC, t.FieldName, r.Nutrient
        """, params)
        rows = cur.fetchall()
    except Exception:
        rows = []
    headers = [
        "Sample Date", "Field", "Crop", "Lab", "Lab Ref", "Sample Type",
        "Depth Top (cm)", "Depth Bottom (cm)", "Nutrient", "Value", "Unit",
        "Rating", "Recommendation", "Amendment Product", "Amendment Rate/ha", "Rate Unit",
    ]
    return _csv_response([list(r) for r in rows], headers,
                         f"soil_tests_{date.today()}.csv")


@router.get("/cash-flow")
def cash_flow_export(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    bid = user["BusinessID"]
    cur = db.cursor()
    f = from_date or date(date.today().year, 1, 1)
    t = to_date or date.today()
    try:
        cur.execute("""
            SELECT EntryDate, Category, Description, Amount, EntryType, CreatedAt
            FROM CashFlowEntry WHERE BusinessID=? AND EntryDate BETWEEN ? AND ?
            ORDER BY EntryDate DESC
        """, [bid, str(f), str(t)])
        rows = cur.fetchall()
    except Exception:
        rows = []
    headers = ["Date", "Category", "Description", "Amount", "Type", "Created At"]
    return _csv_response([list(r) for r in rows], headers,
                         f"cash_flow_{f}_{t}.csv")


@router.get("/equipment-service")
def equipment_service_export(
    equipment_id: Optional[int] = None,
    from_date: Optional[date] = None,
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    bid = user["BusinessID"]
    cur = db.cursor()
    params = [bid]
    extra = ""
    if equipment_id:
        extra += " AND s.EquipmentID=?"; params.append(equipment_id)
    if from_date:
        extra += " AND s.ServiceDate>=?"; params.append(str(from_date))
    try:
        cur.execute(f"""
            SELECT e.EquipmentName, e.Make, e.Model,
                   s.ServiceDate, s.ServiceType, s.HoursAtService, s.KmAtService,
                   s.Description, s.PartsUsed, s.PartsCost, s.LabourHours,
                   s.LabourCost, s.TotalCost, s.PerformedBy,
                   s.NextServiceHours, s.NextServiceDate, s.Notes
            FROM EquipmentServiceRecord s
            JOIN OwnedEquipment e ON e.EquipmentID=s.EquipmentID
            WHERE s.BusinessID=? {extra}
            ORDER BY s.ServiceDate DESC, e.EquipmentName
        """, params)
        rows = cur.fetchall()
    except Exception:
        rows = []
    headers = [
        "Equipment", "Make", "Model", "Service Date", "Service Type",
        "Hours", "Km", "Description", "Parts Used", "Parts Cost ($)",
        "Labour Hours", "Labour Cost ($)", "Total Cost ($)", "Performed By",
        "Next Service Hours", "Next Service Date", "Notes",
    ]
    return _csv_response([list(r) for r in rows], headers,
                         f"equipment_service_{date.today()}.csv")


@router.get("/yield-variance")
def yield_variance_export(
    season: Optional[str] = None,
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    bid = user["BusinessID"]
    cur = db.cursor()
    yr = season or str(datetime.utcnow().year)
    try:
        cur.execute("""
            SELECT Season, FieldName, CropName, VarietyName, AreaHa,
                   BudgetedYieldTonnesHa, ActualYieldTonnes, ActualYieldTonnesHa,
                   CASE WHEN BudgetedYieldTonnesHa>0 AND ActualYieldTonnesHa IS NOT NULL
                        THEN ROUND((ActualYieldTonnesHa-BudgetedYieldTonnesHa)/BudgetedYieldTonnesHa*100,1)
                        ELSE NULL END AS VariancePct,
                   Grade1Pct, Grade2Pct, RejectPct,
                   PricePerTonne, GrossRevenue, TotalVariableCost, GrossMarginPerHa,
                   HarvestStartDate, HarvestEndDate, QualityNotes
            FROM YieldRecord WHERE BusinessID=? AND Season=?
            ORDER BY FieldName, CropName
        """, [bid, yr])
        rows = cur.fetchall()
    except Exception:
        rows = []
    headers = [
        "Season", "Field", "Crop", "Variety", "Area (ha)",
        "Budget t/ha", "Actual Tonnes", "Actual t/ha", "Variance %",
        "Grade 1 %", "Grade 2 %", "Reject %",
        "Price/t ($)", "Gross Revenue ($)", "Variable Cost ($)", "GM/ha ($)",
        "Harvest Start", "Harvest End", "Quality Notes",
    ]
    return _csv_response([list(r) for r in rows], headers,
                         f"yield_variance_{yr}.csv")


@router.get("/field-activity")
def field_activity_export(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    field_id: Optional[str] = None,
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    bid = user["BusinessID"]
    cur = db.cursor()
    f = from_date or date(date.today().year, 1, 1)
    t = to_date or date.today()
    params = [bid, str(f), str(t)]
    extra = ""
    if field_id:
        extra = " AND FieldID=?"; params.append(field_id)
    try:
        cur.execute(f"""
            SELECT ActivityDate, ActivityType, FieldName, CropName, Description,
                   OperatorName, EquipmentUsed, AreaHa, UnitsApplied, UnitType,
                   RatePerHa, ProductName, CostTotal, WeatherConditions,
                   StartTime, EndTime, DurationHours, Notes
            FROM FieldActivity
            WHERE BusinessID=? AND ActivityDate BETWEEN ? AND ? {extra}
            ORDER BY ActivityDate DESC
        """, params)
        rows = cur.fetchall()
    except Exception:
        rows = []
    headers = [
        "Date", "Type", "Field", "Crop", "Description", "Operator",
        "Equipment", "Area (ha)", "Units Applied", "Unit", "Rate/ha",
        "Product", "Cost ($)", "Weather", "Start", "End", "Duration (h)", "Notes",
    ]
    return _csv_response([list(r) for r in rows], headers,
                         f"field_activity_{f}_{t}.csv")


@router.get("/scouting")
def scouting_export(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    db=Depends(get_raw_conn),
    user=Depends(get_current_user),
):
    bid = user["BusinessID"]
    cur = db.cursor()
    f = from_date or date(date.today().year, 1, 1)
    t = to_date or date.today()
    try:
        cur.execute("""
            SELECT r.ScoutingDate, r.FieldName, r.CropName, r.GrowthStage,
                   r.ScoutName, r.AreaScouted, r.WeatherConditions,
                   o.Category, o.PestOrDisease, o.Severity,
                   o.PercentAffected, o.CountPerUnit, o.CountUnit,
                   o.ActionThreshold, o.ActionRecommended, o.RequiresSpray
            FROM ScoutingRecord r
            JOIN ScoutingObservation o ON o.RecordID=r.RecordID
            WHERE r.BusinessID=? AND r.ScoutingDate BETWEEN ? AND ?
            ORDER BY r.ScoutingDate DESC, r.FieldName
        """, [bid, str(f), str(t)])
        rows = cur.fetchall()
    except Exception:
        rows = []
    headers = [
        "Date", "Field", "Crop", "Growth Stage", "Scout", "Area Scouted", "Weather",
        "Category", "Pest/Disease", "Severity", "% Affected", "Count/Unit",
        "Count Unit", "Action Threshold", "Action Recommended", "Spray Required",
    ]
    return _csv_response([list(r) for r in rows], headers,
                         f"scouting_{f}_{t}.csv")
