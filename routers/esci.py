"""
ESCI — Enterprise Supply Chain Intelligence
All endpoints prefixed /api/esci/.
Tables: ESCISupplier, ESCIShipment, ESCIShipmentEvent, ESCIQualityTest,
        ESCIMarginRecord, ESCIMarketPrice, ESCIDemandForecast, ESCIYieldForecast,
        ESCIException, ESCIExceptionNote, ESCIEscalationRule, ESCISettings.
DDL is idempotent (IF NOT EXISTS guards).
"""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
import models

router = APIRouter(prefix="/api/esci", tags=["esci"])
logger = logging.getLogger("esci")

# ── DDL ──────────────────────────────────────────────────────────────────────

_DDL_STATEMENTS = [
    # Suppliers
    """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='ESCISupplier')
    CREATE TABLE ESCISupplier (
        SupplierID   INT IDENTITY PRIMARY KEY,
        BusinessID   INT NOT NULL,
        SupplierName NVARCHAR(200) NOT NULL,
        ContactName  NVARCHAR(200) NULL,
        Email        NVARCHAR(200) NULL,
        Phone        NVARCHAR(50)  NULL,
        Country      NVARCHAR(100) NULL,
        Category     NVARCHAR(100) NULL,
        PortalToken  NVARCHAR(100) NULL,
        IsActive     BIT NOT NULL DEFAULT 1,
        CreatedAt    DATETIME2 NOT NULL DEFAULT GETDATE()
    )""",
    """IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='UQ_ESCISupplier_Token')
    CREATE UNIQUE INDEX UQ_ESCISupplier_Token ON ESCISupplier (PortalToken)
    WHERE PortalToken IS NOT NULL""",
    # Shipments
    """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='ESCIShipment')
    CREATE TABLE ESCIShipment (
        ShipmentID          INT IDENTITY PRIMARY KEY,
        BusinessID          INT NOT NULL,
        SupplierID          INT NULL,
        ShipmentRef         NVARCHAR(100) NULL,
        Origin              NVARCHAR(200) NULL,
        Destination         NVARCHAR(200) NULL,
        DepartureDate       DATE NULL,
        ExpectedArrival     DATE NULL,
        ActualArrival       DATE NULL,
        Commodity           NVARCHAR(200) NULL,
        QuantityKg          DECIMAL(12,3) NULL,
        Status              NVARCHAR(50) NOT NULL DEFAULT 'pending',
        CarrierName         NVARCHAR(200) NULL,
        TrackingNumber      NVARCHAR(200) NULL,
        ContractPricePerKg  DECIMAL(10,4) NULL,
        TotalValue          DECIMAL(14,2) NULL,
        Notes               NVARCHAR(MAX) NULL,
        CreatedAt           DATETIME2 NOT NULL DEFAULT GETDATE(),
        UpdatedAt           DATETIME2 NOT NULL DEFAULT GETDATE()
    )""",
    # Shipment events (timeline)
    """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='ESCIShipmentEvent')
    CREATE TABLE ESCIShipmentEvent (
        EventID    INT IDENTITY PRIMARY KEY,
        ShipmentID INT NOT NULL,
        EventType  NVARCHAR(100) NOT NULL,
        Location   NVARCHAR(200) NULL,
        Notes      NVARCHAR(500) NULL,
        CreatedAt  DATETIME2 NOT NULL DEFAULT GETDATE()
    )""",
    # Quality tests
    """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='ESCIQualityTest')
    CREATE TABLE ESCIQualityTest (
        TestID            INT IDENTITY PRIMARY KEY,
        BusinessID        INT NOT NULL,
        ShipmentID        INT NULL,
        SupplierID        INT NULL,
        Commodity         NVARCHAR(200) NULL,
        TestDate          DATE NOT NULL,
        Grade             NVARCHAR(20) NULL,
        Score             DECIMAL(5,2) NULL,
        MoisturePercent   DECIMAL(5,2) NULL,
        ProteinPercent    DECIMAL(5,2) NULL,
        ImpuritiesPercent DECIMAL(5,2) NULL,
        TestType          NVARCHAR(100) NULL,
        TestedBy          NVARCHAR(200) NULL,
        PassFail          NVARCHAR(10) NULL,
        Notes             NVARCHAR(MAX) NULL,
        CreatedAt         DATETIME2 NOT NULL DEFAULT GETDATE()
    )""",
    # Margin records
    """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='ESCIMarginRecord')
    CREATE TABLE ESCIMarginRecord (
        MarginID         INT IDENTITY PRIMARY KEY,
        BusinessID       INT NOT NULL,
        Commodity        NVARCHAR(200) NOT NULL,
        Category         NVARCHAR(100) NULL,
        PurchaseDate     DATE NOT NULL,
        QuantityKg       DECIMAL(12,3) NULL,
        CostPerKg        DECIMAL(10,4) NOT NULL,
        SalesPricePerKg  DECIMAL(10,4) NULL,
        MarginPerKg      DECIMAL(10,4) NULL,
        MarginPercent    DECIMAL(7,4) NULL,
        Notes            NVARCHAR(500) NULL,
        CreatedAt        DATETIME2 NOT NULL DEFAULT GETDATE()
    )""",
    # Market prices
    """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='ESCIMarketPrice')
    CREATE TABLE ESCIMarketPrice (
        PriceID    INT IDENTITY PRIMARY KEY,
        BusinessID INT NOT NULL,
        Commodity  NVARCHAR(200) NOT NULL,
        PriceDate  DATE NOT NULL,
        PricePerKg DECIMAL(10,4) NOT NULL,
        Source     NVARCHAR(200) NULL,
        Region     NVARCHAR(200) NULL,
        CreatedAt  DATETIME2 NOT NULL DEFAULT GETDATE()
    )""",
    # Demand forecasts
    """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='ESCIDemandForecast')
    CREATE TABLE ESCIDemandForecast (
        ForecastID     INT IDENTITY PRIMARY KEY,
        BusinessID     INT NOT NULL,
        Commodity      NVARCHAR(200) NOT NULL,
        ForecastPeriod NVARCHAR(50) NULL,
        ForecastDate   DATE NOT NULL,
        DemandKg       DECIMAL(12,3) NOT NULL,
        Confidence     DECIMAL(5,2) NULL,
        Method         NVARCHAR(100) NULL,
        Notes          NVARCHAR(500) NULL,
        CreatedAt      DATETIME2 NOT NULL DEFAULT GETDATE()
    )""",
    # Yield forecasts
    """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='ESCIYieldForecast')
    CREATE TABLE ESCIYieldForecast (
        YieldID        INT IDENTITY PRIMARY KEY,
        BusinessID     INT NOT NULL,
        Commodity      NVARCHAR(200) NOT NULL,
        ForecastPeriod NVARCHAR(50) NULL,
        ForecastDate   DATE NOT NULL,
        ExpectedYieldKg DECIMAL(12,3) NOT NULL,
        Confidence     DECIMAL(5,2) NULL,
        FieldID        INT NULL,
        Notes          NVARCHAR(500) NULL,
        CreatedAt      DATETIME2 NOT NULL DEFAULT GETDATE()
    )""",
    # Exceptions
    """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='ESCIException')
    CREATE TABLE ESCIException (
        ExceptionID  INT IDENTITY PRIMARY KEY,
        BusinessID   INT NOT NULL,
        Title        NVARCHAR(500) NOT NULL,
        Description  NVARCHAR(MAX) NULL,
        Severity     NVARCHAR(20) NOT NULL DEFAULT 'medium',
        Status       NVARCHAR(20) NOT NULL DEFAULT 'open',
        Category     NVARCHAR(100) NULL,
        ShipmentID   INT NULL,
        SupplierID   INT NULL,
        AssignedTo   NVARCHAR(200) NULL,
        ResolvedAt   DATETIME2 NULL,
        EscalatedAt  DATETIME2 NULL,
        CreatedAt    DATETIME2 NOT NULL DEFAULT GETDATE(),
        UpdatedAt    DATETIME2 NOT NULL DEFAULT GETDATE()
    )""",
    # Exception notes
    """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='ESCIExceptionNote')
    CREATE TABLE ESCIExceptionNote (
        NoteID      INT IDENTITY PRIMARY KEY,
        ExceptionID INT NOT NULL,
        Author      NVARCHAR(200) NULL,
        Body        NVARCHAR(MAX) NOT NULL,
        CreatedAt   DATETIME2 NOT NULL DEFAULT GETDATE()
    )""",
    # Escalation rules
    """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='ESCIEscalationRule')
    CREATE TABLE ESCIEscalationRule (
        RuleID      INT IDENTITY PRIMARY KEY,
        BusinessID  INT NOT NULL,
        RuleName    NVARCHAR(200) NOT NULL,
        Condition   NVARCHAR(MAX) NULL,
        Action      NVARCHAR(MAX) NULL,
        IsActive    BIT NOT NULL DEFAULT 1,
        LastRunAt   DATETIME2 NULL,
        CreatedAt   DATETIME2 NOT NULL DEFAULT GETDATE()
    )""",
    # Settings
    """IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='ESCISettings')
    CREATE TABLE ESCISettings (
        SettingsID             INT IDENTITY PRIMARY KEY,
        BusinessID             INT NOT NULL,
        Currency               NVARCHAR(10) NOT NULL DEFAULT 'USD',
        AlertLeadDays          INT NOT NULL DEFAULT 7,
        QualityGradeThreshold  NVARCHAR(10) NOT NULL DEFAULT 'C',
        MarginThresholdPercent DECIMAL(5,2) NOT NULL DEFAULT 10.0,
        EmailNotifications     BIT NOT NULL DEFAULT 1,
        UpdatedAt              DATETIME2 NOT NULL DEFAULT GETDATE(),
        CONSTRAINT UQ_ESCISettings_Biz UNIQUE (BusinessID)
    )""",
]

_ddl_done = False

def _ensure_tables(db: Session):
    global _ddl_done
    if _ddl_done:
        return
    for stmt in _DDL_STATEMENTS:
        try:
            db.execute(text(stmt))
            db.commit()
        except Exception as e:
            db.rollback()
            logger.warning("ESCI DDL skipped: %s", e)
    _ddl_done = True


# ── Pydantic models ───────────────────────────────────────────────────────────

class ShipmentIn(BaseModel):
    supplier_id: Optional[int] = None
    shipment_ref: Optional[str] = None
    origin: Optional[str] = None
    destination: Optional[str] = None
    departure_date: Optional[str] = None
    expected_arrival: Optional[str] = None
    actual_arrival: Optional[str] = None
    commodity: Optional[str] = None
    quantity_kg: Optional[float] = None
    status: Optional[str] = "pending"
    carrier_name: Optional[str] = None
    tracking_number: Optional[str] = None
    contract_price_per_kg: Optional[float] = None
    total_value: Optional[float] = None
    notes: Optional[str] = None


class SupplierIn(BaseModel):
    supplier_name: str
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    country: Optional[str] = None
    category: Optional[str] = None


class QualityTestIn(BaseModel):
    shipment_id: Optional[int] = None
    supplier_id: Optional[int] = None
    commodity: Optional[str] = None
    test_date: str
    grade: Optional[str] = None
    score: Optional[float] = None
    moisture_percent: Optional[float] = None
    protein_percent: Optional[float] = None
    impurities_percent: Optional[float] = None
    test_type: Optional[str] = None
    tested_by: Optional[str] = None
    pass_fail: Optional[str] = None
    notes: Optional[str] = None


class MarginRecordIn(BaseModel):
    commodity: str
    category: Optional[str] = None
    purchase_date: str
    quantity_kg: Optional[float] = None
    cost_per_kg: float
    sales_price_per_kg: Optional[float] = None
    notes: Optional[str] = None


class DemandForecastIn(BaseModel):
    commodity: str
    forecast_period: Optional[str] = None
    forecast_date: str
    demand_kg: float
    confidence: Optional[float] = None
    method: Optional[str] = None
    notes: Optional[str] = None


class YieldForecastIn(BaseModel):
    commodity: str
    forecast_period: Optional[str] = None
    forecast_date: str
    expected_yield_kg: float
    confidence: Optional[float] = None
    field_id: Optional[int] = None
    notes: Optional[str] = None


class ExceptionPatchIn(BaseModel):
    status: Optional[str] = None
    severity: Optional[str] = None
    assigned_to: Optional[str] = None


class ExceptionNoteIn(BaseModel):
    body: str
    author: Optional[str] = None


class EscalationRuleIn(BaseModel):
    rule_name: str
    condition: Optional[str] = None
    action: Optional[str] = None
    is_active: Optional[bool] = True


class SettingsIn(BaseModel):
    currency: Optional[str] = None
    alert_lead_days: Optional[int] = None
    quality_grade_threshold: Optional[str] = None
    margin_threshold_percent: Optional[float] = None
    email_notifications: Optional[bool] = None


class PortalQualityIn(BaseModel):
    commodity: Optional[str] = None
    grade: Optional[str] = None
    score: Optional[float] = None
    moisture_percent: Optional[float] = None
    protein_percent: Optional[float] = None
    notes: Optional[str] = None


class PortalEventIn(BaseModel):
    event_type: str
    location: Optional[str] = None
    notes: Optional[str] = None
    shipment_ref: Optional[str] = None


# ── Helper ────────────────────────────────────────────────────────────────────

def _row_to_dict(row) -> dict:
    return {k: (v.isoformat() if isinstance(v, (datetime.date, datetime.datetime)) else v)
            for k, v in row._mapping.items()}


def _d(val: Optional[str]) -> Optional[datetime.date]:
    if not val:
        return None
    try:
        return datetime.date.fromisoformat(val)
    except Exception:
        return None


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/dashboard")
def get_dashboard(
    business_id: int = Query(...),
    db: Session = Depends(get_db),
    _user: models.People = Depends(get_current_user),
):
    _ensure_tables(db)
    bid = business_id

    # Shipment KPIs
    ship = db.execute(text("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN Status='in_transit' THEN 1 ELSE 0 END) AS in_transit,
            SUM(CASE WHEN Status='delayed' THEN 1 ELSE 0 END) AS delayed,
            SUM(CASE WHEN Status='delivered'
                      AND ActualArrival >= DATEADD(day,-30,CAST(GETDATE() AS DATE)) THEN 1 ELSE 0 END) AS delivered_30d,
            SUM(CASE WHEN Status='in_transit'
                      AND ExpectedArrival < CAST(GETDATE() AS DATE) THEN 1 ELSE 0 END) AS overdue
        FROM ESCIShipment WHERE BusinessID=:bid
    """), {"bid": bid}).fetchone()

    # Quality
    qual = db.execute(text("""
        SELECT
            COUNT(*) AS total_tests,
            AVG(CAST(Score AS FLOAT)) AS avg_score,
            SUM(CASE WHEN PassFail='pass' THEN 1 ELSE 0 END) AS passed,
            SUM(CASE WHEN PassFail='fail' THEN 1 ELSE 0 END) AS failed
        FROM ESCIQualityTest
        WHERE BusinessID=:bid AND TestDate >= DATEADD(day,-90,CAST(GETDATE() AS DATE))
    """), {"bid": bid}).fetchone()

    # Exceptions
    exc = db.execute(text("""
        SELECT
            COUNT(*) AS total_open,
            SUM(CASE WHEN Severity='critical' THEN 1 ELSE 0 END) AS critical,
            SUM(CASE WHEN Severity='high' THEN 1 ELSE 0 END) AS high_sev
        FROM ESCIException WHERE BusinessID=:bid AND Status NOT IN ('resolved')
    """), {"bid": bid}).fetchone()

    # Margin
    margin = db.execute(text("""
        SELECT AVG(CAST(MarginPercent AS FLOAT)) AS avg_margin
        FROM ESCIMarginRecord
        WHERE BusinessID=:bid AND PurchaseDate >= DATEADD(day,-90,CAST(GETDATE() AS DATE))
    """), {"bid": bid}).fetchone()

    # Suppliers
    sup_count = db.execute(text(
        "SELECT COUNT(*) FROM ESCISupplier WHERE BusinessID=:bid AND IsActive=1"
    ), {"bid": bid}).scalar()

    return {
        "shipments": {
            "total": ship.total or 0,
            "in_transit": ship.in_transit or 0,
            "delayed": ship.delayed or 0,
            "delivered_30d": ship.delivered_30d or 0,
            "overdue": ship.overdue or 0,
        },
        "quality": {
            "total_tests": qual.total_tests or 0,
            "avg_score": round(float(qual.avg_score), 1) if qual.avg_score else None,
            "passed": qual.passed or 0,
            "failed": qual.failed or 0,
        },
        "exceptions": {
            "total_open": exc.total_open or 0,
            "critical": exc.critical or 0,
            "high": exc.high_sev or 0,
        },
        "margin": {
            "avg_margin_percent": round(float(margin.avg_margin), 2) if margin.avg_margin else None,
        },
        "suppliers": {"active": sup_count or 0},
    }


# ── Shipments ─────────────────────────────────────────────────────────────────

@router.get("/shipments")
def list_shipments(
    business_id: int = Query(...),
    status: Optional[str] = Query(None),
    supplier_id: Optional[int] = Query(None),
    limit: int = Query(100),
    db: Session = Depends(get_db),
    _user: models.People = Depends(get_current_user),
):
    _ensure_tables(db)
    where = "WHERE s.BusinessID=:bid"
    params: Dict[str, Any] = {"bid": business_id}
    if status:
        where += " AND s.Status=:status"
        params["status"] = status
    if supplier_id:
        where += " AND s.SupplierID=:sid"
        params["sid"] = supplier_id
    rows = db.execute(text(f"""
        SELECT TOP (:lim) s.*, sup.SupplierName
        FROM ESCIShipment s
        LEFT JOIN ESCISupplier sup ON sup.SupplierID = s.SupplierID
        {where}
        ORDER BY s.CreatedAt DESC
    """), {**params, "lim": limit}).fetchall()
    return [_row_to_dict(r) for r in rows]


@router.post("/shipments", status_code=201)
def create_shipment(
    payload: ShipmentIn,
    business_id: int = Query(...),
    db: Session = Depends(get_db),
    _user: models.People = Depends(get_current_user),
):
    _ensure_tables(db)
    row = db.execute(text("""
        INSERT INTO ESCIShipment (
            BusinessID, SupplierID, ShipmentRef, Origin, Destination,
            DepartureDate, ExpectedArrival, ActualArrival,
            Commodity, QuantityKg, Status, CarrierName, TrackingNumber,
            ContractPricePerKg, TotalValue, Notes
        )
        OUTPUT INSERTED.ShipmentID
        VALUES (
            :bid, :sup, :ref, :org, :dst,
            :dep, :exp, :act,
            :com, :qty, :stat, :car, :trk,
            :cpkg, :tv, :notes
        )
    """), {
        "bid": business_id, "sup": payload.supplier_id, "ref": payload.shipment_ref,
        "org": payload.origin, "dst": payload.destination,
        "dep": _d(payload.departure_date), "exp": _d(payload.expected_arrival),
        "act": _d(payload.actual_arrival),
        "com": payload.commodity, "qty": payload.quantity_kg,
        "stat": payload.status or "pending",
        "car": payload.carrier_name, "trk": payload.tracking_number,
        "cpkg": payload.contract_price_per_kg, "tv": payload.total_value,
        "notes": payload.notes,
    }).fetchone()
    db.commit()
    return {"shipment_id": row[0]}


@router.patch("/shipments/{shipment_id}")
def update_shipment(
    shipment_id: int,
    payload: ShipmentIn,
    db: Session = Depends(get_db),
    _user: models.People = Depends(get_current_user),
):
    _ensure_tables(db)
    db.execute(text("""
        UPDATE ESCIShipment SET
            SupplierID=COALESCE(:sup, SupplierID),
            ShipmentRef=COALESCE(:ref, ShipmentRef),
            Origin=COALESCE(:org, Origin),
            Destination=COALESCE(:dst, Destination),
            DepartureDate=COALESCE(:dep, DepartureDate),
            ExpectedArrival=COALESCE(:exp, ExpectedArrival),
            ActualArrival=COALESCE(:act, ActualArrival),
            Commodity=COALESCE(:com, Commodity),
            QuantityKg=COALESCE(:qty, QuantityKg),
            Status=COALESCE(:stat, Status),
            CarrierName=COALESCE(:car, CarrierName),
            TrackingNumber=COALESCE(:trk, TrackingNumber),
            ContractPricePerKg=COALESCE(:cpkg, ContractPricePerKg),
            TotalValue=COALESCE(:tv, TotalValue),
            Notes=COALESCE(:notes, Notes),
            UpdatedAt=GETDATE()
        WHERE ShipmentID=:sid
    """), {
        "sid": shipment_id, "sup": payload.supplier_id, "ref": payload.shipment_ref,
        "org": payload.origin, "dst": payload.destination,
        "dep": _d(payload.departure_date), "exp": _d(payload.expected_arrival),
        "act": _d(payload.actual_arrival),
        "com": payload.commodity, "qty": payload.quantity_kg, "stat": payload.status,
        "car": payload.carrier_name, "trk": payload.tracking_number,
        "cpkg": payload.contract_price_per_kg, "tv": payload.total_value,
        "notes": payload.notes,
    })
    db.commit()
    return {"ok": True}


@router.delete("/shipments/{shipment_id}")
def delete_shipment(
    shipment_id: int,
    db: Session = Depends(get_db),
    _user: models.People = Depends(get_current_user),
):
    db.execute(text("DELETE FROM ESCIShipment WHERE ShipmentID=:sid"), {"sid": shipment_id})
    db.commit()
    return {"ok": True}


# ── Visibility (consolidated shipment map data) ────────────────────────────────

@router.get("/visibility")
def get_visibility(
    business_id: int = Query(...),
    days: int = Query(90),
    db: Session = Depends(get_db),
    _user: models.People = Depends(get_current_user),
):
    _ensure_tables(db)
    rows = db.execute(text("""
        SELECT s.ShipmentID, s.ShipmentRef, s.Origin, s.Destination,
               s.Status, s.ExpectedArrival, s.ActualArrival,
               s.Commodity, s.QuantityKg, s.CarrierName,
               sup.SupplierName, sup.Country
        FROM ESCIShipment s
        LEFT JOIN ESCISupplier sup ON sup.SupplierID = s.SupplierID
        WHERE s.BusinessID=:bid
          AND s.CreatedAt >= DATEADD(day,:neg_days,GETDATE())
        ORDER BY s.ExpectedArrival
    """), {"bid": business_id, "neg_days": -days}).fetchall()
    return [_row_to_dict(r) for r in rows]


# ── Suppliers ──────────────────────────────────────────────────────────────────

@router.get("/suppliers")
def list_suppliers(
    business_id: int = Query(...),
    db: Session = Depends(get_db),
    _user: models.People = Depends(get_current_user),
):
    _ensure_tables(db)
    rows = db.execute(text(
        "SELECT * FROM ESCISupplier WHERE BusinessID=:bid AND IsActive=1 ORDER BY SupplierName"
    ), {"bid": business_id}).fetchall()
    return [_row_to_dict(r) for r in rows]


@router.post("/suppliers", status_code=201)
def create_supplier(
    payload: SupplierIn,
    business_id: int = Query(...),
    db: Session = Depends(get_db),
    _user: models.People = Depends(get_current_user),
):
    _ensure_tables(db)
    token = str(uuid.uuid4()).replace("-", "")
    row = db.execute(text("""
        INSERT INTO ESCISupplier (BusinessID, SupplierName, ContactName, Email, Phone, Country, Category, PortalToken)
        OUTPUT INSERTED.SupplierID
        VALUES (:bid, :name, :contact, :email, :phone, :country, :cat, :tok)
    """), {
        "bid": business_id, "name": payload.supplier_name,
        "contact": payload.contact_name, "email": payload.email,
        "phone": payload.phone, "country": payload.country,
        "cat": payload.category, "tok": token,
    }).fetchone()
    db.commit()
    return {"supplier_id": row[0], "portal_token": token}


# ── Quality tests ─────────────────────────────────────────────────────────────

@router.get("/quality")
def list_quality(
    business_id: int = Query(...),
    supplier_id: Optional[int] = Query(None),
    limit: int = Query(50),
    db: Session = Depends(get_db),
    _user: models.People = Depends(get_current_user),
):
    _ensure_tables(db)
    where = "WHERE q.BusinessID=:bid"
    params: Dict[str, Any] = {"bid": business_id, "lim": limit}
    if supplier_id:
        where += " AND q.SupplierID=:sid"
        params["sid"] = supplier_id
    rows = db.execute(text(f"""
        SELECT TOP (:lim) q.*, sup.SupplierName
        FROM ESCIQualityTest q
        LEFT JOIN ESCISupplier sup ON sup.SupplierID = q.SupplierID
        {where}
        ORDER BY q.TestDate DESC, q.TestID DESC
    """), params).fetchall()
    return [_row_to_dict(r) for r in rows]


@router.post("/quality", status_code=201)
def create_quality_test(
    payload: QualityTestIn,
    business_id: int = Query(...),
    db: Session = Depends(get_db),
    _user: models.People = Depends(get_current_user),
):
    _ensure_tables(db)
    # Derive pass_fail from score if not provided
    pf = payload.pass_fail
    if not pf and payload.score is not None:
        pf = "pass" if payload.score >= 60 else "fail"
    row = db.execute(text("""
        INSERT INTO ESCIQualityTest (
            BusinessID, ShipmentID, SupplierID, Commodity, TestDate,
            Grade, Score, MoisturePercent, ProteinPercent, ImpuritiesPercent,
            TestType, TestedBy, PassFail, Notes
        )
        OUTPUT INSERTED.TestID
        VALUES (:bid, :ship, :sup, :com, :td,
                :grade, :score, :moist, :prot, :imp,
                :ttype, :tby, :pf, :notes)
    """), {
        "bid": business_id, "ship": payload.shipment_id, "sup": payload.supplier_id,
        "com": payload.commodity, "td": _d(payload.test_date),
        "grade": payload.grade, "score": payload.score,
        "moist": payload.moisture_percent, "prot": payload.protein_percent,
        "imp": payload.impurities_percent,
        "ttype": payload.test_type, "tby": payload.tested_by,
        "pf": pf, "notes": payload.notes,
    }).fetchone()
    db.commit()
    return {"test_id": row[0]}


# ── Yield forecasts ────────────────────────────────────────────────────────────

@router.get("/yield-forecasts")
def list_yield_forecasts(
    business_id: int = Query(...),
    db: Session = Depends(get_db),
    _user: models.People = Depends(get_current_user),
):
    _ensure_tables(db)
    rows = db.execute(text(
        "SELECT * FROM ESCIYieldForecast WHERE BusinessID=:bid ORDER BY ForecastDate DESC"
    ), {"bid": business_id}).fetchall()
    return [_row_to_dict(r) for r in rows]


@router.post("/yield-forecasts", status_code=201)
def create_yield_forecast(
    payload: YieldForecastIn,
    business_id: int = Query(...),
    db: Session = Depends(get_db),
    _user: models.People = Depends(get_current_user),
):
    _ensure_tables(db)
    row = db.execute(text("""
        INSERT INTO ESCIYieldForecast
            (BusinessID, Commodity, ForecastPeriod, ForecastDate, ExpectedYieldKg, Confidence, FieldID, Notes)
        OUTPUT INSERTED.YieldID
        VALUES (:bid, :com, :per, :fd, :ykg, :conf, :fid, :notes)
    """), {
        "bid": business_id, "com": payload.commodity, "per": payload.forecast_period,
        "fd": _d(payload.forecast_date), "ykg": payload.expected_yield_kg,
        "conf": payload.confidence, "fid": payload.field_id, "notes": payload.notes,
    }).fetchone()
    db.commit()
    return {"yield_id": row[0]}


# ── Demand forecasts ───────────────────────────────────────────────────────────

@router.get("/demand-forecasts")
def list_demand_forecasts(
    business_id: int = Query(...),
    db: Session = Depends(get_db),
    _user: models.People = Depends(get_current_user),
):
    _ensure_tables(db)
    rows = db.execute(text(
        "SELECT * FROM ESCIDemandForecast WHERE BusinessID=:bid ORDER BY ForecastDate DESC"
    ), {"bid": business_id}).fetchall()
    return [_row_to_dict(r) for r in rows]


@router.post("/demand-forecasts", status_code=201)
def create_demand_forecast(
    payload: DemandForecastIn,
    business_id: int = Query(...),
    db: Session = Depends(get_db),
    _user: models.People = Depends(get_current_user),
):
    _ensure_tables(db)
    row = db.execute(text("""
        INSERT INTO ESCIDemandForecast
            (BusinessID, Commodity, ForecastPeriod, ForecastDate, DemandKg, Confidence, Method, Notes)
        OUTPUT INSERTED.ForecastID
        VALUES (:bid, :com, :per, :fd, :dkg, :conf, :meth, :notes)
    """), {
        "bid": business_id, "com": payload.commodity, "per": payload.forecast_period,
        "fd": _d(payload.forecast_date), "dkg": payload.demand_kg,
        "conf": payload.confidence, "meth": payload.method, "notes": payload.notes,
    }).fetchone()
    db.commit()
    return {"forecast_id": row[0]}


# ── Margins ────────────────────────────────────────────────────────────────────

@router.get("/margins")
def list_margins(
    business_id: int = Query(...),
    limit: int = Query(100),
    db: Session = Depends(get_db),
    _user: models.People = Depends(get_current_user),
):
    _ensure_tables(db)
    rows = db.execute(text(
        "SELECT TOP (:lim) * FROM ESCIMarginRecord WHERE BusinessID=:bid ORDER BY PurchaseDate DESC"
    ), {"bid": business_id, "lim": limit}).fetchall()
    return [_row_to_dict(r) for r in rows]


@router.post("/margins", status_code=201)
def create_margin_record(
    payload: MarginRecordIn,
    business_id: int = Query(...),
    db: Session = Depends(get_db),
    _user: models.People = Depends(get_current_user),
):
    _ensure_tables(db)
    margin_per_kg = None
    margin_pct = None
    if payload.sales_price_per_kg is not None and payload.cost_per_kg:
        margin_per_kg = payload.sales_price_per_kg - payload.cost_per_kg
        if payload.cost_per_kg != 0:
            margin_pct = (margin_per_kg / payload.cost_per_kg) * 100
    row = db.execute(text("""
        INSERT INTO ESCIMarginRecord
            (BusinessID, Commodity, Category, PurchaseDate, QuantityKg,
             CostPerKg, SalesPricePerKg, MarginPerKg, MarginPercent, Notes)
        OUTPUT INSERTED.MarginID
        VALUES (:bid, :com, :cat, :pd, :qty, :cost, :sale, :mpkg, :mpct, :notes)
    """), {
        "bid": business_id, "com": payload.commodity, "cat": payload.category,
        "pd": _d(payload.purchase_date), "qty": payload.quantity_kg,
        "cost": payload.cost_per_kg, "sale": payload.sales_price_per_kg,
        "mpkg": margin_per_kg, "mpct": margin_pct, "notes": payload.notes,
    }).fetchone()
    db.commit()
    return {"margin_id": row[0]}


@router.get("/margins/summary")
def margins_summary(
    business_id: int = Query(...),
    days: int = Query(90),
    db: Session = Depends(get_db),
    _user: models.People = Depends(get_current_user),
):
    _ensure_tables(db)
    rows = db.execute(text("""
        SELECT Commodity, Category,
               COUNT(*) AS records,
               AVG(CAST(MarginPercent AS FLOAT)) AS avg_margin_pct,
               AVG(CAST(MarginPerKg AS FLOAT)) AS avg_margin_per_kg,
               SUM(CAST(QuantityKg AS FLOAT)) AS total_kg
        FROM ESCIMarginRecord
        WHERE BusinessID=:bid
          AND PurchaseDate >= DATEADD(day,:neg,CAST(GETDATE() AS DATE))
        GROUP BY Commodity, Category
        ORDER BY avg_margin_pct DESC
    """), {"bid": business_id, "neg": -days}).fetchall()
    return [_row_to_dict(r) for r in rows]


# ── Market prices ──────────────────────────────────────────────────────────────

@router.get("/market-prices")
def list_market_prices(
    business_id: int = Query(...),
    commodity: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _user: models.People = Depends(get_current_user),
):
    _ensure_tables(db)
    where = "WHERE BusinessID=:bid"
    params: Dict[str, Any] = {"bid": business_id}
    if commodity:
        where += " AND Commodity=:com"
        params["com"] = commodity
    rows = db.execute(text(
        f"SELECT TOP 200 * FROM ESCIMarketPrice {where} ORDER BY PriceDate DESC"
    ), params).fetchall()
    return [_row_to_dict(r) for r in rows]


# ── Contract-market comparison ─────────────────────────────────────────────────

@router.get("/contract-market-comparison")
def contract_market_comparison(
    business_id: int = Query(...),
    db: Session = Depends(get_db),
    _user: models.People = Depends(get_current_user),
):
    _ensure_tables(db)
    rows = db.execute(text("""
        SELECT s.Commodity,
               AVG(CAST(s.ContractPricePerKg AS FLOAT)) AS avg_contract_price,
               (SELECT TOP 1 mp.PricePerKg
                FROM ESCIMarketPrice mp
                WHERE mp.BusinessID=s.BusinessID AND mp.Commodity=s.Commodity
                ORDER BY mp.PriceDate DESC) AS latest_market_price,
               COUNT(*) AS shipment_count
        FROM ESCIShipment s
        WHERE s.BusinessID=:bid AND s.ContractPricePerKg IS NOT NULL
          AND s.CreatedAt >= DATEADD(day,-180,GETDATE())
        GROUP BY s.BusinessID, s.Commodity
    """), {"bid": business_id}).fetchall()
    result = []
    for r in rows:
        d = _row_to_dict(r)
        if d["avg_contract_price"] and d["latest_market_price"]:
            d["price_delta"] = round(
                float(d["avg_contract_price"]) - float(d["latest_market_price"]), 4
            )
        else:
            d["price_delta"] = None
        result.append(d)
    return result


# ── Analytics ─────────────────────────────────────────────────────────────────

@router.get("/analytics/quality-trends")
def quality_trends(
    business_id: int = Query(...),
    weeks: int = Query(12),
    db: Session = Depends(get_db),
    _user: models.People = Depends(get_current_user),
):
    _ensure_tables(db)
    rows = db.execute(text("""
        SELECT DATEPART(iso_week, TestDate) AS week_num,
               YEAR(TestDate) AS yr,
               AVG(CAST(Score AS FLOAT)) AS avg_score,
               COUNT(*) AS tests,
               SUM(CASE WHEN PassFail='pass' THEN 1 ELSE 0 END) AS passed
        FROM ESCIQualityTest
        WHERE BusinessID=:bid
          AND TestDate >= DATEADD(week,:neg_w,CAST(GETDATE() AS DATE))
        GROUP BY DATEPART(iso_week, TestDate), YEAR(TestDate)
        ORDER BY yr, week_num
    """), {"bid": business_id, "neg_w": -weeks}).fetchall()
    return [_row_to_dict(r) for r in rows]


@router.get("/analytics/exception-trends")
def exception_trends(
    business_id: int = Query(...),
    weeks: int = Query(12),
    db: Session = Depends(get_db),
    _user: models.People = Depends(get_current_user),
):
    _ensure_tables(db)
    rows = db.execute(text("""
        SELECT DATEPART(iso_week, CreatedAt) AS week_num,
               YEAR(CreatedAt) AS yr,
               COUNT(*) AS total,
               SUM(CASE WHEN Severity='critical' THEN 1 ELSE 0 END) AS critical,
               SUM(CASE WHEN Severity='high' THEN 1 ELSE 0 END) AS high_sev,
               SUM(CASE WHEN Status='resolved' THEN 1 ELSE 0 END) AS resolved
        FROM ESCIException
        WHERE BusinessID=:bid
          AND CreatedAt >= DATEADD(week,:neg_w,GETDATE())
        GROUP BY DATEPART(iso_week, CreatedAt), YEAR(CreatedAt)
        ORDER BY yr, week_num
    """), {"bid": business_id, "neg_w": -weeks}).fetchall()
    return [_row_to_dict(r) for r in rows]


@router.get("/analytics/margin-trends")
def margin_trends(
    business_id: int = Query(...),
    months: int = Query(6),
    db: Session = Depends(get_db),
    _user: models.People = Depends(get_current_user),
):
    _ensure_tables(db)
    rows = db.execute(text("""
        SELECT YEAR(PurchaseDate) AS yr,
               MONTH(PurchaseDate) AS mo,
               AVG(CAST(MarginPercent AS FLOAT)) AS avg_margin_pct,
               SUM(CAST(QuantityKg AS FLOAT)) AS total_kg
        FROM ESCIMarginRecord
        WHERE BusinessID=:bid
          AND PurchaseDate >= DATEADD(month,:neg_m,CAST(GETDATE() AS DATE))
        GROUP BY YEAR(PurchaseDate), MONTH(PurchaseDate)
        ORDER BY yr, mo
    """), {"bid": business_id, "neg_m": -months}).fetchall()
    return [_row_to_dict(r) for r in rows]


@router.get("/analytics/seasonal")
def seasonal_analytics(
    business_id: int = Query(...),
    db: Session = Depends(get_db),
    _user: models.People = Depends(get_current_user),
):
    _ensure_tables(db)
    demand = db.execute(text("""
        SELECT Commodity, MONTH(ForecastDate) AS mo,
               AVG(CAST(DemandKg AS FLOAT)) AS avg_demand
        FROM ESCIDemandForecast
        WHERE BusinessID=:bid
        GROUP BY Commodity, MONTH(ForecastDate)
        ORDER BY Commodity, mo
    """), {"bid": business_id}).fetchall()
    supply = db.execute(text("""
        SELECT Commodity, MONTH(ForecastDate) AS mo,
               AVG(CAST(ExpectedYieldKg AS FLOAT)) AS avg_yield
        FROM ESCIYieldForecast
        WHERE BusinessID=:bid
        GROUP BY Commodity, MONTH(ForecastDate)
        ORDER BY Commodity, mo
    """), {"bid": business_id}).fetchall()
    return {
        "demand": [_row_to_dict(r) for r in demand],
        "supply": [_row_to_dict(r) for r in supply],
    }


# ── Exceptions ────────────────────────────────────────────────────────────────

@router.get("/exceptions")
def list_exceptions(
    business_id: int = Query(...),
    status: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    limit: int = Query(50),
    db: Session = Depends(get_db),
    _user: models.People = Depends(get_current_user),
):
    _ensure_tables(db)
    where = "WHERE e.BusinessID=:bid"
    params: Dict[str, Any] = {"bid": business_id, "lim": limit}
    if status:
        where += " AND e.Status=:status"
        params["status"] = status
    if severity:
        where += " AND e.Severity=:sev"
        params["sev"] = severity
    rows = db.execute(text(f"""
        SELECT TOP (:lim) e.*, sup.SupplierName
        FROM ESCIException e
        LEFT JOIN ESCISupplier sup ON sup.SupplierID = e.SupplierID
        {where}
        ORDER BY
            CASE e.Severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2
                             WHEN 'medium' THEN 3 ELSE 4 END,
            e.CreatedAt DESC
    """), params).fetchall()
    return [_row_to_dict(r) for r in rows]


@router.get("/exceptions/{exception_id}")
def get_exception(
    exception_id: int,
    db: Session = Depends(get_db),
    _user: models.People = Depends(get_current_user),
):
    _ensure_tables(db)
    exc = db.execute(text(
        "SELECT * FROM ESCIException WHERE ExceptionID=:eid"
    ), {"eid": exception_id}).fetchone()
    if not exc:
        raise HTTPException(404, "Exception not found")
    notes = db.execute(text(
        "SELECT * FROM ESCIExceptionNote WHERE ExceptionID=:eid ORDER BY CreatedAt"
    ), {"eid": exception_id}).fetchall()
    return {**_row_to_dict(exc), "notes": [_row_to_dict(n) for n in notes]}


@router.patch("/exceptions/{exception_id}")
def patch_exception(
    exception_id: int,
    payload: ExceptionPatchIn,
    db: Session = Depends(get_db),
    _user: models.People = Depends(get_current_user),
):
    _ensure_tables(db)
    sets = ["UpdatedAt=GETDATE()"]
    params: Dict[str, Any] = {"eid": exception_id}
    if payload.status:
        sets.append("Status=:status")
        params["status"] = payload.status
        if payload.status == "resolved":
            sets.append("ResolvedAt=GETDATE()")
        if payload.status == "escalated":
            sets.append("EscalatedAt=GETDATE()")
    if payload.severity:
        sets.append("Severity=:sev")
        params["sev"] = payload.severity
    if payload.assigned_to:
        sets.append("AssignedTo=:asgn")
        params["asgn"] = payload.assigned_to
    db.execute(text(
        f"UPDATE ESCIException SET {', '.join(sets)} WHERE ExceptionID=:eid"
    ), params)
    db.commit()
    return {"ok": True}


@router.post("/exceptions/{exception_id}/notes", status_code=201)
def add_exception_note(
    exception_id: int,
    payload: ExceptionNoteIn,
    db: Session = Depends(get_db),
    _user: models.People = Depends(get_current_user),
):
    _ensure_tables(db)
    row = db.execute(text("""
        INSERT INTO ESCIExceptionNote (ExceptionID, Author, Body)
        OUTPUT INSERTED.NoteID
        VALUES (:eid, :author, :body)
    """), {"eid": exception_id, "author": payload.author, "body": payload.body}).fetchone()
    db.commit()
    return {"note_id": row[0]}


# ── SSE: live exceptions feed ─────────────────────────────────────────────────

@router.get("/stream/exceptions")
async def stream_exceptions(
    business_id: int = Query(...),
    since: Optional[str] = Query(None),
):
    """Server-Sent Events feed for new/updated exceptions. No auth required for SSE (token handled client-side via query param in JS)."""
    since_dt = datetime.datetime.fromisoformat(since) if since else (
        datetime.datetime.utcnow() - datetime.timedelta(minutes=5)
    )

    async def _generator() -> AsyncGenerator[str, None]:
        nonlocal since_dt
        from database import SessionLocal
        while True:
            try:
                with SessionLocal() as db:
                    rows = db.execute(text("""
                        SELECT TOP 20 ExceptionID, Title, Severity, Status, UpdatedAt
                        FROM ESCIException
                        WHERE BusinessID=:bid AND UpdatedAt > :since
                        ORDER BY UpdatedAt DESC
                    """), {"bid": business_id, "since": since_dt}).fetchall()
                    if rows:
                        since_dt = max(r.UpdatedAt for r in rows)
                        data = json.dumps([_row_to_dict(r) for r in rows])
                        yield f"data: {data}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
            await asyncio.sleep(5)

    return StreamingResponse(
        _generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Escalation rules ───────────────────────────────────────────────────────────

@router.get("/escalation-rules")
def list_escalation_rules(
    business_id: int = Query(...),
    db: Session = Depends(get_db),
    _user: models.People = Depends(get_current_user),
):
    _ensure_tables(db)
    rows = db.execute(text(
        "SELECT * FROM ESCIEscalationRule WHERE BusinessID=:bid ORDER BY CreatedAt DESC"
    ), {"bid": business_id}).fetchall()
    return [_row_to_dict(r) for r in rows]


@router.post("/escalation-rules", status_code=201)
def create_escalation_rule(
    payload: EscalationRuleIn,
    business_id: int = Query(...),
    db: Session = Depends(get_db),
    _user: models.People = Depends(get_current_user),
):
    _ensure_tables(db)
    row = db.execute(text("""
        INSERT INTO ESCIEscalationRule (BusinessID, RuleName, Condition, Action, IsActive)
        OUTPUT INSERTED.RuleID
        VALUES (:bid, :name, :cond, :act, :active)
    """), {
        "bid": business_id, "name": payload.rule_name,
        "cond": payload.condition, "act": payload.action,
        "active": 1 if payload.is_active else 0,
    }).fetchone()
    db.commit()
    return {"rule_id": row[0]}


@router.delete("/escalation-rules/{rule_id}")
def delete_escalation_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    _user: models.People = Depends(get_current_user),
):
    db.execute(text("DELETE FROM ESCIEscalationRule WHERE RuleID=:rid"), {"rid": rule_id})
    db.commit()
    return {"ok": True}


@router.post("/escalation-rules/run")
def run_escalation_rules(
    business_id: int = Query(...),
    db: Session = Depends(get_db),
    _user: models.People = Depends(get_current_user),
):
    """
    Evaluate active escalation rules for this business.
    Current rules auto-escalate critical open exceptions older than 24h.
    """
    _ensure_tables(db)
    # Auto-escalate: any critical exception open >24h gets escalated
    escalated = db.execute(text("""
        UPDATE ESCIException
        SET Status='escalated', EscalatedAt=GETDATE(), UpdatedAt=GETDATE()
        OUTPUT INSERTED.ExceptionID
        WHERE BusinessID=:bid
          AND Severity='critical'
          AND Status='open'
          AND CreatedAt < DATEADD(hour,-24,GETDATE())
    """), {"bid": business_id}).fetchall()
    db.commit()
    # Mark rules as run
    db.execute(text(
        "UPDATE ESCIEscalationRule SET LastRunAt=GETDATE() WHERE BusinessID=:bid AND IsActive=1"
    ), {"bid": business_id})
    db.commit()
    return {"escalated_ids": [r[0] for r in escalated]}


# ── Scorecard ─────────────────────────────────────────────────────────────────

@router.get("/scorecard")
def get_scorecard(
    business_id: int = Query(...),
    db: Session = Depends(get_db),
    _user: models.People = Depends(get_current_user),
):
    """
    Composite scorecard per supplier.
    Delivery score (40%): % shipments on time (ActualArrival <= ExpectedArrival)
    Quality score (40%):  avg quality score / 100
    Exception score (20%): 1 - (open exceptions / max(1, total exceptions))
    """
    _ensure_tables(db)
    suppliers = db.execute(text(
        "SELECT SupplierID, SupplierName, Category FROM ESCISupplier WHERE BusinessID=:bid AND IsActive=1"
    ), {"bid": business_id}).fetchall()

    results = []
    for sup in suppliers:
        sid = sup.SupplierID

        # Delivery
        ship = db.execute(text("""
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN ActualArrival IS NOT NULL AND ActualArrival <= ExpectedArrival THEN 1 ELSE 0 END) AS on_time
            FROM ESCIShipment
            WHERE BusinessID=:bid AND SupplierID=:sid
              AND Status='delivered'
        """), {"bid": business_id, "sid": sid}).fetchone()
        delivery_score = (
            (float(ship.on_time) / ship.total * 100) if ship.total and ship.total > 0 else None
        )

        # Quality
        qual = db.execute(text(
            "SELECT AVG(CAST(Score AS FLOAT)) AS avg_score FROM ESCIQualityTest "
            "WHERE BusinessID=:bid AND SupplierID=:sid"
        ), {"bid": business_id, "sid": sid}).fetchone()
        quality_score = float(qual.avg_score) if qual.avg_score else None

        # Exceptions
        exc = db.execute(text("""
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN Status NOT IN ('resolved') THEN 1 ELSE 0 END) AS open_count
            FROM ESCIException WHERE BusinessID=:bid AND SupplierID=:sid
        """), {"bid": business_id, "sid": sid}).fetchone()
        exc_score = None
        if exc.total and exc.total > 0:
            exc_score = max(0.0, 1.0 - float(exc.open_count) / exc.total) * 100

        # Composite
        parts = [v for v in [delivery_score, quality_score, exc_score] if v is not None]
        if parts:
            composite = (
                (delivery_score or 0) * 0.4 +
                (quality_score or 0) * 0.4 +
                (exc_score or 0) * 0.2
            )
        else:
            composite = None

        results.append({
            "supplier_id": sid,
            "supplier_name": sup.SupplierName,
            "category": sup.Category,
            "delivery_score": round(delivery_score, 1) if delivery_score is not None else None,
            "quality_score": round(quality_score, 1) if quality_score is not None else None,
            "exception_score": round(exc_score, 1) if exc_score is not None else None,
            "composite_score": round(composite, 1) if composite is not None else None,
            "shipments_total": ship.total or 0,
            "open_exceptions": exc.open_count or 0,
        })

    results.sort(key=lambda x: (x["composite_score"] or -1), reverse=True)
    return results


# ── Settings ──────────────────────────────────────────────────────────────────

@router.get("/settings")
def get_settings(
    business_id: int = Query(...),
    db: Session = Depends(get_db),
    _user: models.People = Depends(get_current_user),
):
    _ensure_tables(db)
    row = db.execute(text(
        "SELECT * FROM ESCISettings WHERE BusinessID=:bid"
    ), {"bid": business_id}).fetchone()
    if not row:
        return {
            "business_id": business_id,
            "currency": "USD",
            "alert_lead_days": 7,
            "quality_grade_threshold": "C",
            "margin_threshold_percent": 10.0,
            "email_notifications": True,
        }
    return _row_to_dict(row)


@router.put("/settings")
def update_settings(
    payload: SettingsIn,
    business_id: int = Query(...),
    db: Session = Depends(get_db),
    _user: models.People = Depends(get_current_user),
):
    _ensure_tables(db)
    existing = db.execute(text(
        "SELECT SettingsID FROM ESCISettings WHERE BusinessID=:bid"
    ), {"bid": business_id}).fetchone()
    if existing:
        sets: list[str] = ["UpdatedAt=GETDATE()"]
        params: Dict[str, Any] = {"bid": business_id}
        if payload.currency is not None:
            sets.append("Currency=:cur"); params["cur"] = payload.currency
        if payload.alert_lead_days is not None:
            sets.append("AlertLeadDays=:ald"); params["ald"] = payload.alert_lead_days
        if payload.quality_grade_threshold is not None:
            sets.append("QualityGradeThreshold=:qgt"); params["qgt"] = payload.quality_grade_threshold
        if payload.margin_threshold_percent is not None:
            sets.append("MarginThresholdPercent=:mtp"); params["mtp"] = payload.margin_threshold_percent
        if payload.email_notifications is not None:
            sets.append("EmailNotifications=:en"); params["en"] = 1 if payload.email_notifications else 0
        db.execute(text(f"UPDATE ESCISettings SET {', '.join(sets)} WHERE BusinessID=:bid"), params)
    else:
        db.execute(text("""
            INSERT INTO ESCISettings
                (BusinessID, Currency, AlertLeadDays, QualityGradeThreshold, MarginThresholdPercent, EmailNotifications)
            VALUES (:bid, :cur, :ald, :qgt, :mtp, :en)
        """), {
            "bid": business_id,
            "cur": payload.currency or "USD",
            "ald": payload.alert_lead_days or 7,
            "qgt": payload.quality_grade_threshold or "C",
            "mtp": payload.margin_threshold_percent or 10.0,
            "en": 1 if (payload.email_notifications is not False) else 0,
        })
    db.commit()
    return {"ok": True}


# ── Supplier Portal (public — no auth) ────────────────────────────────────────

@router.get("/supplier-portal/{token}")
def get_supplier_portal(
    token: str,
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    sup = db.execute(text(
        "SELECT * FROM ESCISupplier WHERE PortalToken=:tok AND IsActive=1"
    ), {"tok": token}).fetchone()
    if not sup:
        raise HTTPException(404, "Portal link not found or expired")

    shipments = db.execute(text("""
        SELECT TOP 20 ShipmentID, ShipmentRef, Commodity, QuantityKg,
               DepartureDate, ExpectedArrival, Status
        FROM ESCIShipment
        WHERE SupplierID=:sid ORDER BY CreatedAt DESC
    """), {"sid": sup.SupplierID}).fetchall()

    quality = db.execute(text(
        "SELECT TOP 10 * FROM ESCIQualityTest WHERE SupplierID=:sid ORDER BY TestDate DESC"
    ), {"sid": sup.SupplierID}).fetchall()

    return {
        "supplier": _row_to_dict(sup),
        "shipments": [_row_to_dict(r) for r in shipments],
        "quality_tests": [_row_to_dict(r) for r in quality],
    }


@router.post("/supplier-portal/{token}/quality", status_code=201)
def portal_submit_quality(
    token: str,
    payload: PortalQualityIn,
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    sup = db.execute(text(
        "SELECT SupplierID, BusinessID FROM ESCISupplier WHERE PortalToken=:tok AND IsActive=1"
    ), {"tok": token}).fetchone()
    if not sup:
        raise HTTPException(404, "Portal link not found")
    pf = None
    if payload.score is not None:
        pf = "pass" if payload.score >= 60 else "fail"
    row = db.execute(text("""
        INSERT INTO ESCIQualityTest
            (BusinessID, SupplierID, Commodity, TestDate, Grade, Score,
             MoisturePercent, PassFail, Notes)
        OUTPUT INSERTED.TestID
        VALUES (:bid, :sid, :com, CAST(GETDATE() AS DATE), :grade, :score,
                :moist, :pf, :notes)
    """), {
        "bid": sup.BusinessID, "sid": sup.SupplierID,
        "com": payload.commodity, "grade": payload.grade,
        "score": payload.score, "moist": payload.moisture_percent,
        "pf": pf, "notes": payload.notes,
    }).fetchone()
    db.commit()
    return {"test_id": row[0]}


@router.post("/supplier-portal/{token}/event", status_code=201)
def portal_submit_event(
    token: str,
    payload: PortalEventIn,
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    sup = db.execute(text(
        "SELECT SupplierID FROM ESCISupplier WHERE PortalToken=:tok AND IsActive=1"
    ), {"tok": token}).fetchone()
    if not sup:
        raise HTTPException(404, "Portal link not found")

    # Find shipment by ref if provided
    ship_id = None
    if payload.shipment_ref:
        ship = db.execute(text(
            "SELECT ShipmentID FROM ESCIShipment WHERE SupplierID=:sid AND ShipmentRef=:ref"
        ), {"sid": sup.SupplierID, "ref": payload.shipment_ref}).fetchone()
        if ship:
            ship_id = ship.ShipmentID

    row = db.execute(text("""
        INSERT INTO ESCIShipmentEvent (ShipmentID, EventType, Location, Notes)
        OUTPUT INSERTED.EventID
        VALUES (:sid, :etype, :loc, :notes)
    """), {
        "sid": ship_id, "etype": payload.event_type,
        "loc": payload.location, "notes": payload.notes,
    }).fetchone()
    db.commit()
    return {"event_id": row[0]}
