# routers/market_alerts.py
# Commodity price alert thresholds per user.
# Frontend posts current live prices via /check; backend fires AppNotifications
# when a threshold is newly crossed (edge-triggered, not level-triggered).

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, engine
from auth import get_current_user
from routers.notifications import create_notification
from pydantic import BaseModel
from datetime import datetime

router = APIRouter(prefix="/api/market-alerts", tags=["market_alerts"])

# ── Auto-create table ────────────────────────────────────────────────────────
try:
    with engine.begin() as _conn:
        _conn.execute(text("""
            IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='MarketAlerts')
            BEGIN
                CREATE TABLE MarketAlerts (
                    AlertID          INT IDENTITY(1,1) PRIMARY KEY,
                    PeopleID         INT          NOT NULL,
                    Commodity        VARCHAR(80)  NOT NULL,
                    Direction        VARCHAR(10)  NOT NULL,
                    ThresholdPrice   DECIMAL(12,4) NOT NULL,
                    Unit             VARCHAR(20)  NULL,
                    LastNotifiedAt   DATETIME     NULL,
                    LastCheckedPrice DECIMAL(12,4) NULL,
                    CreatedAt        DATETIME     NOT NULL DEFAULT GETDATE()
                )
                CREATE INDEX IX_MarketAlerts_Person
                    ON MarketAlerts (PeopleID, CreatedAt DESC)
            END
        """))
except Exception as _e:
    print(f"MarketAlerts table setup error: {_e}")


# ── Schemas ──────────────────────────────────────────────────────────────────
class AlertCreate(BaseModel):
    commodity: str
    direction: str          # 'above' | 'below'
    threshold_price: float
    unit: str | None = None

class PriceItem(BaseModel):
    commodity: str
    price: float

class PriceCheckRequest(BaseModel):
    prices: list[PriceItem]


# ── Routes ───────────────────────────────────────────────────────────────────
@router.get("")
def list_alerts(db: Session = Depends(get_db), user=Depends(get_current_user)):
    rows = db.execute(text("""
        SELECT AlertID, Commodity, Direction, ThresholdPrice, Unit, LastNotifiedAt, CreatedAt
        FROM MarketAlerts
        WHERE PeopleID = :pid
        ORDER BY CreatedAt DESC
    """), {"pid": user.PeopleID}).mappings().all()
    return [dict(r) for r in rows]


@router.post("")
def create_alert(body: AlertCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if body.direction not in ("above", "below"):
        raise HTTPException(400, "direction must be 'above' or 'below'")
    count = db.execute(
        text("SELECT COUNT(*) FROM MarketAlerts WHERE PeopleID = :pid"),
        {"pid": user.PeopleID}
    ).scalar()
    if count >= 20:
        raise HTTPException(400, "Maximum 20 price alerts per account")
    db.execute(text("""
        INSERT INTO MarketAlerts (PeopleID, Commodity, Direction, ThresholdPrice, Unit)
        VALUES (:pid, :c, :d, :tp, :u)
    """), {
        "pid": user.PeopleID,
        "c": body.commodity,
        "d": body.direction,
        "tp": body.threshold_price,
        "u": body.unit,
    })
    db.commit()
    return {"ok": True}


@router.delete("/{alert_id}")
def delete_alert(alert_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    db.execute(
        text("DELETE FROM MarketAlerts WHERE AlertID = :aid AND PeopleID = :pid"),
        {"aid": alert_id, "pid": user.PeopleID}
    )
    db.commit()
    return {"ok": True}


@router.post("/check")
def check_alerts(body: PriceCheckRequest, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Called by the frontend after fetching live prices.
    Fires an AppNotification for each alert whose threshold is newly crossed.
    Edge-triggered: only fires when price crosses the threshold in the watched
    direction — not on every load while the price stays above/below.
    Re-notify cooldown: 4 hours minimum between repeat notifications."""
    price_map = {item.commodity.lower(): item.price for item in body.prices}

    # Log every submitted price to the history table for trend analysis / sparklines
    for item in body.prices:
        if item.price is not None:
            db.execute(text("""
                INSERT INTO CommodityPriceHistory (Commodity, PriceUSD)
                VALUES (:c, :p)
            """), {"c": item.commodity, "p": item.price})

    alerts = db.execute(text("""
        SELECT AlertID, Commodity, Direction, ThresholdPrice, Unit,
               LastNotifiedAt, LastCheckedPrice
        FROM MarketAlerts WHERE PeopleID = :pid
    """), {"pid": user.PeopleID}).mappings().all()

    fired = 0
    for alert in alerts:
        current = price_map.get(alert["Commodity"].lower())
        if current is None:
            continue

        threshold  = float(alert["ThresholdPrice"])
        direction  = alert["Direction"]
        last_price = float(alert["LastCheckedPrice"]) if alert["LastCheckedPrice"] is not None else None
        last_notif = alert["LastNotifiedAt"]

        crossed_now = (
            (direction == "above" and current >= threshold) or
            (direction == "below" and current <= threshold)
        )
        was_crossed = last_price is not None and (
            (direction == "above" and last_price >= threshold) or
            (direction == "below" and last_price <= threshold)
        )
        cooldown_active = last_notif is not None and (
            (datetime.utcnow() - last_notif).total_seconds() < 14400
        )

        if crossed_now and not was_crossed and not cooldown_active:
            unit = alert["Unit"] or ""
            label = "above" if direction == "above" else "below"
            create_notification(
                db,
                people_id=user.PeopleID,
                type="market_alert",
                title=f"{alert['Commodity']} price alert",
                body=(
                    f"{alert['Commodity']} is now ${current:,.2f}{' /' + unit if unit else ''} — "
                    f"{label} your alert of ${threshold:,.2f}"
                ),
                link_path="/commodity-prices",
            )
            db.execute(text("""
                UPDATE MarketAlerts
                SET LastNotifiedAt = GETDATE(), LastCheckedPrice = :p
                WHERE AlertID = :aid
            """), {"p": current, "aid": alert["AlertID"]})
            fired += 1
        else:
            db.execute(
                text("UPDATE MarketAlerts SET LastCheckedPrice = :p WHERE AlertID = :aid"),
                {"p": current, "aid": alert["AlertID"]}
            )

    db.commit()
    return {"ok": True, "fired": fired}
