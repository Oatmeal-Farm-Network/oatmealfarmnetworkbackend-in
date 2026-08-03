# routers/field_health_alerts.py
# Proactive satellite field-health monitoring.
# Users set per-field NDVI drop thresholds; the frontend POSTs /check on page load,
# and the backend fires AppNotifications when NDVI newly crosses below threshold.
# Edge-triggered with a 24-hour cooldown between repeat notifications per field.
# POST /check-all is called by Cloud Scheduler (no user auth; SCHEDULER_SECRET header).

from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, engine, SessionLocal
from auth import get_current_user
from routers.notifications import create_notification
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import os
import logging

_log = logging.getLogger(__name__)
_SCHEDULER_SECRET = os.getenv("SCHEDULER_SECRET", "")

router = APIRouter(prefix="/api/field-health-alerts", tags=["field_health_alerts"])

try:
    with engine.begin() as _conn:
        _conn.execute(text("""
            IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='FieldHealthAlerts')
            BEGIN
                CREATE TABLE FieldHealthAlerts (
                    AlertID         INT IDENTITY(1,1) PRIMARY KEY,
                    PeopleID        INT           NOT NULL,
                    FieldID         INT           NOT NULL,
                    FieldName       NVARCHAR(200) NULL,
                    CropType        NVARCHAR(100) NULL,
                    NDVIThreshold   DECIMAL(6,4)  NOT NULL,
                    LastNotifiedAt  DATETIME      NULL,
                    LastCheckedNDVI DECIMAL(6,4)  NULL,
                    CreatedAt       DATETIME      NOT NULL DEFAULT GETDATE()
                )
                CREATE UNIQUE INDEX IX_FieldHealthAlerts_Field
                    ON FieldHealthAlerts (PeopleID, FieldID)
            END
        """))
except Exception as e:
    print(f"[field_health_alerts] Table ensure warning: {e}")


class FieldAlertCreate(BaseModel):
    field_id: int
    field_name: Optional[str] = None
    crop_type: Optional[str] = None
    ndvi_threshold: float


# ── Fields + current NDVI ─────────────────────────────────────────────────────

@router.get("/fields")
def list_fields_with_ndvi(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Returns the user's CropMonitor fields with their latest NDVI reading."""
    biz_rows = db.execute(text(
        "SELECT BusinessID FROM BusinessAccess WHERE PeopleID = :pid AND (Active IS NULL OR Active = 1)"
    ), {"pid": user.PeopleID}).scalars().all()
    if not biz_rows:
        return []

    placeholders = ",".join([f":b{i}" for i in range(len(biz_rows))])
    params = {f"b{i}": bid for i, bid in enumerate(biz_rows)}

    fields = db.execute(text(f"""
        SELECT FieldID, Name, CropType, FieldSizeHectares, MonitoringEnabled
        FROM dbo.Field
        WHERE BusinessID IN ({placeholders}) AND DeletedAt IS NULL
        ORDER BY Name
    """), params).mappings().all()

    result = []
    for f in fields:
        ndvi_row = db.execute(text("""
            SELECT TOP 1 vi.MeanValue, a.AnalysisDate
            FROM dbo.Analysis a
            JOIN dbo.VegetationIndex vi ON vi.AnalysisID = a.AnalysisID
            WHERE a.FieldID = :fid AND vi.IndexType = 'NDVI'
            ORDER BY a.AnalysisDate DESC
        """), {"fid": f["FieldID"]}).mappings().first()
        result.append({
            "field_id": f["FieldID"],
            "name": f["Name"] or f"Field #{f['FieldID']}",
            "crop_type": f["CropType"],
            "size_ha": float(f["FieldSizeHectares"]) if f["FieldSizeHectares"] else None,
            "monitoring_enabled": bool(f["MonitoringEnabled"]),
            "latest_ndvi": float(ndvi_row["MeanValue"]) if ndvi_row and ndvi_row["MeanValue"] is not None else None,
            "ndvi_date": (ndvi_row["AnalysisDate"].isoformat()
                          if ndvi_row and ndvi_row["AnalysisDate"] else None),
        })
    return result


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.get("")
def list_field_alerts(db: Session = Depends(get_db), user=Depends(get_current_user)):
    rows = db.execute(text("""
        SELECT AlertID, FieldID, FieldName, CropType, NDVIThreshold,
               LastNotifiedAt, LastCheckedNDVI, CreatedAt
        FROM FieldHealthAlerts WHERE PeopleID = :pid
        ORDER BY CreatedAt DESC
    """), {"pid": user.PeopleID}).mappings().all()
    return [dict(r) for r in rows]


@router.post("")
def upsert_field_alert(body: FieldAlertCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if not (0.0 <= body.ndvi_threshold <= 1.0):
        raise HTTPException(400, "NDVI threshold must be between 0.0 and 1.0")

    existing = db.execute(text(
        "SELECT AlertID FROM FieldHealthAlerts WHERE PeopleID = :pid AND FieldID = :fid"
    ), {"pid": user.PeopleID, "fid": body.field_id}).scalar()

    if existing:
        db.execute(text("""
            UPDATE FieldHealthAlerts
            SET NDVIThreshold = :t, FieldName = :fn, CropType = :ct
            WHERE AlertID = :aid
        """), {"t": body.ndvi_threshold, "fn": body.field_name, "ct": body.crop_type, "aid": existing})
    else:
        count = db.execute(text(
            "SELECT COUNT(*) FROM FieldHealthAlerts WHERE PeopleID = :pid"
        ), {"pid": user.PeopleID}).scalar() or 0
        if count >= 20:
            raise HTTPException(400, "Maximum 20 field alerts per account")
        db.execute(text("""
            INSERT INTO FieldHealthAlerts (PeopleID, FieldID, FieldName, CropType, NDVIThreshold)
            VALUES (:pid, :fid, :fn, :ct, :t)
        """), {"pid": user.PeopleID, "fid": body.field_id, "fn": body.field_name,
               "ct": body.crop_type, "t": body.ndvi_threshold})

    db.commit()
    return {"ok": True}


@router.delete("/{alert_id}")
def delete_field_alert(alert_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    db.execute(text(
        "DELETE FROM FieldHealthAlerts WHERE AlertID = :aid AND PeopleID = :pid"
    ), {"aid": alert_id, "pid": user.PeopleID})
    db.commit()
    return {"ok": True}


# ── Check ─────────────────────────────────────────────────────────────────────

@router.post("/check")
def check_field_alerts(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Queries latest NDVI from CropMonitor satellite tables and fires AppNotifications
    when a field newly drops below the user's configured threshold.
    Edge-triggered: only fires on the crossing event, not while it stays below.
    24-hour cooldown between repeat notifications for the same field."""
    alerts = db.execute(text("""
        SELECT AlertID, FieldID, FieldName, CropType, NDVIThreshold,
               LastNotifiedAt, LastCheckedNDVI
        FROM FieldHealthAlerts WHERE PeopleID = :pid
    """), {"pid": user.PeopleID}).mappings().all()

    fired = 0
    for alert in alerts:
        ndvi_row = db.execute(text("""
            SELECT TOP 1 vi.MeanValue
            FROM dbo.Analysis a
            JOIN dbo.VegetationIndex vi ON vi.AnalysisID = a.AnalysisID
            WHERE a.FieldID = :fid AND vi.IndexType = 'NDVI'
            ORDER BY a.AnalysisDate DESC
        """), {"fid": alert["FieldID"]}).mappings().first()

        if not ndvi_row or ndvi_row["MeanValue"] is None:
            continue

        current    = float(ndvi_row["MeanValue"])
        threshold  = float(alert["NDVIThreshold"])
        last_ndvi  = float(alert["LastCheckedNDVI"]) if alert["LastCheckedNDVI"] is not None else None
        last_notif = alert["LastNotifiedAt"]

        below_now   = current <= threshold
        was_below   = last_ndvi is not None and last_ndvi <= threshold
        on_cooldown = last_notif is not None and (
            (datetime.utcnow() - last_notif).total_seconds() < 86400
        )

        if below_now and not was_below and not on_cooldown:
            field_name = alert["FieldName"] or f"Field #{alert['FieldID']}"
            crop       = alert["CropType"] or "crop"
            create_notification(
                db,
                people_id=user.PeopleID,
                type="field_health_alert",
                title=f"{field_name} health alert",
                body=(
                    f"{field_name} ({crop}) NDVI is {current:.3f} — {_describe_ndvi(current)}. "
                    f"Below your alert threshold of {threshold:.3f}."
                ),
                link_path="/crop-monitor",
            )
            db.execute(text("""
                UPDATE FieldHealthAlerts
                SET LastNotifiedAt = GETDATE(), LastCheckedNDVI = :n
                WHERE AlertID = :aid
            """), {"n": current, "aid": alert["AlertID"]})
            fired += 1
        else:
            db.execute(
                text("UPDATE FieldHealthAlerts SET LastCheckedNDVI = :n WHERE AlertID = :aid"),
                {"n": current, "aid": alert["AlertID"]},
            )

    db.commit()
    return {"ok": True, "fired": fired}


def _describe_ndvi(v: float) -> str:
    if v >= 0.7: return "very healthy"
    if v >= 0.5: return "healthy"
    if v >= 0.3: return "moderately stressed"
    if v >= 0.1: return "significantly stressed"
    return "severely degraded"


def _run_check_all() -> dict:
    """Core logic for the scheduled all-user NDVI check. Runs in its own DB session."""
    fired = 0
    skipped = 0
    try:
        with SessionLocal() as db:
            alerts = db.execute(text("""
                SELECT AlertID, PeopleID, FieldID, FieldName, CropType,
                       NDVIThreshold, LastNotifiedAt, LastCheckedNDVI
                FROM FieldHealthAlerts
                ORDER BY PeopleID, FieldID
            """)).mappings().all()

            for alert in alerts:
                try:
                    ndvi_row = db.execute(text("""
                        SELECT TOP 1 vi.MeanValue
                        FROM dbo.Analysis a
                        JOIN dbo.VegetationIndex vi ON vi.AnalysisID = a.AnalysisID
                        WHERE a.FieldID = :fid AND vi.IndexType = 'NDVI'
                        ORDER BY a.AnalysisDate DESC
                    """), {"fid": alert["FieldID"]}).mappings().first()

                    if not ndvi_row or ndvi_row["MeanValue"] is None:
                        skipped += 1
                        continue

                    current   = float(ndvi_row["MeanValue"])
                    threshold = float(alert["NDVIThreshold"])
                    last_ndvi = float(alert["LastCheckedNDVI"]) if alert["LastCheckedNDVI"] is not None else None
                    last_notif = alert["LastNotifiedAt"]

                    below_now   = current <= threshold
                    was_below   = last_ndvi is not None and last_ndvi <= threshold
                    on_cooldown = last_notif is not None and (
                        (datetime.utcnow() - last_notif).total_seconds() < 86400
                    )

                    if below_now and not was_below and not on_cooldown:
                        field_name = alert["FieldName"] or f"Field #{alert['FieldID']}"
                        crop       = alert["CropType"] or "crop"
                        create_notification(
                            db,
                            people_id=alert["PeopleID"],
                            type="field_health_alert",
                            title=f"{field_name} health alert",
                            body=(
                                f"{field_name} ({crop}) NDVI is {current:.3f} — "
                                f"{_describe_ndvi(current)}. "
                                f"Below your alert threshold of {threshold:.3f}."
                            ),
                            link_path="/crop-monitor",
                        )
                        db.execute(text("""
                            UPDATE FieldHealthAlerts
                            SET LastNotifiedAt = GETDATE(), LastCheckedNDVI = :n
                            WHERE AlertID = :aid
                        """), {"n": current, "aid": alert["AlertID"]})
                        fired += 1
                    else:
                        db.execute(
                            text("UPDATE FieldHealthAlerts SET LastCheckedNDVI = :n WHERE AlertID = :aid"),
                            {"n": current, "aid": alert["AlertID"]},
                        )
                except Exception as e:
                    _log.warning(f"[field_health] alert {alert['AlertID']}: {e}")

            db.commit()
    except Exception as e:
        _log.error(f"[field_health] check_all error: {e}")

    return {"ok": True, "fired": fired, "skipped": skipped}


@router.post("/check-all")
def check_all_field_alerts(x_scheduler_secret: Optional[str] = Header(None, alias="X-Scheduler-Secret")):
    """System-level NDVI check across all users — called by Cloud Scheduler.
    Authenticated via X-Scheduler-Secret header (SCHEDULER_SECRET env var).
    No user JWT required."""
    if _SCHEDULER_SECRET and x_scheduler_secret != _SCHEDULER_SECRET:
        raise HTTPException(403, "Forbidden")
    return _run_check_all()
