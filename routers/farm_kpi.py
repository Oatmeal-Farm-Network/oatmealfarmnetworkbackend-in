from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
from typing import Optional
from datetime import datetime, date
from routers.notifications import notify_business
import csv, io

router = APIRouter(prefix="/api/farm-kpi", tags=["farm_kpi"])

_tables_ready = False


def _ensure_tables(db: Session):
    global _tables_ready
    if _tables_ready:
        return

    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'FarmKPI')
        CREATE TABLE FarmKPI (
            KPIID           INT IDENTITY PRIMARY KEY,
            BusinessID      INT           NOT NULL,
            KPIName         NVARCHAR(200) NOT NULL,
            KPICategory     NVARCHAR(100) NOT NULL DEFAULT 'production',
            KPIKey          NVARCHAR(100) NOT NULL,
            Unit            NVARCHAR(50)  NULL,
            TargetValue     DECIMAL(18,4) NULL,
            WarningThreshold DECIMAL(18,4) NULL,
            CriticalThreshold DECIMAL(18,4) NULL,
            ThresholdDirection NVARCHAR(10) NOT NULL DEFAULT 'below',
            IsActive        BIT           NOT NULL DEFAULT 1,
            SortOrder       INT           NOT NULL DEFAULT 0,
            Notes           NVARCHAR(500) NULL,
            CreatedAt       DATETIME2     DEFAULT GETDATE()
        )
    """))

    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'FarmKPIReading')
        CREATE TABLE FarmKPIReading (
            ReadingID   INT IDENTITY PRIMARY KEY,
            KPIID       INT           NOT NULL,
            BusinessID  INT           NOT NULL,
            ReadingDate DATE          NOT NULL,
            Value       DECIMAL(18,4) NOT NULL,
            Notes       NVARCHAR(500) NULL,
            Source      NVARCHAR(100) NULL,
            CreatedAt   DATETIME2     DEFAULT GETDATE()
        )
    """))

    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'FarmAlert')
        CREATE TABLE FarmAlert (
            AlertID     INT IDENTITY PRIMARY KEY,
            BusinessID  INT           NOT NULL,
            AlertType   NVARCHAR(50)  NOT NULL,
            Severity    NVARCHAR(20)  NOT NULL DEFAULT 'warning',
            Title       NVARCHAR(300) NOT NULL,
            Message     NVARCHAR(1000) NOT NULL,
            Source      NVARCHAR(100) NULL,
            SourceID    INT           NULL,
            IsRead      BIT           NOT NULL DEFAULT 0,
            IsDismissed BIT           NOT NULL DEFAULT 0,
            ExpiresAt   DATETIME2     NULL,
            CreatedAt   DATETIME2     DEFAULT GETDATE()
        )
    """))

    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'FarmWeatherAlert')
        CREATE TABLE FarmWeatherAlert (
            WeatherAlertID INT IDENTITY PRIMARY KEY,
            BusinessID  INT           NOT NULL,
            AlertType   NVARCHAR(50)  NOT NULL,
            Severity    NVARCHAR(20)  NOT NULL DEFAULT 'warning',
            CropName    NVARCHAR(200) NULL,
            FieldID     INT           NULL,
            Title       NVARCHAR(300) NOT NULL,
            Message     NVARCHAR(1000) NOT NULL,
            WeatherData NVARCHAR(MAX) NULL,
            RecommendedAction NVARCHAR(500) NULL,
            IsRead      BIT           NOT NULL DEFAULT 0,
            ValidUntil  DATETIME2     NULL,
            CreatedAt   DATETIME2     DEFAULT GETDATE()
        )
    """))

    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'FarmPestObservation')
        CREATE TABLE FarmPestObservation (
            ObsID       INT IDENTITY PRIMARY KEY,
            BusinessID  INT           NOT NULL,
            FieldID     INT           NULL,
            FieldName   NVARCHAR(200) NULL,
            CropName    NVARCHAR(200) NULL,
            PestName    NVARCHAR(200) NOT NULL,
            PestType    NVARCHAR(50)  NOT NULL DEFAULT 'insect',
            SeverityLevel NVARCHAR(20) NOT NULL DEFAULT 'low',
            ObservationDate DATE      NOT NULL,
            AffectedArea DECIMAL(10,2) NULL,
            Notes       NVARCHAR(1000) NULL,
            PhotoURL    NVARCHAR(500) NULL,
            TreatmentRequired BIT    NOT NULL DEFAULT 0,
            WorkOrderID INT           NULL,
            Status      NVARCHAR(20)  NOT NULL DEFAULT 'observed',
            CreatedAt   DATETIME2     DEFAULT GETDATE()
        )
    """))

    db.commit()
    _tables_ready = True


# ── KPIs CRUD ─────────────────────────────────────────────────────────────────

@router.get("/kpis")
def list_kpis(business_id: int = Query(...), category: Optional[str] = None, db: Session = Depends(get_db)):
    _ensure_tables(db)
    q = """
        SELECT k.KPIID, k.BusinessID, k.KPIName, k.KPICategory, k.KPIKey,
               k.Unit, k.TargetValue, k.WarningThreshold, k.CriticalThreshold,
               k.ThresholdDirection, k.IsActive, k.SortOrder, k.Notes,
               (SELECT TOP 1 Value FROM FarmKPIReading
                WHERE KPIID = k.KPIID ORDER BY ReadingDate DESC) AS LatestValue,
               (SELECT TOP 1 ReadingDate FROM FarmKPIReading
                WHERE KPIID = k.KPIID ORDER BY ReadingDate DESC) AS LatestDate
        FROM FarmKPI k
        WHERE k.BusinessID = :bid AND k.IsActive = 1
    """
    params: dict = {"bid": business_id}
    if category:
        q += " AND k.KPICategory = :cat"
        params["cat"] = category
    q += " ORDER BY k.SortOrder, k.KPIName"
    rows = db.execute(text(q), params).fetchall()
    return [_kpi_row(r) for r in rows]


@router.post("/kpis")
def create_kpi(payload: dict, db: Session = Depends(get_db)):
    _ensure_tables(db)
    bid = payload.get("business_id") or payload.get("BusinessID")
    if not bid:
        raise HTTPException(400, "business_id required")
    db.execute(text("""
        INSERT INTO FarmKPI
            (BusinessID, KPIName, KPICategory, KPIKey, Unit, TargetValue,
             WarningThreshold, CriticalThreshold, ThresholdDirection, SortOrder, Notes)
        VALUES (:bid, :name, :cat, :key, :unit, :target, :warn, :crit, :dir, :sort, :notes)
    """), {
        "bid":    bid,
        "name":   payload.get("kpi_name", ""),
        "cat":    payload.get("kpi_category", "production"),
        "key":    payload.get("kpi_key", ""),
        "unit":   payload.get("unit"),
        "target": payload.get("target_value"),
        "warn":   payload.get("warning_threshold"),
        "crit":   payload.get("critical_threshold"),
        "dir":    payload.get("threshold_direction", "below"),
        "sort":   payload.get("sort_order", 0),
        "notes":  payload.get("notes"),
    })
    db.commit()
    return {"ok": True}


@router.put("/kpis/{kpi_id}")
def update_kpi(kpi_id: int, payload: dict, db: Session = Depends(get_db)):
    _ensure_tables(db)
    bid = payload.get("business_id") or payload.get("BusinessID")
    db.execute(text("""
        UPDATE FarmKPI SET
            KPIName            = :name,
            KPICategory        = :cat,
            Unit               = :unit,
            TargetValue        = :target,
            WarningThreshold   = :warn,
            CriticalThreshold  = :crit,
            ThresholdDirection = :dir,
            SortOrder          = :sort,
            Notes              = :notes
        WHERE KPIID = :id AND BusinessID = :bid
    """), {
        "id":     kpi_id,
        "bid":    bid,
        "name":   payload.get("kpi_name"),
        "cat":    payload.get("kpi_category"),
        "unit":   payload.get("unit"),
        "target": payload.get("target_value"),
        "warn":   payload.get("warning_threshold"),
        "crit":   payload.get("critical_threshold"),
        "dir":    payload.get("threshold_direction"),
        "sort":   payload.get("sort_order"),
        "notes":  payload.get("notes"),
    })
    db.commit()
    return {"ok": True}


@router.delete("/kpis/{kpi_id}")
def delete_kpi(kpi_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(text("UPDATE FarmKPI SET IsActive = 0 WHERE KPIID = :id AND BusinessID = :bid"),
               {"id": kpi_id, "bid": business_id})
    db.commit()
    return {"ok": True}


# ── KPI Readings ──────────────────────────────────────────────────────────────

@router.post("/kpis/{kpi_id}/readings")
def add_reading(kpi_id: int, payload: dict, db: Session = Depends(get_db)):
    _ensure_tables(db)
    bid = payload.get("business_id") or payload.get("BusinessID")
    db.execute(text("""
        INSERT INTO FarmKPIReading (KPIID, BusinessID, ReadingDate, Value, Notes, Source)
        VALUES (:kid, :bid, :date, :val, :notes, :src)
    """), {
        "kid":   kpi_id,
        "bid":   bid,
        "date":  payload.get("reading_date", date.today().isoformat()),
        "val":   payload.get("value", 0),
        "notes": payload.get("notes"),
        "src":   payload.get("source"),
    })
    db.commit()
    return {"ok": True}


@router.get("/kpis/{kpi_id}/readings")
def get_readings(
    kpi_id: int,
    business_id: int = Query(...),
    days: int = 90,
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    rows = db.execute(text("""
        SELECT ReadingID, KPIID, BusinessID, ReadingDate, Value, Notes, Source, CreatedAt
        FROM FarmKPIReading
        WHERE KPIID = :kid AND BusinessID = :bid
          AND ReadingDate >= DATEADD(DAY, :days, GETDATE())
        ORDER BY ReadingDate
    """), {"kid": kpi_id, "bid": business_id, "days": -days}).fetchall()
    return [{"reading_id": r.ReadingID, "reading_date": r.ReadingDate.isoformat(),
             "value": float(r.Value), "notes": r.Notes, "source": r.Source} for r in rows]


# ── Alerts ────────────────────────────────────────────────────────────────────

@router.get("/alerts")
def list_alerts(
    business_id: int = Query(...),
    unread_only: bool = False,
    severity: Optional[str] = None,
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    q = """
        SELECT AlertID, BusinessID, AlertType, Severity, Title, Message,
               Source, SourceID, IsRead, IsDismissed, ExpiresAt, CreatedAt
        FROM FarmAlert
        WHERE BusinessID = :bid AND IsDismissed = 0
          AND (ExpiresAt IS NULL OR ExpiresAt > GETDATE())
    """
    params: dict = {"bid": business_id}
    if unread_only:
        q += " AND IsRead = 0"
    if severity:
        q += " AND Severity = :sev"
        params["sev"] = severity
    q += " ORDER BY CASE Severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, CreatedAt DESC"
    rows = db.execute(text(q), params).fetchall()
    return [_alert_row(r) for r in rows]


@router.post("/alerts")
def create_alert(payload: dict, db: Session = Depends(get_db)):
    _ensure_tables(db)
    bid = payload.get("business_id") or payload.get("BusinessID")
    db.execute(text("""
        INSERT INTO FarmAlert
            (BusinessID, AlertType, Severity, Title, Message, Source, SourceID, ExpiresAt)
        VALUES (:bid, :atype, :sev, :title, :msg, :src, :sid, :exp)
    """), {
        "bid":   bid,
        "atype": payload.get("alert_type", "general"),
        "sev":   payload.get("severity", "warning"),
        "title": payload.get("title", ""),
        "msg":   payload.get("message", ""),
        "src":   payload.get("source"),
        "sid":   payload.get("source_id"),
        "exp":   payload.get("expires_at"),
    })
    db.commit()
    return {"ok": True}


@router.put("/alerts/{alert_id}/read")
def mark_alert_read(alert_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(text("UPDATE FarmAlert SET IsRead = 1 WHERE AlertID = :id AND BusinessID = :bid"),
               {"id": alert_id, "bid": business_id})
    db.commit()
    return {"ok": True}


@router.put("/alerts/{alert_id}/dismiss")
def dismiss_alert(alert_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(text("UPDATE FarmAlert SET IsDismissed = 1 WHERE AlertID = :id AND BusinessID = :bid"),
               {"id": alert_id, "bid": business_id})
    db.commit()
    return {"ok": True}


# ── Weather Alerts ────────────────────────────────────────────────────────────

@router.get("/weather-alerts")
def list_weather_alerts(business_id: int = Query(...), unread_only: bool = False, db: Session = Depends(get_db)):
    _ensure_tables(db)
    q = """
        SELECT * FROM FarmWeatherAlert WHERE BusinessID = :bid
        AND (ValidUntil IS NULL OR ValidUntil > GETDATE())
    """
    params: dict = {"bid": business_id}
    if unread_only:
        q += " AND IsRead = 0"
    q += " ORDER BY CASE Severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, CreatedAt DESC"
    rows = db.execute(text(q), params).fetchall()
    return [_weather_alert_row(r) for r in rows]


@router.post("/weather-alerts")
def create_weather_alert(payload: dict, db: Session = Depends(get_db)):
    _ensure_tables(db)
    import json
    bid = payload.get("business_id") or payload.get("BusinessID")
    db.execute(text("""
        INSERT INTO FarmWeatherAlert
            (BusinessID, AlertType, Severity, CropName, FieldID, Title, Message,
             WeatherData, RecommendedAction, ValidUntil)
        VALUES (:bid, :atype, :sev, :crop, :fid, :title, :msg, :wdata, :rec, :valid)
    """), {
        "bid":   bid,
        "atype": payload.get("alert_type", "frost"),
        "sev":   payload.get("severity", "warning"),
        "crop":  payload.get("crop_name"),
        "fid":   payload.get("field_id"),
        "title": payload.get("title", ""),
        "msg":   payload.get("message", ""),
        "wdata": json.dumps(payload.get("weather_data")) if payload.get("weather_data") else None,
        "rec":   payload.get("recommended_action"),
        "valid": payload.get("valid_until"),
    })
    db.commit()
    return {"ok": True}


@router.put("/weather-alerts/{alert_id}/read")
def mark_weather_alert_read(alert_id: int, business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(text("UPDATE FarmWeatherAlert SET IsRead = 1 WHERE WeatherAlertID = :id AND BusinessID = :bid"),
               {"id": alert_id, "bid": business_id})
    db.commit()
    return {"ok": True}


# ── Pest Observations ─────────────────────────────────────────────────────────

@router.get("/pest-observations")
def list_pest_observations(
    business_id: int = Query(...),
    field_id: Optional[int] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    q = "SELECT * FROM FarmPestObservation WHERE BusinessID = :bid"
    params: dict = {"bid": business_id}
    if field_id:
        q += " AND FieldID = :fid"
        params["fid"] = field_id
    if status:
        q += " AND Status = :st"
        params["st"] = status
    q += " ORDER BY ObservationDate DESC"
    rows = db.execute(text(q), params).fetchall()
    return [_pest_row(r) for r in rows]


@router.post("/pest-observations")
def create_pest_observation(payload: dict, db: Session = Depends(get_db)):
    _ensure_tables(db)
    bid = payload.get("business_id") or payload.get("BusinessID")
    row = db.execute(text("""
        INSERT INTO FarmPestObservation
            (BusinessID, FieldID, FieldName, CropName, PestName, PestType,
             SeverityLevel, ObservationDate, AffectedArea, Notes, PhotoURL,
             TreatmentRequired, Status)
        OUTPUT INSERTED.ObsID
        VALUES (:bid, :fid, :fname, :crop, :pest, :ptype,
                :sev, :date, :area, :notes, :photo, :treat, :status)
    """), {
        "bid":    bid,
        "fid":    payload.get("field_id"),
        "fname":  payload.get("field_name"),
        "crop":   payload.get("crop_name"),
        "pest":   payload.get("pest_name", ""),
        "ptype":  payload.get("pest_type", "insect"),
        "sev":    payload.get("severity_level", "low"),
        "date":   payload.get("observation_date", date.today().isoformat()),
        "area":   payload.get("affected_area"),
        "notes":  payload.get("notes"),
        "photo":  payload.get("photo_url"),
        "treat":  1 if payload.get("treatment_required") else 0,
        "status": payload.get("status", "observed"),
    }).fetchone()
    obs_id = row[0]

    # Auto-create a farm alert for high severity
    if payload.get("severity_level") in ("high", "critical"):
        db.execute(text("""
            INSERT INTO FarmAlert
                (BusinessID, AlertType, Severity, Title, Message, Source, SourceID)
            VALUES (:bid, 'pest', :sev, :title, :msg, 'pest_observation', :sid)
        """), {
            "bid":   bid,
            "sev":   "critical" if payload.get("severity_level") == "critical" else "warning",
            "title": f"Pest Alert: {payload.get('pest_name', 'Unknown')} on {payload.get('crop_name', 'crop')}",
            "msg":   f"{payload.get('severity_level', 'high').title()} severity {payload.get('pest_name', 'pest')} "
                     f"observed{' on ' + payload['field_name'] if payload.get('field_name') else ''}. "
                     f"Treatment {'required' if payload.get('treatment_required') else 'may be needed'}.",
            "sid":   obs_id,
        })

    db.commit()

    # Notify + auto-create a draft treatment work order when treatment is required
    if payload.get("treatment_required"):
        notify_business(
            db, bid,
            type="pest_treatment_required",
            title=f"Treatment Required: {payload.get('pest_name', 'Pest')}",
            body=(
                f"{payload.get('severity_level', 'unknown').title()} severity"
                + (f" on {payload['field_name']}" if payload.get('field_name') else "")
                + (f" ({payload['crop_name']})" if payload.get('crop_name') else "")
            ),
            link_path=f"/work-orders?BusinessID={bid}",
            entity_type="FarmPestObservation",
            entity_id=obs_id,
        )
        # Auto-create a draft "Treatment" work order linked to this pest observation
        try:
            title = f"Treat: {payload.get('pest_name', 'Pest')} — {payload.get('field_name') or payload.get('crop_name', 'Field')}"
            desc = (
                f"Auto-generated treatment work order for {payload.get('pest_type', 'pest')} "
                f"'{payload.get('pest_name', 'Unknown')}'. "
                f"Severity: {payload.get('severity_level', 'unknown')}. "
                + (f"Affected area: {payload.get('affected_area')}{payload.get('area_unit', '')}." if payload.get('affected_area') else "")
            )
            wo_row = db.execute(text("""
                INSERT INTO WorkOrder
                    (BusinessID, FieldID, Location, TaskType, Title, Description, Priority, Status)
                OUTPUT INSERTED.WOID
                VALUES (:bid, :fid, :loc, 'spraying', :title, :desc, :pri, 'open')
            """), {
                "bid":   bid,
                "fid":   payload.get("field_id"),
                "loc":   payload.get("field_name"),
                "title": title,
                "desc":  desc,
                "pri":   "urgent" if payload.get("severity_level") == "critical" else "high",
            }).fetchone()
            wo_id = wo_row[0]
            # Link the pest observation to this work order
            db.execute(text("""
                UPDATE FarmPestObservation
                SET WorkOrderID=:wid, Status='treatment_started'
                WHERE ObsID=:oid AND BusinessID=:bid
            """), {"wid": wo_id, "oid": obs_id, "bid": bid})
        except Exception as _e:
            print(f"[auto-wo] pest treatment WO creation failed: {_e}")
        db.commit()

    return {"obs_id": obs_id}


@router.put("/pest-observations/{obs_id}")
def update_pest_observation(obs_id: int, payload: dict, db: Session = Depends(get_db)):
    _ensure_tables(db)
    bid = payload.get("business_id") or payload.get("BusinessID")
    db.execute(text("""
        UPDATE FarmPestObservation SET
            SeverityLevel    = :sev,
            TreatmentRequired= :treat,
            WorkOrderID      = :woid,
            Status           = :status,
            Notes            = :notes
        WHERE ObsID = :id AND BusinessID = :bid
    """), {
        "id":     obs_id,
        "bid":    bid,
        "sev":    payload.get("severity_level"),
        "treat":  1 if payload.get("treatment_required") else 0,
        "woid":   payload.get("work_order_id"),
        "status": payload.get("status"),
        "notes":  payload.get("notes"),
    })
    db.commit()
    return {"ok": True}


# ── Unified Dashboard ─────────────────────────────────────────────────────────

@router.get("/dashboard")
def kpi_dashboard(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)

    # KPIs with latest values
    kpis = db.execute(text("""
        SELECT k.KPIID, k.KPIName, k.KPICategory, k.Unit,
               k.TargetValue, k.WarningThreshold, k.CriticalThreshold,
               k.ThresholdDirection,
               (SELECT TOP 1 Value FROM FarmKPIReading WHERE KPIID = k.KPIID ORDER BY ReadingDate DESC) AS LatestValue,
               (SELECT TOP 1 ReadingDate FROM FarmKPIReading WHERE KPIID = k.KPIID ORDER BY ReadingDate DESC) AS LatestDate
        FROM FarmKPI k WHERE k.BusinessID = :bid AND k.IsActive = 1
        ORDER BY k.SortOrder, k.KPIName
    """), {"bid": business_id}).fetchall()

    # Alert counts
    alert_counts = db.execute(text("""
        SELECT
            COUNT(*) AS total_unread,
            SUM(CASE WHEN Severity = 'critical' THEN 1 ELSE 0 END) AS critical_count,
            SUM(CASE WHEN Severity = 'warning' THEN 1 ELSE 0 END) AS warning_count
        FROM FarmAlert
        WHERE BusinessID = :bid AND IsRead = 0 AND IsDismissed = 0
          AND (ExpiresAt IS NULL OR ExpiresAt > GETDATE())
    """), {"bid": business_id}).fetchone()

    weather_unread = db.execute(text("""
        SELECT COUNT(*) FROM FarmWeatherAlert
        WHERE BusinessID = :bid AND IsRead = 0
          AND (ValidUntil IS NULL OR ValidUntil > GETDATE())
    """), {"bid": business_id}).scalar() or 0

    # Active pest observations
    active_pests = db.execute(text("""
        SELECT COUNT(*) FROM FarmPestObservation
        WHERE BusinessID = :bid AND Status IN ('observed', 'monitoring')
    """), {"bid": business_id}).scalar() or 0

    # Low stock inputs
    low_stock = db.execute(text("""
        SELECT COUNT(*) FROM FarmInput
        WHERE BusinessID = :bid AND IsActive = 1
          AND MinStockAlert IS NOT NULL AND CurrentStock <= MinStockAlert
    """), {"bid": business_id}).scalar() or 0

    # Overdue maintenance
    overdue_maint = db.execute(text("""
        SELECT COUNT(*) FROM FarmMaintenanceSchedule s
        JOIN FarmAsset a ON a.AssetID = s.AssetID
        WHERE s.BusinessID = :bid AND s.IsActive = 1
          AND s.NextDueDate < GETDATE() AND a.IsActive = 1
    """), {"bid": business_id}).scalar() or 0

    kpi_data = [_kpi_row(k) for k in kpis]

    return {
        "kpis": kpi_data,
        "alerts": {
            "total_unread":   alert_counts.total_unread or 0,
            "critical":       alert_counts.critical_count or 0,
            "warning":        alert_counts.warning_count or 0,
            "weather_unread": weather_unread,
        },
        "operations": {
            "active_pests":      active_pests,
            "low_stock_inputs":  low_stock,
            "overdue_maintenance": overdue_maint,
        },
    }


@router.get("/summary")
def kpi_summary(business_id: int = Query(...), db: Session = Depends(get_db)):
    """Lightweight operations + alert summary for the account home dashboard."""
    _ensure_tables(db)
    try:
        alert_counts = db.execute(text("""
            SELECT
                SUM(CASE WHEN Severity='critical' THEN 1 ELSE 0 END) AS critical_count
            FROM FarmAlert
            WHERE BusinessID=:bid AND IsRead=0 AND IsDismissed=0
              AND (ExpiresAt IS NULL OR ExpiresAt > GETDATE())
        """), {"bid": business_id}).fetchone()
        active_pests = db.execute(text(
            "SELECT COUNT(*) FROM FarmPestObservation WHERE BusinessID=:bid AND Status IN ('observed','monitoring')"
        ), {"bid": business_id}).scalar() or 0
        low_stock = db.execute(text(
            "SELECT COUNT(*) FROM FarmInput WHERE BusinessID=:bid AND IsActive=1 AND MinStockAlert IS NOT NULL AND CurrentStock<=MinStockAlert"
        ), {"bid": business_id}).scalar() or 0
        overdue_maint = db.execute(text(
            "SELECT COUNT(*) FROM FarmMaintenanceSchedule s JOIN FarmAsset a ON a.AssetID=s.AssetID"
            " WHERE s.BusinessID=:bid AND s.IsActive=1 AND s.NextDueDate<GETDATE() AND a.IsActive=1"
        ), {"bid": business_id}).scalar() or 0
    except Exception:
        return {"operations": {}, "alerts": {}}
    return {
        "operations": {
            "active_pests":        active_pests,
            "low_stock_inputs":    low_stock,
            "overdue_maintenance": overdue_maint,
        },
        "alerts": {"critical": alert_counts.critical_count or 0 if alert_counts else 0},
    }


# ── Serializers ───────────────────────────────────────────────────────────────

def _kpi_status(kpi) -> str:
    val = getattr(kpi, "LatestValue", None)
    if val is None:
        return "no_data"
    val = float(val)
    direction = kpi.ThresholdDirection or "below"
    crit = float(kpi.CriticalThreshold) if kpi.CriticalThreshold is not None else None
    warn = float(kpi.WarningThreshold) if kpi.WarningThreshold is not None else None
    if direction == "below":
        if crit is not None and val <= crit:
            return "critical"
        if warn is not None and val <= warn:
            return "warning"
    else:
        if crit is not None and val >= crit:
            return "critical"
        if warn is not None and val >= warn:
            return "warning"
    return "ok"


def _kpi_row(r) -> dict:
    latest_val = getattr(r, "LatestValue", None)
    latest_date = getattr(r, "LatestDate", None)
    target = float(r.TargetValue) if r.TargetValue is not None else None
    val = float(latest_val) if latest_val is not None else None
    pct = None
    if val is not None and target and target != 0:
        pct = round(val / target * 100, 1)
    return {
        "kpi_id":             r.KPIID,
        "kpi_name":           r.KPIName,
        "kpi_category":       r.KPICategory,
        "kpi_key":            r.KPIKey,
        "unit":               r.Unit,
        "target_value":       target,
        "warning_threshold":  float(r.WarningThreshold) if r.WarningThreshold is not None else None,
        "critical_threshold": float(r.CriticalThreshold) if r.CriticalThreshold is not None else None,
        "threshold_direction": r.ThresholdDirection,
        "latest_value":       val,
        "latest_date":        latest_date.isoformat() if latest_date else None,
        "pct_of_target":      pct,
        "status":             _kpi_status(r),
    }


def _alert_row(r) -> dict:
    return {
        "alert_id":   r.AlertID,
        "alert_type": r.AlertType,
        "severity":   r.Severity,
        "title":      r.Title,
        "message":    r.Message,
        "source":     r.Source,
        "source_id":  r.SourceID,
        "is_read":    bool(r.IsRead),
        "expires_at": r.ExpiresAt.isoformat() if r.ExpiresAt else None,
        "created_at": r.CreatedAt.isoformat() if r.CreatedAt else None,
    }


def _weather_alert_row(r) -> dict:
    import json
    return {
        "weather_alert_id":   r.WeatherAlertID,
        "alert_type":         r.AlertType,
        "severity":           r.Severity,
        "crop_name":          r.CropName,
        "field_id":           r.FieldID,
        "title":              r.Title,
        "message":            r.Message,
        "weather_data":       json.loads(r.WeatherData) if r.WeatherData else None,
        "recommended_action": r.RecommendedAction,
        "is_read":            bool(r.IsRead),
        "valid_until":        r.ValidUntil.isoformat() if r.ValidUntil else None,
        "created_at":         r.CreatedAt.isoformat() if r.CreatedAt else None,
    }


def _pest_row(r) -> dict:
    return {
        "obs_id":           r.ObsID,
        "field_id":         r.FieldID,
        "field_name":       r.FieldName,
        "crop_name":        r.CropName,
        "pest_name":        r.PestName,
        "pest_type":        r.PestType,
        "severity_level":   r.SeverityLevel,
        "observation_date": r.ObservationDate.isoformat() if r.ObservationDate else None,
        "affected_area":    float(r.AffectedArea) if r.AffectedArea is not None else None,
        "notes":            r.Notes,
        "photo_url":        r.PhotoURL,
        "treatment_required": bool(r.TreatmentRequired),
        "work_order_id":    r.WorkOrderID,
        "status":           r.Status,
        "created_at":       r.CreatedAt.isoformat() if r.CreatedAt else None,
    }


# ── Farm P&L Report ───────────────────────────────────────────────────────────

@router.get("/pnl")
def farm_pnl_report(
    business_id: int = Query(...),
    crop_year: Optional[int] = None,
    crop_name: Optional[str] = None,
    field_id: Optional[int] = None,
    fmt: Optional[str] = Query(None, alias="format"),
    db: Session = Depends(get_db),
):
    """
    Per-crop P&L combining CropBudget (planned vs actual), FarmInputTransaction usage costs,
    and WorkOrder actual costs keyed by FieldID.
    """
    _ensure_tables(db)

    year_filter = crop_year or date.today().year

    # ── Base: one row per CropBudget ─────────────────────────────────────────
    q_params: dict = {"bid": business_id, "yr": year_filter}
    budget_sql = """
        SELECT
            b.BudgetID, b.FieldID, ISNULL(b.FieldName,'') AS FieldName,
            b.CropName, b.CropYear, b.Season,
            ISNULL(b.PlantedAcres,0)    AS PlantedAcres,
            ISNULL(b.ExpectedYield,0)   AS ExpectedYield,
            ISNULL(b.ActualYield,0)     AS ActualYield,
            ISNULL(b.YieldUnit,'')      AS YieldUnit,
            ISNULL(b.BudgetedRevenue,0) AS BudgetedRevenue,
            ISNULL(b.ActualRevenue,0)   AS ActualRevenue,
            ISNULL(b.BudgetedCost,0)    AS BudgetedCost,
            ISNULL(b.ActualCost,0)      AS BudgetActualCost,
            b.Status
        FROM CropBudget b
        WHERE b.BusinessID=:bid AND b.CropYear=:yr
    """
    if crop_name:
        budget_sql += " AND b.CropName=:cn"; q_params["cn"] = crop_name
    if field_id:
        budget_sql += " AND b.FieldID=:fid"; q_params["fid"] = field_id
    budget_sql += " ORDER BY b.CropName, b.FieldName"

    budgets = db.execute(text(budget_sql), q_params).fetchall()

    # ── Input usage costs by crop_name + field_id ────────────────────────────
    input_costs = db.execute(text("""
        SELECT
            CropName,
            FieldID,
            ISNULL(SUM(TotalCost),0) AS InputCost
        FROM FarmInputTransaction
        WHERE BusinessID=:bid
          AND TxType='usage'
          AND YEAR(CreatedAt)=:yr
        GROUP BY CropName, FieldID
    """), {"bid": business_id, "yr": year_filter}).fetchall()

    input_cost_map: dict = {}
    for ic in input_costs:
        key = (ic.CropName or "", ic.FieldID)
        input_cost_map[key] = float(ic.InputCost or 0)

    # ── Work order actual costs by field_id ──────────────────────────────────
    wo_costs = db.execute(text("""
        SELECT
            FieldID,
            ISNULL(SUM(ActualCost),0) AS WOCost
        FROM WorkOrder
        WHERE BusinessID=:bid
          AND YEAR(CreatedAt)=:yr
          AND ActualCost IS NOT NULL
        GROUP BY FieldID
    """), {"bid": business_id, "yr": year_filter}).fetchall()

    wo_cost_map: dict = {(wc.FieldID): float(wc.WOCost or 0) for wc in wo_costs}

    # ── Harvest lots by crop_name + field_id ─────────────────────────────────
    harvest_rows = db.execute(text("""
        SELECT
            CropName, FieldID,
            ISNULL(SUM(Quantity),0) AS HarvestQty,
            MAX(Unit) AS Unit
        FROM HarvestLot
        WHERE BusinessID=:bid AND YEAR(HarvestDate)=:yr
        GROUP BY CropName, FieldID
    """), {"bid": business_id, "yr": year_filter}).fetchall()

    harvest_map: dict = {}
    for hr in harvest_rows:
        key = (hr.CropName or "", hr.FieldID)
        harvest_map[key] = {"qty": float(hr.HarvestQty or 0), "unit": hr.Unit or ""}

    # ── Assemble rows ─────────────────────────────────────────────────────────
    rows = []
    for b in budgets:
        key_exact = (b.CropName, b.FieldID)
        key_crop  = (b.CropName, None)

        # Prefer exact field match; fall back to crop-only
        inp_cost = input_cost_map.get(key_exact, 0) or input_cost_map.get(key_crop, 0)
        wo_cost  = wo_cost_map.get(b.FieldID, 0)
        harvest  = harvest_map.get(key_exact) or harvest_map.get(key_crop) or {}

        total_actual_cost   = float(b.BudgetActualCost) + inp_cost + wo_cost
        budgeted_profit     = float(b.BudgetedRevenue) - float(b.BudgetedCost)
        actual_profit       = float(b.ActualRevenue)   - total_actual_cost
        profit_variance     = actual_profit - budgeted_profit

        rows.append({
            "budget_id":         b.BudgetID,
            "crop_name":         b.CropName,
            "field_name":        b.FieldName,
            "field_id":          b.FieldID,
            "crop_year":         b.CropYear,
            "season":            b.Season,
            "planted_acres":     float(b.PlantedAcres),
            "expected_yield":    float(b.ExpectedYield),
            "actual_yield":      float(b.ActualYield) or harvest.get("qty", 0),
            "yield_unit":        b.YieldUnit or harvest.get("unit", ""),
            "budgeted_revenue":  float(b.BudgetedRevenue),
            "actual_revenue":    float(b.ActualRevenue),
            "budgeted_cost":     float(b.BudgetedCost),
            "budget_actual_cost":float(b.BudgetActualCost),
            "input_usage_cost":  inp_cost,
            "work_order_cost":   wo_cost,
            "total_actual_cost": total_actual_cost,
            "budgeted_profit":   budgeted_profit,
            "actual_profit":     actual_profit,
            "profit_variance":   profit_variance,
            "status":            b.Status,
        })

    # ── Totals ────────────────────────────────────────────────────────────────
    def _sum(field): return round(sum(r[field] for r in rows), 2)
    totals = {
        "budgeted_revenue":  _sum("budgeted_revenue"),
        "actual_revenue":    _sum("actual_revenue"),
        "budgeted_cost":     _sum("budgeted_cost"),
        "total_actual_cost": _sum("total_actual_cost"),
        "budgeted_profit":   _sum("budgeted_profit"),
        "actual_profit":     _sum("actual_profit"),
        "profit_variance":   _sum("profit_variance"),
    }

    # ── CSV export ────────────────────────────────────────────────────────────
    if fmt == "csv":
        out = io.StringIO()
        fields = [
            "crop_name","field_name","season","planted_acres",
            "expected_yield","actual_yield","yield_unit",
            "budgeted_revenue","actual_revenue",
            "budgeted_cost","total_actual_cost",
            "budgeted_profit","actual_profit","profit_variance","status",
        ]
        writer = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        # Totals row
        writer.writerow({
            "crop_name": "TOTAL", "field_name": "", "season": "", "planted_acres": "",
            "expected_yield": "", "actual_yield": "", "yield_unit": "",
            "budgeted_revenue": totals["budgeted_revenue"],
            "actual_revenue":   totals["actual_revenue"],
            "budgeted_cost":    totals["budgeted_cost"],
            "total_actual_cost":totals["total_actual_cost"],
            "budgeted_profit":  totals["budgeted_profit"],
            "actual_profit":    totals["actual_profit"],
            "profit_variance":  totals["profit_variance"],
            "status": "",
        })
        return Response(
            content=out.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=farm_pnl_{year_filter}.csv"},
        )

    return {
        "report_date": date.today().isoformat(),
        "crop_year":   year_filter,
        "rows":        rows,
        "totals":      totals,
    }
