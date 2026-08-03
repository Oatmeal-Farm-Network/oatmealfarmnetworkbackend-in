"""
Enterprise Supply Chain Intelligence (ESCI) — core router.

12 ESCI_* tables: SupplierProfile, Contract, Shipment, ShipmentEvent,
QualityTest, YieldForecast, DemandForecast, MarginRecord, Exception,
ExceptionNote, MarketPrice, Settings.

All tables created lazily on first request via _ensure_tables().
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from database import blank_to_none
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, engine
from auth import get_current_user
import models
from typing import Optional, List
import datetime
import secrets
import logging

logger = logging.getLogger("supply_chain")


def _notify_business_team(db: Session, business_id: int, title: str,
                           body_text: str, link_path: str, type_: str) -> None:
    """Insert AppNotification rows + push for every active team member of a business."""
    try:
        from routers.notifications import _push_to_person
        members = db.execute(text(
            "SELECT PeopleID FROM BusinessAccess WHERE BusinessID=:bid AND Active=1"
        ), {"bid": business_id}).fetchall()
        for m in members:
            pid = int(m.PeopleID)
            db.execute(text("""
                INSERT INTO AppNotifications
                    (RecipientPeopleID, RecipientBusinessID, Type, Title, Body, LinkPath,
                     RelatedEntityType, RelatedEntityID)
                VALUES (:pid, :bid, :t, :ti, :b, :lp, 'supply_chain_exception', NULL)
            """), {"pid": pid, "bid": business_id, "t": type_,
                   "ti": title[:200], "b": (body_text or "")[:500], "lp": link_path})
            _push_to_person(pid, title, body_text, link_path, type_)
        db.commit()
    except Exception as e:
        logger.warning("[ESCI] push notification failed: %s", e)

router = APIRouter(prefix="/api/esci", tags=["supply_chain"])

_tables_ready = False


def _ensure_tables(db: Session):
    global _tables_ready
    if _tables_ready:
        return

    # ── Supplier Profiles ──────────────────────────────────────────────────────
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'ESCI_SupplierProfile')
        CREATE TABLE ESCI_SupplierProfile (
            SupplierID      INT IDENTITY PRIMARY KEY,
            BusinessID      INT           NOT NULL,
            SupplierName    NVARCHAR(200) NOT NULL,
            ContactName     NVARCHAR(200) NULL,
            ContactEmail    NVARCHAR(200) NULL,
            ContactPhone    NVARCHAR(50)  NULL,
            Country         NVARCHAR(100) NULL,
            Region          NVARCHAR(100) NULL,
            SupplierType    NVARCHAR(50)  NULL,
            CertifiedOrganic BIT          NOT NULL DEFAULT 0,
            CertifiedGAP    BIT           NOT NULL DEFAULT 0,
            GlobalGAP       BIT           NOT NULL DEFAULT 0,
            Notes           NVARCHAR(MAX) NULL,
            IsActive        BIT           NOT NULL DEFAULT 1,
            CreatedAt       DATETIME2     DEFAULT GETDATE()
        )
    """))

    # ── Contracts ─────────────────────────────────────────────────────────────
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'ESCI_Contract')
        CREATE TABLE ESCI_Contract (
            ContractID      INT IDENTITY PRIMARY KEY,
            BusinessID      INT           NOT NULL,
            SupplierID      INT           NULL,
            ProductName     NVARCHAR(200) NOT NULL,
            ProductCategory NVARCHAR(100) NULL,
            SKU             NVARCHAR(100) NULL,
            SeasonStart     DATE          NULL,
            SeasonEnd       DATE          NULL,
            CommittedVolume DECIMAL(12,2) NULL,
            Unit            NVARCHAR(50)  NULL,
            PriceFloor      DECIMAL(10,4) NULL,
            PriceCeiling    DECIMAL(10,4) NULL,
            AgreePrice      DECIMAL(10,4) NULL,
            Currency        NVARCHAR(10)  NOT NULL DEFAULT 'USD',
            Status          NVARCHAR(30)  NOT NULL DEFAULT 'active',
            Notes           NVARCHAR(MAX) NULL,
            CreatedAt       DATETIME2     DEFAULT GETDATE()
        )
    """))

    # ── Shipments ─────────────────────────────────────────────────────────────
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'ESCI_Shipment')
        CREATE TABLE ESCI_Shipment (
            ShipmentID      INT IDENTITY PRIMARY KEY,
            BusinessID      INT           NOT NULL,
            SupplierID      INT           NULL,
            ContractID      INT           NULL,
            ShipmentRef     NVARCHAR(100) NULL,
            ProductName     NVARCHAR(200) NOT NULL,
            ProductCategory NVARCHAR(100) NULL,
            OrderedQty      DECIMAL(12,2) NULL,
            ReceivedQty     DECIMAL(12,2) NULL,
            Unit            NVARCHAR(50)  NULL,
            Status          NVARCHAR(30)  NOT NULL DEFAULT 'pending',
            ExpectedDate    DATE          NULL,
            ReceivedDate    DATE          NULL,
            OriginLocation  NVARCHAR(200) NULL,
            DestLocation    NVARCHAR(200) NULL,
            CarrierName     NVARCHAR(200) NULL,
            TrackingNum     NVARCHAR(200) NULL,
            UnitCost        DECIMAL(10,4) NULL,
            TotalCost       DECIMAL(12,2) NULL,
            Currency        NVARCHAR(10)  NOT NULL DEFAULT 'USD',
            Notes           NVARCHAR(MAX) NULL,
            CreatedAt       DATETIME2     DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (
            SELECT 1 FROM sys.indexes
            WHERE object_id = OBJECT_ID('ESCI_Shipment') AND name = 'IX_ESCI_Shipment_Biz_Date'
        )
        CREATE INDEX IX_ESCI_Shipment_Biz_Date ON ESCI_Shipment (BusinessID, ExpectedDate DESC)
    """))

    # ── Shipment Events (status trail) ────────────────────────────────────────
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'ESCI_ShipmentEvent')
        CREATE TABLE ESCI_ShipmentEvent (
            EventID         INT IDENTITY PRIMARY KEY,
            ShipmentID      INT           NOT NULL,
            BusinessID      INT           NOT NULL,
            EventType       NVARCHAR(50)  NOT NULL,
            OccurredAt      DATETIME2     NOT NULL DEFAULT GETDATE(),
            Location        NVARCHAR(200) NULL,
            TempC           DECIMAL(5,2)  NULL,
            Notes           NVARCHAR(1000) NULL,
            RecordedBy      NVARCHAR(200) NULL
        )
    """))

    # ── Quality Tests ─────────────────────────────────────────────────────────
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'ESCI_QualityTest')
        CREATE TABLE ESCI_QualityTest (
            TestID          INT IDENTITY PRIMARY KEY,
            ShipmentID      INT           NOT NULL,
            BusinessID      INT           NOT NULL,
            TestedAt        DATETIME2     NOT NULL DEFAULT GETDATE(),
            Tester          NVARCHAR(200) NULL,
            Grade           NVARCHAR(20)  NULL,
            PassFail        NVARCHAR(10)  NOT NULL DEFAULT 'pass',
            DefectPct       DECIMAL(5,2)  NULL,
            BrixLevel       DECIMAL(5,2)  NULL,
            MoisturePct     DECIMAL(5,2)  NULL,
            PesticideResult NVARCHAR(20)  NULL,
            MicrobialResult NVARCHAR(20)  NULL,
            Notes           NVARCHAR(MAX) NULL
        )
    """))

    # ── Yield Forecasts ───────────────────────────────────────────────────────
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'ESCI_YieldForecast')
        CREATE TABLE ESCI_YieldForecast (
            ForecastID      INT IDENTITY PRIMARY KEY,
            BusinessID      INT           NOT NULL,
            SupplierID      INT           NULL,
            ProductName     NVARCHAR(200) NOT NULL,
            Season          NVARCHAR(50)  NULL,
            HarvestStart    DATE          NULL,
            HarvestEnd      DATE          NULL,
            ForecastQty     DECIMAL(12,2) NULL,
            Unit            NVARCHAR(50)  NULL,
            ConfidencePct   DECIMAL(5,2)  NULL,
            ActualQty       DECIMAL(12,2) NULL,
            Notes           NVARCHAR(MAX) NULL,
            CreatedAt       DATETIME2     DEFAULT GETDATE()
        )
    """))

    # ── Demand Forecasts ──────────────────────────────────────────────────────
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'ESCI_DemandForecast')
        CREATE TABLE ESCI_DemandForecast (
            DemandID        INT IDENTITY PRIMARY KEY,
            BusinessID      INT           NOT NULL,
            ProductName     NVARCHAR(200) NOT NULL,
            ProductCategory NVARCHAR(100) NULL,
            CustomerSegment NVARCHAR(100) NULL,
            PeriodType      NVARCHAR(20)  NOT NULL DEFAULT 'weekly',
            PeriodStart     DATE          NOT NULL,
            PeriodEnd       DATE          NULL,
            ForecastQty     DECIMAL(12,2) NOT NULL,
            Unit            NVARCHAR(50)  NULL,
            ActualQty       DECIMAL(12,2) NULL,
            ConfidencePct   DECIMAL(5,2)  NULL,
            Notes           NVARCHAR(MAX) NULL,
            CreatedAt       DATETIME2     DEFAULT GETDATE()
        )
    """))

    # ── Margin Records ────────────────────────────────────────────────────────
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'ESCI_MarginRecord')
        CREATE TABLE ESCI_MarginRecord (
            MarginID        INT IDENTITY PRIMARY KEY,
            BusinessID      INT           NOT NULL,
            ShipmentID      INT           NULL,
            ContractID      INT           NULL,
            ProductName     NVARCHAR(200) NOT NULL,
            ProductCategory NVARCHAR(100) NULL,
            PeriodStart     DATE          NOT NULL,
            PeriodEnd       DATE          NULL,
            Qty             DECIMAL(12,2) NULL,
            Unit            NVARCHAR(50)  NULL,
            LandedCostUnit  DECIMAL(10,4) NULL,
            SalePriceUnit   DECIMAL(10,4) NULL,
            MarginUnit      AS (SalePriceUnit - LandedCostUnit) PERSISTED,
            MarginPct       AS (
                CASE WHEN SalePriceUnit > 0
                     THEN ((SalePriceUnit - LandedCostUnit) / SalePriceUnit) * 100
                     ELSE NULL END
            ) PERSISTED,
            Currency        NVARCHAR(10)  NOT NULL DEFAULT 'USD',
            Notes           NVARCHAR(MAX) NULL,
            CreatedAt       DATETIME2     DEFAULT GETDATE()
        )
    """))

    # ── Exceptions ────────────────────────────────────────────────────────────
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'ESCI_Exception')
        CREATE TABLE ESCI_Exception (
            ExceptionID     INT IDENTITY PRIMARY KEY,
            BusinessID      INT           NOT NULL,
            ShipmentID      INT           NULL,
            SupplierID      INT           NULL,
            ExceptionType   NVARCHAR(50)  NOT NULL,
            Severity        NVARCHAR(20)  NOT NULL DEFAULT 'medium',
            Status          NVARCHAR(30)  NOT NULL DEFAULT 'open',
            Title           NVARCHAR(300) NOT NULL,
            Detail          NVARCHAR(MAX) NULL,
            DetectedAt      DATETIME2     NOT NULL DEFAULT GETDATE(),
            ResolvedAt      DATETIME2     NULL,
            AssignedTo      NVARCHAR(200) NULL,
            CreatedAt       DATETIME2     DEFAULT GETDATE()
        )
    """))
    db.execute(text("""
        IF NOT EXISTS (
            SELECT 1 FROM sys.indexes
            WHERE object_id = OBJECT_ID('ESCI_Exception') AND name = 'IX_ESCI_Exception_Biz_Status'
        )
        CREATE INDEX IX_ESCI_Exception_Biz_Status ON ESCI_Exception (BusinessID, Status, DetectedAt DESC)
    """))

    # ── Exception Notes ───────────────────────────────────────────────────────
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'ESCI_ExceptionNote')
        CREATE TABLE ESCI_ExceptionNote (
            NoteID          INT IDENTITY PRIMARY KEY,
            ExceptionID     INT           NOT NULL,
            BusinessID      INT           NOT NULL,
            AuthorName      NVARCHAR(200) NULL,
            NoteText        NVARCHAR(MAX) NOT NULL,
            CreatedAt       DATETIME2     DEFAULT GETDATE()
        )
    """))

    # ── Market Prices (commodity benchmarks) ──────────────────────────────────
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'ESCI_MarketPrice')
        CREATE TABLE ESCI_MarketPrice (
            PriceID         INT IDENTITY PRIMARY KEY,
            BusinessID      INT           NOT NULL,
            Commodity       NVARCHAR(200) NOT NULL,
            PriceDate       DATE          NOT NULL,
            PricePerUnit    DECIMAL(10,4) NOT NULL,
            Unit            NVARCHAR(50)  NULL,
            Market          NVARCHAR(200) NULL,
            Source          NVARCHAR(200) NULL,
            Notes           NVARCHAR(500) NULL,
            CreatedAt       DATETIME2     DEFAULT GETDATE()
        )
    """))

    # ── Per-business Settings ─────────────────────────────────────────────────
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'ESCI_Settings')
        CREATE TABLE ESCI_Settings (
            SettingsID      INT IDENTITY PRIMARY KEY,
            BusinessID      INT           NOT NULL UNIQUE,
            DefaultCurrency NVARCHAR(10)  NOT NULL DEFAULT 'USD',
            ShipmentAlertLeadDays INT     NOT NULL DEFAULT 3,
            QualityPassGrade     NVARCHAR(10) NOT NULL DEFAULT 'B',
            LowMarginThresholdPct DECIMAL(5,2) NOT NULL DEFAULT 10.0,
            ExceptionEmailEnabled BIT     NOT NULL DEFAULT 1,
            ExceptionEmailTo     NVARCHAR(500) NULL,
            UpdatedAt       DATETIME2     DEFAULT GETDATE()
        )
    """))

    # ── Escalation Rules ──────────────────────────────────────────────────────
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'ESCI_EscalationRule')
        CREATE TABLE ESCI_EscalationRule (
            RuleID          INT IDENTITY PRIMARY KEY,
            BusinessID      INT           NOT NULL,
            Severity        NVARCHAR(20)  NOT NULL DEFAULT 'critical',
            HoursUntilEscalate INT        NOT NULL DEFAULT 4,
            EscalateTo      NVARCHAR(200) NULL,
            IsActive        BIT           NOT NULL DEFAULT 1,
            CreatedAt       DATETIME2     DEFAULT GETDATE()
        )
    """))

    # ── Supplier Portal Tokens ────────────────────────────────────────────────
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'ESCI_SupplierPortalToken')
        CREATE TABLE ESCI_SupplierPortalToken (
            TokenID         INT IDENTITY PRIMARY KEY,
            BusinessID      INT           NOT NULL,
            SupplierID      INT           NOT NULL,
            Token           NVARCHAR(100) NOT NULL UNIQUE,
            Label           NVARCHAR(200) NULL,
            ExpiresAt       DATETIME2     NULL,
            IsActive        BIT           NOT NULL DEFAULT 1,
            CreatedAt       DATETIME2     DEFAULT GETDATE()
        )
    """))

    # ── Add escalation columns to ESCI_Exception if not present ──────────────
    db.execute(text("""
        IF NOT EXISTS (
            SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME='ESCI_Exception' AND COLUMN_NAME='EscalationLevel'
        )
        ALTER TABLE ESCI_Exception
            ADD EscalationLevel INT NOT NULL DEFAULT 0,
                EscalatedAt     DATETIME2 NULL
    """))

    db.commit()
    _tables_ready = True


def _ser(row):
    d = dict(row._mapping)
    for k, v in d.items():
        if hasattr(v, 'isoformat'):
            d[k] = v.isoformat()
        elif hasattr(v, '__float__'):
            try:
                d[k] = float(v)
            except Exception:
                pass
    return d


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/dashboard")
def dashboard(business_id: int = Query(...), db: Session = Depends(get_db)):
    """Summary KPIs for the SupplyChainHub landing page."""
    _ensure_tables(db)

    suppliers = db.execute(text(
        "SELECT COUNT(1) AS n FROM ESCI_SupplierProfile WHERE BusinessID = :bid AND IsActive = 1"
    ), {"bid": business_id}).fetchone()

    active_contracts = db.execute(text(
        "SELECT COUNT(1) AS n FROM ESCI_Contract WHERE BusinessID = :bid AND Status = 'active'"
    ), {"bid": business_id}).fetchone()

    shipments_in_transit = db.execute(text(
        "SELECT COUNT(1) AS n FROM ESCI_Shipment WHERE BusinessID = :bid AND Status = 'in_transit'"
    ), {"bid": business_id}).fetchone()

    open_exceptions = db.execute(text(
        "SELECT COUNT(1) AS total, "
        "SUM(CASE WHEN Severity='critical' THEN 1 ELSE 0 END) AS critical "
        "FROM ESCI_Exception WHERE BusinessID = :bid AND Status = 'open'"
    ), {"bid": business_id}).fetchone()

    # Quality pass rate last 30 days
    quality = db.execute(text("""
        SELECT COUNT(1) AS total,
               SUM(CASE WHEN PassFail='pass' THEN 1 ELSE 0 END) AS passed
          FROM ESCI_QualityTest
         WHERE BusinessID = :bid
           AND TestedAt >= DATEADD(day, -30, GETDATE())
    """), {"bid": business_id}).fetchone()

    # Average margin last 30 days
    margin = db.execute(text("""
        SELECT AVG(CAST(MarginPct AS FLOAT)) AS avg_margin_pct
          FROM ESCI_MarginRecord
         WHERE BusinessID = :bid
           AND PeriodStart >= DATEADD(day, -90, GETDATE())
    """), {"bid": business_id}).fetchone()

    # Shipments due this week (expected or overdue)
    due_soon = db.execute(text("""
        SELECT COUNT(1) AS n FROM ESCI_Shipment
         WHERE BusinessID = :bid
           AND Status IN ('pending','in_transit')
           AND ExpectedDate BETWEEN CAST(GETDATE() AS DATE)
                               AND DATEADD(day, 7, CAST(GETDATE() AS DATE))
    """), {"bid": business_id}).fetchone()

    overdue = db.execute(text("""
        SELECT COUNT(1) AS n FROM ESCI_Shipment
         WHERE BusinessID = :bid
           AND Status IN ('pending','in_transit')
           AND ExpectedDate < CAST(GETDATE() AS DATE)
    """), {"bid": business_id}).fetchone()

    quality_total = int(quality.total) if quality else 0
    quality_pass_rate = (
        round(int(quality.passed) / quality_total * 100, 1)
        if quality_total > 0 else None
    )

    return {
        "suppliers_active":        int(suppliers.n) if suppliers else 0,
        "contracts_active":        int(active_contracts.n) if active_contracts else 0,
        "shipments_in_transit":    int(shipments_in_transit.n) if shipments_in_transit else 0,
        "exceptions_open":         int(open_exceptions.total) if open_exceptions else 0,
        "exceptions_critical":     int(open_exceptions.critical) if open_exceptions else 0,
        "quality_tests_30d":       quality_total,
        "quality_pass_rate_pct":   quality_pass_rate,
        "avg_margin_pct_90d":      round(float(margin.avg_margin_pct), 2) if margin and margin.avg_margin_pct is not None else None,
        "shipments_due_7d":        int(due_soon.n) if due_soon else 0,
        "shipments_overdue":       int(overdue.n) if overdue else 0,
    }


# ── Suppliers ─────────────────────────────────────────────────────────────────

@router.get("/suppliers")
def list_suppliers(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    rows = db.execute(text("""
        SELECT sp.*,
               COUNT(DISTINCT c.ContractID)  AS contract_count,
               COUNT(DISTINCT s.ShipmentID)  AS shipment_count
          FROM ESCI_SupplierProfile sp
          LEFT JOIN ESCI_Contract c ON c.SupplierID = sp.SupplierID AND c.BusinessID = sp.BusinessID
          LEFT JOIN ESCI_Shipment  s ON s.SupplierID = sp.SupplierID AND s.BusinessID = sp.BusinessID
         WHERE sp.BusinessID = :bid
         GROUP BY sp.SupplierID, sp.BusinessID, sp.SupplierName, sp.ContactName,
                  sp.ContactEmail, sp.ContactPhone, sp.Country, sp.Region,
                  sp.SupplierType, sp.CertifiedOrganic, sp.CertifiedGAP,
                  sp.GlobalGAP, sp.Notes, sp.IsActive, sp.CreatedAt
         ORDER BY sp.SupplierName
    """), {"bid": business_id}).fetchall()
    return [_ser(r) for r in rows]


@router.post("/suppliers")
def create_supplier(body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure_tables(db)
    if not body.get("BusinessID") or not body.get("SupplierName"):
        raise HTTPException(400, "BusinessID and SupplierName are required")
    row = db.execute(text("""
        INSERT INTO ESCI_SupplierProfile
            (BusinessID, SupplierName, ContactName, ContactEmail, ContactPhone,
             Country, Region, SupplierType, CertifiedOrganic, CertifiedGAP, GlobalGAP, Notes)
        OUTPUT INSERTED.SupplierID
        VALUES (:bid, :name, :contact, :email, :phone,
                :country, :region, :stype, :organic, :gap, :ggap, :notes)
    """), {
        "bid":     body["BusinessID"],
        "name":    body["SupplierName"],
        "contact": body.get("ContactName"),
        "email":   body.get("ContactEmail"),
        "phone":   body.get("ContactPhone"),
        "country": body.get("Country"),
        "region":  body.get("Region"),
        "stype":   body.get("SupplierType"),
        "organic": 1 if body.get("CertifiedOrganic") else 0,
        "gap":     1 if body.get("CertifiedGAP") else 0,
        "ggap":    1 if body.get("GlobalGAP") else 0,
        "notes":   body.get("Notes"),
    }).fetchone()
    db.commit()
    return {"SupplierID": row[0]}


@router.put("/suppliers/{supplier_id}")
def update_supplier(supplier_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure_tables(db)
    db.execute(text("""
        UPDATE ESCI_SupplierProfile SET
            SupplierName    = COALESCE(:name,    SupplierName),
            ContactName     = COALESCE(:contact, ContactName),
            ContactEmail    = COALESCE(:email,   ContactEmail),
            ContactPhone    = COALESCE(:phone,   ContactPhone),
            Country         = COALESCE(:country, Country),
            Region          = COALESCE(:region,  Region),
            SupplierType    = COALESCE(:stype,   SupplierType),
            CertifiedOrganic= COALESCE(:organic, CertifiedOrganic),
            CertifiedGAP    = COALESCE(:gap,     CertifiedGAP),
            GlobalGAP       = COALESCE(:ggap,    GlobalGAP),
            IsActive        = COALESCE(:active,  IsActive),
            Notes           = COALESCE(:notes,   Notes)
        WHERE SupplierID = :sid
    """), {
        "sid":     supplier_id,
        "name":    body.get("SupplierName"),
        "contact": body.get("ContactName"),
        "email":   body.get("ContactEmail"),
        "phone":   body.get("ContactPhone"),
        "country": body.get("Country"),
        "region":  body.get("Region"),
        "stype":   body.get("SupplierType"),
        "organic": body.get("CertifiedOrganic"),
        "gap":     body.get("CertifiedGAP"),
        "ggap":    body.get("GlobalGAP"),
        "active":  body.get("IsActive"),
        "notes":   body.get("Notes"),
    })
    db.commit()
    return {"ok": True}


@router.delete("/suppliers/{supplier_id}")
def delete_supplier(supplier_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(text("UPDATE ESCI_SupplierProfile SET IsActive=0 WHERE SupplierID=:sid"), {"sid": supplier_id})
    db.commit()
    return {"ok": True}


# ── Contracts ─────────────────────────────────────────────────────────────────

@router.get("/contracts")
def list_contracts(
    business_id: int = Query(...),
    supplier_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    where = ["c.BusinessID = :bid"]
    params: dict = {"bid": business_id}
    if supplier_id:
        where.append("c.SupplierID = :sid"); params["sid"] = supplier_id
    if status:
        where.append("c.Status = :st"); params["st"] = status
    rows = db.execute(text(f"""
        SELECT c.*, sp.SupplierName
          FROM ESCI_Contract c
          LEFT JOIN ESCI_SupplierProfile sp ON sp.SupplierID = c.SupplierID
         WHERE {' AND '.join(where)}
         ORDER BY c.SeasonStart DESC, c.ProductName
    """), params).fetchall()
    return [_ser(r) for r in rows]


@router.post("/contracts")
def create_contract(body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure_tables(db)
    if not body.get("BusinessID") or not body.get("ProductName"):
        raise HTTPException(400, "BusinessID and ProductName are required")
    row = db.execute(text("""
        INSERT INTO ESCI_Contract
            (BusinessID, SupplierID, ProductName, ProductCategory, SKU,
             SeasonStart, SeasonEnd, CommittedVolume, Unit,
             PriceFloor, PriceCeiling, AgreePrice, Currency, Status, Notes)
        OUTPUT INSERTED.ContractID
        VALUES (:bid, :sid, :prod, :cat, :sku,
                :s_start, :s_end, :vol, :unit,
                :floor, :ceil, :agree, :cur, :status, :notes)
    """), {
        "bid":     body["BusinessID"],
        "sid":     body.get("SupplierID"),
        "prod":    body["ProductName"],
        "cat":     body.get("ProductCategory"),
        "sku":     body.get("SKU"),
        "s_start": body.get("SeasonStart"),
        "s_end":   body.get("SeasonEnd"),
        "vol":     body.get("CommittedVolume"),
        "unit":    body.get("Unit"),
        "floor":   body.get("PriceFloor"),
        "ceil":    body.get("PriceCeiling"),
        "agree":   body.get("AgreePrice"),
        "cur":     body.get("Currency", "USD"),
        "status":  body.get("Status", "active"),
        "notes":   body.get("Notes"),
    }).fetchone()
    db.commit()
    return {"ContractID": row[0]}


@router.put("/contracts/{contract_id}")
def update_contract(contract_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure_tables(db)
    db.execute(text("""
        UPDATE ESCI_Contract SET
            ProductName     = COALESCE(:prod,   ProductName),
            ProductCategory = COALESCE(:cat,    ProductCategory),
            CommittedVolume = COALESCE(:vol,    CommittedVolume),
            PriceFloor      = COALESCE(:floor,  PriceFloor),
            PriceCeiling    = COALESCE(:ceil,   PriceCeiling),
            AgreePrice      = COALESCE(:agree,  AgreePrice),
            Status          = COALESCE(:status, Status),
            Notes           = COALESCE(:notes,  Notes)
        WHERE ContractID = :cid
    """), {
        "cid":    contract_id,
        "prod":   body.get("ProductName"),
        "cat":    body.get("ProductCategory"),
        "vol":    body.get("CommittedVolume"),
        "floor":  body.get("PriceFloor"),
        "ceil":   body.get("PriceCeiling"),
        "agree":  body.get("AgreePrice"),
        "status": body.get("Status"),
        "notes":  body.get("Notes"),
    })
    db.commit()
    return {"ok": True}


@router.delete("/contracts/{contract_id}")
def delete_contract(contract_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(text("DELETE FROM ESCI_Contract WHERE ContractID=:cid"), {"cid": contract_id})
    db.commit()
    return {"ok": True}


# ── Shipments ─────────────────────────────────────────────────────────────────

@router.get("/shipments")
def list_shipments(
    business_id: int = Query(...),
    supplier_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    where = ["s.BusinessID = :bid"]
    params: dict = {"bid": business_id}
    if supplier_id:
        where.append("s.SupplierID = :sid"); params["sid"] = supplier_id
    if status:
        where.append("s.Status = :st"); params["st"] = status
    rows = db.execute(text(f"""
        SELECT TOP {limit}
               s.*,
               sp.SupplierName,
               qt.PassFail AS LatestQuality, qt.Grade AS LatestGrade
          FROM ESCI_Shipment s
          LEFT JOIN ESCI_SupplierProfile sp ON sp.SupplierID = s.SupplierID
          OUTER APPLY (
              SELECT TOP 1 PassFail, Grade
                FROM ESCI_QualityTest
               WHERE ShipmentID = s.ShipmentID
               ORDER BY TestedAt DESC
          ) qt
         WHERE {' AND '.join(where)}
         ORDER BY s.ExpectedDate DESC, s.CreatedAt DESC
    """), params).fetchall()
    return [_ser(r) for r in rows]


@router.post("/shipments")
def create_shipment(body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure_tables(db)
    if not body.get("BusinessID") or not body.get("ProductName"):
        raise HTTPException(400, "BusinessID and ProductName are required")
    row = db.execute(text("""
        INSERT INTO ESCI_Shipment
            (BusinessID, SupplierID, ContractID, ShipmentRef, ProductName, ProductCategory,
             OrderedQty, ReceivedQty, Unit, Status, ExpectedDate, ReceivedDate,
             OriginLocation, DestLocation, CarrierName, TrackingNum,
             UnitCost, TotalCost, Currency, Notes)
        OUTPUT INSERTED.ShipmentID
        VALUES (:bid, :sid, :cid, :ref, :prod, :cat,
                :oqty, :rqty, :unit, :status, :exp, :recv,
                :origin, :dest, :carrier, :tracking,
                :ucost, :tcost, :cur, :notes)
    """), {
        "bid":     body["BusinessID"],
        "sid":     body.get("SupplierID"),
        "cid":     body.get("ContractID"),
        "ref":     body.get("ShipmentRef"),
        "prod":    body["ProductName"],
        "cat":     body.get("ProductCategory"),
        "oqty":    body.get("OrderedQty"),
        "rqty":    body.get("ReceivedQty"),
        "unit":    body.get("Unit"),
        "status":  body.get("Status", "pending"),
        "exp":     body.get("ExpectedDate"),
        "recv":    body.get("ReceivedDate"),
        "origin":  body.get("OriginLocation"),
        "dest":    body.get("DestLocation"),
        "carrier": body.get("CarrierName"),
        "tracking":body.get("TrackingNum"),
        "ucost":   body.get("UnitCost"),
        "tcost":   body.get("TotalCost"),
        "cur":     body.get("Currency", "USD"),
        "notes":   body.get("Notes"),
    }).fetchone()
    db.commit()
    return {"ShipmentID": row[0]}


@router.get("/shipments/{shipment_id}")
def get_shipment(shipment_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    row = db.execute(text("""
        SELECT s.*, sp.SupplierName FROM ESCI_Shipment s
        LEFT JOIN ESCI_SupplierProfile sp ON sp.SupplierID = s.SupplierID
        WHERE s.ShipmentID = :sid
    """), {"sid": shipment_id}).fetchone()
    if not row:
        raise HTTPException(404, "Shipment not found")
    result = _ser(row)
    events = db.execute(text("""
        SELECT * FROM ESCI_ShipmentEvent WHERE ShipmentID=:sid ORDER BY OccurredAt ASC
    """), {"sid": shipment_id}).fetchall()
    result["events"] = [_ser(e) for e in events]
    tests = db.execute(text("""
        SELECT * FROM ESCI_QualityTest WHERE ShipmentID=:sid ORDER BY TestedAt DESC
    """), {"sid": shipment_id}).fetchall()
    result["quality_tests"] = [_ser(t) for t in tests]
    return result


@router.patch("/shipments/{shipment_id}")
def update_shipment(shipment_id: int, body: dict, db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(text("""
        UPDATE ESCI_Shipment SET
            Status       = COALESCE(:status,  Status),
            ReceivedQty  = COALESCE(:rqty,    ReceivedQty),
            ReceivedDate = COALESCE(:recv,    ReceivedDate),
            ExpectedDate = COALESCE(:exp,     ExpectedDate),
            TrackingNum  = COALESCE(:tracking,TrackingNum),
            UnitCost     = COALESCE(:ucost,   UnitCost),
            TotalCost    = COALESCE(:tcost,   TotalCost),
            Notes        = COALESCE(:notes,   Notes)
        WHERE ShipmentID = :sid
    """), {
        "sid":      shipment_id,
        "status":   body.get("Status"),
        "rqty":     body.get("ReceivedQty"),
        "recv":     body.get("ReceivedDate"),
        "exp":      body.get("ExpectedDate"),
        "tracking": body.get("TrackingNum"),
        "ucost":    body.get("UnitCost"),
        "tcost":    body.get("TotalCost"),
        "notes":    body.get("Notes"),
    })
    db.commit()
    return {"ok": True}


@router.delete("/shipments/{shipment_id}")
def delete_shipment(shipment_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(text("DELETE FROM ESCI_QualityTest    WHERE ShipmentID=:sid"), {"sid": shipment_id})
    db.execute(text("DELETE FROM ESCI_ShipmentEvent  WHERE ShipmentID=:sid"), {"sid": shipment_id})
    db.execute(text("DELETE FROM ESCI_Shipment       WHERE ShipmentID=:sid"), {"sid": shipment_id})
    db.commit()
    return {"ok": True}


# ── Shipment Events ───────────────────────────────────────────────────────────

@router.post("/shipments/{shipment_id}/events")
def add_shipment_event(shipment_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure_tables(db)
    if not body.get("BusinessID") or not body.get("EventType"):
        raise HTTPException(400, "BusinessID and EventType are required")
    row = db.execute(text("""
        INSERT INTO ESCI_ShipmentEvent
            (ShipmentID, BusinessID, EventType, OccurredAt, Location, TempC, Notes, RecordedBy)
        OUTPUT INSERTED.EventID
        VALUES (:sid, :bid, :etype, COALESCE(:at, GETDATE()), :loc, :temp, :notes, :by)
    """), {
        "sid":   shipment_id,
        "bid":   body["BusinessID"],
        "etype": body["EventType"],
        "at":    body.get("OccurredAt"),
        "loc":   body.get("Location"),
        "temp":  body.get("TempC"),
        "notes": body.get("Notes"),
        "by":    body.get("RecordedBy"),
    }).fetchone()
    db.commit()
    return {"EventID": row[0]}


# ── Quality Tests ─────────────────────────────────────────────────────────────

@router.get("/quality")
def list_quality_tests(
    business_id: int = Query(...),
    shipment_id: Optional[int] = Query(None),
    pass_fail: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    where = ["qt.BusinessID = :bid"]
    params: dict = {"bid": business_id}
    if shipment_id:
        where.append("qt.ShipmentID = :ship"); params["ship"] = shipment_id
    if pass_fail:
        where.append("qt.PassFail = :pf"); params["pf"] = pass_fail
    rows = db.execute(text(f"""
        SELECT TOP {limit} qt.*, s.ProductName, s.ShipmentRef
          FROM ESCI_QualityTest qt
          LEFT JOIN ESCI_Shipment s ON s.ShipmentID = qt.ShipmentID
         WHERE {' AND '.join(where)}
         ORDER BY qt.TestedAt DESC
    """), params).fetchall()
    return [_ser(r) for r in rows]


@router.post("/quality")
def add_quality_test(body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure_tables(db)
    if not body.get("ShipmentID") or not body.get("BusinessID"):
        raise HTTPException(400, "ShipmentID and BusinessID are required")
    row = db.execute(text("""
        INSERT INTO ESCI_QualityTest
            (ShipmentID, BusinessID, TestedAt, Tester, Grade, PassFail, DefectPct,
             BrixLevel, MoisturePct, PesticideResult, MicrobialResult, Notes)
        OUTPUT INSERTED.TestID
        VALUES (:sid, :bid, COALESCE(:at, GETDATE()), :tester, :grade, :pf, :defect,
                :brix, :moisture, :pest, :micro, :notes)
    """), {
        "sid":      body["ShipmentID"],
        "bid":      body["BusinessID"],
        "at":       body.get("TestedAt"),
        "tester":   body.get("Tester"),
        "grade":    body.get("Grade"),
        "pf":       body.get("PassFail", "pass"),
        "defect":   body.get("DefectPct"),
        "brix":     body.get("BrixLevel"),
        "moisture": body.get("MoisturePct"),
        "pest":     body.get("PesticideResult"),
        "micro":    body.get("MicrobialResult"),
        "notes":    body.get("Notes"),
    }).fetchone()
    db.commit()

    # Auto-create quality_fail exception if failed
    if body.get("PassFail", "pass").lower() == "fail":
        ship = db.execute(text(
            "SELECT BusinessID, SupplierID, ProductName FROM ESCI_Shipment WHERE ShipmentID=:sid"
        ), {"sid": body["ShipmentID"]}).fetchone()
        if ship:
            exc_title  = f"Quality test FAILED — {ship.ProductName}"
            exc_detail = f"Grade: {body.get('Grade', 'n/a')}, Defect%: {body.get('DefectPct', 'n/a')}"
            db.execute(text("""
                INSERT INTO ESCI_Exception
                    (BusinessID, ShipmentID, SupplierID, ExceptionType, Severity, Title, Detail)
                VALUES (:bid, :ship, :sup, 'quality_fail', 'high', :title, :detail)
            """), {
                "bid":    int(ship.BusinessID),
                "ship":   body["ShipmentID"],
                "sup":    ship.SupplierID,
                "title":  exc_title,
                "detail": exc_detail,
            })
            db.commit()
            link = f"/supply-chain/exceptions?BusinessID={int(ship.BusinessID)}"
            _notify_business_team(
                db, int(ship.BusinessID),
                f"[HIGH] {exc_title}", exc_detail, link, "supply_chain_exception",
            )

    return {"TestID": row[0]}


# ── Yield Forecasts ───────────────────────────────────────────────────────────

@router.get("/yield-forecasts")
def list_yield_forecasts(
    business_id: int = Query(...),
    supplier_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    where = ["yf.BusinessID = :bid"]
    params: dict = {"bid": business_id}
    if supplier_id:
        where.append("yf.SupplierID = :sid"); params["sid"] = supplier_id
    rows = db.execute(text(f"""
        SELECT yf.*, sp.SupplierName
          FROM ESCI_YieldForecast yf
          LEFT JOIN ESCI_SupplierProfile sp ON sp.SupplierID = yf.SupplierID
         WHERE {' AND '.join(where)}
         ORDER BY yf.HarvestStart DESC
    """), params).fetchall()
    return [_ser(r) for r in rows]


@router.post("/yield-forecasts")
def create_yield_forecast(body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure_tables(db)
    if not body.get("BusinessID") or not body.get("ProductName"):
        raise HTTPException(400, "BusinessID and ProductName are required")
    row = db.execute(text("""
        INSERT INTO ESCI_YieldForecast
            (BusinessID, SupplierID, ProductName, Season, HarvestStart, HarvestEnd,
             ForecastQty, Unit, ConfidencePct, ActualQty, Notes)
        OUTPUT INSERTED.ForecastID
        VALUES (:bid, :sid, :prod, :season, :hs, :he,
                :fqty, :unit, :conf, :aqty, :notes)
    """), {
        "bid":    body["BusinessID"],
        "sid":    body.get("SupplierID"),
        "prod":   body["ProductName"],
        "season": body.get("Season"),
        "hs":     body.get("HarvestStart"),
        "he":     body.get("HarvestEnd"),
        "fqty":   body.get("ForecastQty"),
        "unit":   body.get("Unit"),
        "conf":   body.get("ConfidencePct"),
        "aqty":   body.get("ActualQty"),
        "notes":  body.get("Notes"),
    }).fetchone()
    db.commit()
    return {"ForecastID": row[0]}


@router.patch("/yield-forecasts/{forecast_id}")
def update_yield_forecast(forecast_id: int, body: dict, db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(text("""
        UPDATE ESCI_YieldForecast SET
            ForecastQty   = COALESCE(:fqty,  ForecastQty),
            ActualQty     = COALESCE(:aqty,  ActualQty),
            ConfidencePct = COALESCE(:conf,  ConfidencePct),
            Notes         = COALESCE(:notes, Notes)
        WHERE ForecastID = :fid
    """), {
        "fid":   forecast_id,
        "fqty":  body.get("ForecastQty"),
        "aqty":  body.get("ActualQty"),
        "conf":  body.get("ConfidencePct"),
        "notes": body.get("Notes"),
    })
    db.commit()
    return {"ok": True}


@router.delete("/yield-forecasts/{forecast_id}")
def delete_yield_forecast(forecast_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(text("DELETE FROM ESCI_YieldForecast WHERE ForecastID=:fid"), {"fid": forecast_id})
    db.commit()
    return {"ok": True}


# ── Demand Forecasts ──────────────────────────────────────────────────────────

@router.get("/demand-forecasts")
def list_demand_forecasts(
    business_id: int = Query(...),
    product: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    where = ["BusinessID = :bid"]
    params: dict = {"bid": business_id}
    if product:
        where.append("ProductName LIKE :prod"); params["prod"] = f"%{product}%"
    rows = db.execute(text(f"""
        SELECT * FROM ESCI_DemandForecast
         WHERE {' AND '.join(where)}
         ORDER BY PeriodStart DESC
    """), params).fetchall()
    return [_ser(r) for r in rows]


@router.post("/demand-forecasts")
def create_demand_forecast(body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure_tables(db)
    if not body.get("BusinessID") or not body.get("ProductName") or not body.get("PeriodStart"):
        raise HTTPException(400, "BusinessID, ProductName, and PeriodStart are required")
    row = db.execute(text("""
        INSERT INTO ESCI_DemandForecast
            (BusinessID, ProductName, ProductCategory, CustomerSegment, PeriodType,
             PeriodStart, PeriodEnd, ForecastQty, Unit, ActualQty, ConfidencePct, Notes)
        OUTPUT INSERTED.DemandID
        VALUES (:bid, :prod, :cat, :seg, :ptype,
                :ps, :pe, :fqty, :unit, :aqty, :conf, :notes)
    """), {
        "bid":   body["BusinessID"],
        "prod":  body["ProductName"],
        "cat":   body.get("ProductCategory"),
        "seg":   body.get("CustomerSegment"),
        "ptype": body.get("PeriodType", "weekly"),
        "ps":    body["PeriodStart"],
        "pe":    body.get("PeriodEnd"),
        "fqty":  body["ForecastQty"],
        "unit":  body.get("Unit"),
        "aqty":  body.get("ActualQty"),
        "conf":  body.get("ConfidencePct"),
        "notes": body.get("Notes"),
    }).fetchone()
    db.commit()
    return {"DemandID": row[0]}


@router.patch("/demand-forecasts/{demand_id}")
def update_demand_forecast(demand_id: int, body: dict, db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(text("""
        UPDATE ESCI_DemandForecast SET
            ForecastQty = COALESCE(:fqty,  ForecastQty),
            ActualQty   = COALESCE(:aqty,  ActualQty),
            Notes       = COALESCE(:notes, Notes)
        WHERE DemandID = :did
    """), {
        "did":   demand_id,
        "fqty":  body.get("ForecastQty"),
        "aqty":  body.get("ActualQty"),
        "notes": body.get("Notes"),
    })
    db.commit()
    return {"ok": True}


@router.delete("/demand-forecasts/{demand_id}")
def delete_demand_forecast(demand_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(text("DELETE FROM ESCI_DemandForecast WHERE DemandID=:did"), {"did": demand_id})
    db.commit()
    return {"ok": True}


# ── Margin Records ────────────────────────────────────────────────────────────

@router.get("/margins")
def list_margins(
    business_id: int = Query(...),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    rows = db.execute(text(f"""
        SELECT TOP {limit} * FROM ESCI_MarginRecord
         WHERE BusinessID = :bid
         ORDER BY PeriodStart DESC
    """), {"bid": business_id}).fetchall()
    return [_ser(r) for r in rows]


@router.get("/margins/summary")
def margin_summary(
    business_id: int = Query(...),
    days: int = Query(90, ge=7, le=365),
    db: Session = Depends(get_db),
):
    """Aggregate margin by product category for a time window."""
    _ensure_tables(db)
    rows = db.execute(text("""
        SELECT ProductCategory,
               COUNT(1) AS record_count,
               AVG(CAST(MarginPct AS FLOAT)) AS avg_margin_pct,
               MIN(CAST(MarginPct AS FLOAT)) AS min_margin_pct,
               MAX(CAST(MarginPct AS FLOAT)) AS max_margin_pct,
               SUM(Qty * LandedCostUnit) AS total_landed_cost,
               SUM(Qty * SalePriceUnit)  AS total_revenue
          FROM ESCI_MarginRecord
         WHERE BusinessID = :bid
           AND PeriodStart >= DATEADD(day, -:d, GETDATE())
         GROUP BY ProductCategory
         ORDER BY avg_margin_pct ASC
    """), {"bid": business_id, "d": days}).fetchall()
    return [_ser(r) for r in rows]


@router.post("/margins")
def create_margin_record(body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure_tables(db)
    if not body.get("BusinessID") or not body.get("ProductName") or not body.get("PeriodStart"):
        raise HTTPException(400, "BusinessID, ProductName, and PeriodStart are required")
    row = db.execute(text("""
        INSERT INTO ESCI_MarginRecord
            (BusinessID, ShipmentID, ContractID, ProductName, ProductCategory,
             PeriodStart, PeriodEnd, Qty, Unit, LandedCostUnit, SalePriceUnit, Currency, Notes)
        OUTPUT INSERTED.MarginID
        VALUES (:bid, :ship, :con, :prod, :cat,
                :ps, :pe, :qty, :unit, :lcost, :sprice, :cur, :notes)
    """), {
        "bid":    body["BusinessID"],
        "ship":   body.get("ShipmentID"),
        "con":    body.get("ContractID"),
        "prod":   body["ProductName"],
        "cat":    body.get("ProductCategory"),
        "ps":     body["PeriodStart"],
        "pe":     body.get("PeriodEnd"),
        "qty":    body.get("Qty"),
        "unit":   body.get("Unit"),
        "lcost":  body.get("LandedCostUnit"),
        "sprice": body.get("SalePriceUnit"),
        "cur":    body.get("Currency", "USD"),
        "notes":  body.get("Notes"),
    }).fetchone()
    db.commit()
    return {"MarginID": row[0]}


@router.delete("/margins/{margin_id}")
def delete_margin_record(margin_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(text("DELETE FROM ESCI_MarginRecord WHERE MarginID=:mid"), {"mid": margin_id})
    db.commit()
    return {"ok": True}


# ── Exceptions ────────────────────────────────────────────────────────────────

@router.get("/exceptions")
def list_exceptions(
    business_id: int = Query(...),
    status: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    exception_type: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    where = ["e.BusinessID = :bid"]
    params: dict = {"bid": business_id}
    if status:
        where.append("e.Status = :st"); params["st"] = status
    if severity:
        where.append("e.Severity = :sev"); params["sev"] = severity
    if exception_type:
        where.append("e.ExceptionType = :etype"); params["etype"] = exception_type
    rows = db.execute(text(f"""
        SELECT TOP {limit}
               e.*,
               sp.SupplierName,
               s.ProductName AS ShipmentProduct,
               s.ShipmentRef
          FROM ESCI_Exception e
          LEFT JOIN ESCI_SupplierProfile sp ON sp.SupplierID = e.SupplierID
          LEFT JOIN ESCI_Shipment s ON s.ShipmentID = e.ShipmentID
         WHERE {' AND '.join(where)}
         ORDER BY
           CASE Severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END,
           e.DetectedAt DESC
    """), params).fetchall()
    return [_ser(r) for r in rows]


@router.post("/exceptions")
def create_exception(body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure_tables(db)
    if not body.get("BusinessID") or not body.get("Title") or not body.get("ExceptionType"):
        raise HTTPException(400, "BusinessID, Title, and ExceptionType are required")
    sev = body.get("Severity", "medium")
    row = db.execute(text("""
        INSERT INTO ESCI_Exception
            (BusinessID, ShipmentID, SupplierID, ExceptionType, Severity, Status,
             Title, Detail, DetectedAt, AssignedTo)
        OUTPUT INSERTED.ExceptionID
        VALUES (:bid, :ship, :sup, :etype, :sev, :status,
                :title, :detail, COALESCE(:at, GETDATE()), :assigned)
    """), {
        "bid":      body["BusinessID"],
        "ship":     body.get("ShipmentID"),
        "sup":      body.get("SupplierID"),
        "etype":    body["ExceptionType"],
        "sev":      sev,
        "status":   body.get("Status", "open"),
        "title":    body["Title"],
        "detail":   body.get("Detail"),
        "at":       body.get("DetectedAt"),
        "assigned": body.get("AssignedTo"),
    }).fetchone()
    db.commit()
    exc_id = row[0]

    # Push notification for critical / high exceptions
    if sev in ("critical", "high"):
        link = f"/supply-chain/exceptions?BusinessID={body['BusinessID']}"
        _notify_business_team(
            db, body["BusinessID"],
            f"[{sev.upper()}] {body['Title']}",
            body.get("Detail") or "",
            link, "supply_chain_exception",
        )

    return {"ExceptionID": exc_id}


@router.get("/exceptions/{exception_id}")
def get_exception(exception_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    row = db.execute(text("""
        SELECT e.*, sp.SupplierName, s.ProductName AS ShipmentProduct
          FROM ESCI_Exception e
          LEFT JOIN ESCI_SupplierProfile sp ON sp.SupplierID = e.SupplierID
          LEFT JOIN ESCI_Shipment s ON s.ShipmentID = e.ShipmentID
         WHERE e.ExceptionID = :eid
    """), {"eid": exception_id}).fetchone()
    if not row:
        raise HTTPException(404, "Exception not found")
    result = _ser(row)
    notes = db.execute(text("""
        SELECT * FROM ESCI_ExceptionNote WHERE ExceptionID=:eid ORDER BY CreatedAt ASC
    """), {"eid": exception_id}).fetchall()
    result["notes"] = [_ser(n) for n in notes]
    return result


@router.patch("/exceptions/{exception_id}")
def update_exception(exception_id: int, body: dict, db: Session = Depends(get_db)):
    _ensure_tables(db)
    resolved_at = None
    if body.get("Status") == "resolved":
        resolved_at = datetime.datetime.utcnow().isoformat()
    db.execute(text("""
        UPDATE ESCI_Exception SET
            Status     = COALESCE(:status,   Status),
            AssignedTo = COALESCE(:assigned, AssignedTo),
            ResolvedAt = COALESCE(:resolved, ResolvedAt),
            Detail     = COALESCE(:detail,   Detail)
        WHERE ExceptionID = :eid
    """), {
        "eid":      exception_id,
        "status":   body.get("Status"),
        "assigned": body.get("AssignedTo"),
        "resolved": resolved_at,
        "detail":   body.get("Detail"),
    })
    db.commit()
    return {"ok": True}


@router.post("/exceptions/{exception_id}/notes")
def add_exception_note(exception_id: int, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure_tables(db)
    if not body.get("BusinessID") or not body.get("NoteText"):
        raise HTTPException(400, "BusinessID and NoteText are required")
    row = db.execute(text("""
        INSERT INTO ESCI_ExceptionNote (ExceptionID, BusinessID, AuthorName, NoteText)
        OUTPUT INSERTED.NoteID
        VALUES (:eid, :bid, :author, :text)
    """), {
        "eid":    exception_id,
        "bid":    body["BusinessID"],
        "author": body.get("AuthorName"),
        "text":   body["NoteText"],
    }).fetchone()
    db.commit()
    return {"NoteID": row[0]}


# ── Market Prices ─────────────────────────────────────────────────────────────

@router.get("/market-prices")
def list_market_prices(
    business_id: int = Query(...),
    commodity: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    where = ["BusinessID = :bid"]
    params: dict = {"bid": business_id}
    if commodity:
        where.append("Commodity LIKE :com"); params["com"] = f"%{commodity}%"
    rows = db.execute(text(f"""
        SELECT TOP {limit} * FROM ESCI_MarketPrice
         WHERE {' AND '.join(where)}
         ORDER BY PriceDate DESC, Commodity
    """), params).fetchall()
    return [_ser(r) for r in rows]


@router.post("/market-prices")
def add_market_price(body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure_tables(db)
    if not body.get("BusinessID") or not body.get("Commodity") or not body.get("PriceDate"):
        raise HTTPException(400, "BusinessID, Commodity, and PriceDate are required")
    row = db.execute(text("""
        INSERT INTO ESCI_MarketPrice
            (BusinessID, Commodity, PriceDate, PricePerUnit, Unit, Market, Source, Notes)
        OUTPUT INSERTED.PriceID
        VALUES (:bid, :com, :date, :price, :unit, :market, :source, :notes)
    """), {
        "bid":    body["BusinessID"],
        "com":    body["Commodity"],
        "date":   body["PriceDate"],
        "price":  body["PricePerUnit"],
        "unit":   body.get("Unit"),
        "market": body.get("Market"),
        "source": body.get("Source"),
        "notes":  body.get("Notes"),
    }).fetchone()
    db.commit()
    return {"PriceID": row[0]}


@router.delete("/market-prices/{price_id}")
def delete_market_price(price_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(text("DELETE FROM ESCI_MarketPrice WHERE PriceID=:pid"), {"pid": price_id})
    db.commit()
    return {"ok": True}


# ── Settings ──────────────────────────────────────────────────────────────────

@router.get("/settings")
def get_settings(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    row = db.execute(text(
        "SELECT * FROM ESCI_Settings WHERE BusinessID=:bid"
    ), {"bid": business_id}).fetchone()
    if not row:
        return {
            "BusinessID":              business_id,
            "DefaultCurrency":         "USD",
            "ShipmentAlertLeadDays":   3,
            "QualityPassGrade":        "B",
            "LowMarginThresholdPct":   10.0,
            "ExceptionEmailEnabled":   True,
            "ExceptionEmailTo":        None,
        }
    return _ser(row)


@router.put("/settings")
def upsert_settings(body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure_tables(db)
    if not body.get("BusinessID"):
        raise HTTPException(400, "BusinessID is required")
    existing = db.execute(text(
        "SELECT 1 FROM ESCI_Settings WHERE BusinessID=:bid"
    ), {"bid": body["BusinessID"]}).fetchone()
    if existing:
        db.execute(text("""
            UPDATE ESCI_Settings SET
                DefaultCurrency         = COALESCE(:cur,    DefaultCurrency),
                ShipmentAlertLeadDays   = COALESCE(:lead,   ShipmentAlertLeadDays),
                QualityPassGrade        = COALESCE(:grade,  QualityPassGrade),
                LowMarginThresholdPct   = COALESCE(:margin, LowMarginThresholdPct),
                ExceptionEmailEnabled   = COALESCE(:email,  ExceptionEmailEnabled),
                ExceptionEmailTo        = COALESCE(:emailto,ExceptionEmailTo),
                UpdatedAt               = GETDATE()
            WHERE BusinessID = :bid
        """), {
            "bid":     body["BusinessID"],
            "cur":     body.get("DefaultCurrency"),
            "lead":    body.get("ShipmentAlertLeadDays"),
            "grade":   body.get("QualityPassGrade"),
            "margin":  body.get("LowMarginThresholdPct"),
            "email":   body.get("ExceptionEmailEnabled"),
            "emailto": body.get("ExceptionEmailTo"),
        })
    else:
        db.execute(text("""
            INSERT INTO ESCI_Settings
                (BusinessID, DefaultCurrency, ShipmentAlertLeadDays, QualityPassGrade,
                 LowMarginThresholdPct, ExceptionEmailEnabled, ExceptionEmailTo)
            VALUES (:bid, :cur, :lead, :grade, :margin, :email, :emailto)
        """), {
            "bid":     body["BusinessID"],
            "cur":     body.get("DefaultCurrency", "USD"),
            "lead":    body.get("ShipmentAlertLeadDays", 3),
            "grade":   body.get("QualityPassGrade", "B"),
            "margin":  body.get("LowMarginThresholdPct", 10.0),
            "email":   1 if body.get("ExceptionEmailEnabled", True) else 0,
            "emailto": body.get("ExceptionEmailTo"),
        })
    db.commit()
    return {"ok": True}


# ── Visibility summary (Farm → Shelf) ─────────────────────────────────────────

@router.get("/visibility")
def visibility_summary(
    business_id: int = Query(...),
    days: int = Query(90, ge=7, le=365),
    db: Session = Depends(get_db),
):
    """End-to-end supply chain visibility snapshot."""
    _ensure_tables(db)

    by_status = db.execute(text("""
        SELECT Status, COUNT(1) AS n,
               ISNULL(SUM(TotalCost), 0) AS total_value
          FROM ESCI_Shipment
         WHERE BusinessID = :bid
           AND CreatedAt >= DATEADD(day, -:d, GETDATE())
         GROUP BY Status
    """), {"bid": business_id, "d": days}).fetchall()

    by_supplier = db.execute(text("""
        SELECT sp.SupplierName,
               COUNT(DISTINCT s.ShipmentID) AS shipments,
               SUM(CASE WHEN s.Status='received' THEN 1 ELSE 0 END) AS received,
               SUM(CASE WHEN s.Status='rejected' THEN 1 ELSE 0 END) AS rejected,
               ISNULL(AVG(DATEDIFF(day, s.ExpectedDate, s.ReceivedDate)), 0) AS avg_delay_days
          FROM ESCI_Shipment s
          LEFT JOIN ESCI_SupplierProfile sp ON sp.SupplierID = s.SupplierID
         WHERE s.BusinessID = :bid
           AND s.CreatedAt >= DATEADD(day, -:d, GETDATE())
         GROUP BY sp.SupplierName
         ORDER BY shipments DESC
    """), {"bid": business_id, "d": days}).fetchall()

    on_time = db.execute(text("""
        SELECT COUNT(1) AS total,
               SUM(CASE WHEN ReceivedDate <= ExpectedDate THEN 1 ELSE 0 END) AS on_time
          FROM ESCI_Shipment
         WHERE BusinessID = :bid
           AND Status = 'received'
           AND ReceivedDate IS NOT NULL
           AND ExpectedDate IS NOT NULL
           AND CreatedAt >= DATEADD(day, -:d, GETDATE())
    """), {"bid": business_id, "d": days}).fetchone()

    on_time_pct = None
    if on_time and int(on_time.total) > 0:
        on_time_pct = round(int(on_time.on_time) / int(on_time.total) * 100, 1)

    return {
        "period_days":       days,
        "by_status":         [_ser(r) for r in by_status],
        "by_supplier":       [_ser(r) for r in by_supplier],
        "on_time_pct":       on_time_pct,
        "on_time_shipments": int(on_time.on_time) if on_time else 0,
        "total_received":    int(on_time.total) if on_time else 0,
    }


# ── Analytics: trend endpoints ────────────────────────────────────────────────

@router.get("/analytics/quality-trends")
def quality_trends(
    business_id: int = Query(...),
    weeks: int = Query(12, ge=4, le=52),
    db: Session = Depends(get_db),
):
    """Weekly quality pass rate for the last N weeks."""
    _ensure_tables(db)
    rows = db.execute(text("""
        SELECT DATEPART(year, TestedAt)  AS yr,
               DATEPART(week, TestedAt)  AS wk,
               CAST(MIN(DATEADD(day,
                   -(DATEPART(weekday, TestedAt)-2),
                   CAST(TestedAt AS DATE))) AS NVARCHAR(20)) AS week_start,
               COUNT(1) AS total,
               SUM(CASE WHEN PassFail='pass' THEN 1 ELSE 0 END) AS passed,
               AVG(CAST(DefectPct AS FLOAT)) AS avg_defect_pct
          FROM ESCI_QualityTest
         WHERE BusinessID = :bid
           AND TestedAt >= DATEADD(week, -:w, GETDATE())
         GROUP BY DATEPART(year, TestedAt), DATEPART(week, TestedAt)
         ORDER BY yr ASC, wk ASC
    """), {"bid": business_id, "w": weeks}).fetchall()
    result = []
    for r in rows:
        total = int(r.total)
        result.append({
            "week_start":    r.week_start,
            "total":         total,
            "passed":        int(r.passed),
            "pass_rate_pct": round(int(r.passed) / total * 100, 1) if total else None,
            "avg_defect_pct": round(float(r.avg_defect_pct), 2) if r.avg_defect_pct else None,
        })
    return result


@router.get("/analytics/margin-trends")
def margin_trends(
    business_id: int = Query(...),
    months: int = Query(6, ge=2, le=24),
    db: Session = Depends(get_db),
):
    """Monthly average margin % for the last N months."""
    _ensure_tables(db)
    rows = db.execute(text("""
        SELECT DATEPART(year, PeriodStart)  AS yr,
               DATEPART(month, PeriodStart) AS mo,
               CAST(DATEFROMPARTS(DATEPART(year, PeriodStart),
                                  DATEPART(month, PeriodStart), 1) AS NVARCHAR(20)) AS month_start,
               COUNT(1) AS records,
               AVG(CAST(MarginPct AS FLOAT))  AS avg_margin_pct,
               MIN(CAST(MarginPct AS FLOAT))  AS min_margin_pct,
               SUM(Qty * LandedCostUnit)      AS total_cost,
               SUM(Qty * SalePriceUnit)       AS total_revenue
          FROM ESCI_MarginRecord
         WHERE BusinessID = :bid
           AND PeriodStart >= DATEADD(month, -:m, GETDATE())
           AND MarginPct IS NOT NULL
         GROUP BY DATEPART(year, PeriodStart), DATEPART(month, PeriodStart)
         ORDER BY yr ASC, mo ASC
    """), {"bid": business_id, "m": months}).fetchall()
    return [_ser(r) for r in rows]


@router.get("/analytics/exception-trends")
def exception_trends(
    business_id: int = Query(...),
    weeks: int = Query(8, ge=2, le=26),
    db: Session = Depends(get_db),
):
    """Weekly exception counts broken down by severity."""
    _ensure_tables(db)
    rows = db.execute(text("""
        SELECT DATEPART(year, DetectedAt)  AS yr,
               DATEPART(week, DetectedAt)  AS wk,
               CAST(MIN(DATEADD(day,
                   -(DATEPART(weekday, DetectedAt)-2),
                   CAST(DetectedAt AS DATE))) AS NVARCHAR(20)) AS week_start,
               COUNT(1) AS total,
               SUM(CASE WHEN Severity='critical' THEN 1 ELSE 0 END) AS critical,
               SUM(CASE WHEN Severity='high'     THEN 1 ELSE 0 END) AS high,
               SUM(CASE WHEN Severity='medium'   THEN 1 ELSE 0 END) AS medium,
               SUM(CASE WHEN Severity='low'      THEN 1 ELSE 0 END) AS low,
               SUM(CASE WHEN Status='resolved'   THEN 1 ELSE 0 END) AS resolved
          FROM ESCI_Exception
         WHERE BusinessID = :bid
           AND DetectedAt >= DATEADD(week, -:w, GETDATE())
         GROUP BY DATEPART(year, DetectedAt), DATEPART(week, DetectedAt)
         ORDER BY yr ASC, wk ASC
    """), {"bid": business_id, "w": weeks}).fetchall()
    return [_ser(r) for r in rows]


@router.get("/analytics/seasonal")
def seasonal_analysis(
    business_id: int = Query(...),
    years: int = Query(2, ge=1, le=5),
    db: Session = Depends(get_db),
):
    """Quality pass rate and shipment volume by calendar month (seasonal patterns)."""
    _ensure_tables(db)
    quality = db.execute(text("""
        SELECT DATEPART(month, TestedAt) AS month_num,
               DATENAME(month, TestedAt) AS month_name,
               DATEPART(year,  TestedAt) AS yr,
               COUNT(1) AS tests,
               SUM(CASE WHEN PassFail='pass' THEN 1 ELSE 0 END) AS passed
          FROM ESCI_QualityTest
         WHERE BusinessID = :bid
           AND TestedAt >= DATEADD(year, -:y, GETDATE())
         GROUP BY DATEPART(month, TestedAt), DATENAME(month, TestedAt), DATEPART(year, TestedAt)
         ORDER BY yr ASC, month_num ASC
    """), {"bid": business_id, "y": years}).fetchall()

    yield_data = db.execute(text("""
        SELECT DATEPART(month, HarvestStart) AS month_num,
               DATENAME(month, HarvestStart) AS month_name,
               SUM(ForecastQty) AS total_forecast,
               SUM(ActualQty)   AS total_actual
          FROM ESCI_YieldForecast
         WHERE BusinessID = :bid
           AND HarvestStart >= DATEADD(year, -:y, GETDATE())
           AND HarvestStart IS NOT NULL
         GROUP BY DATEPART(month, HarvestStart), DATENAME(month, HarvestStart)
         ORDER BY month_num ASC
    """), {"bid": business_id, "y": years}).fetchall()

    q_by_month: dict = {}
    for r in quality:
        key = int(r.month_num)
        if key not in q_by_month:
            q_by_month[key] = {"month_num": key, "month_name": r.month_name, "tests": 0, "passed": 0}
        q_by_month[key]["tests"]  += int(r.tests)
        q_by_month[key]["passed"] += int(r.passed)
    for v in q_by_month.values():
        v["pass_rate_pct"] = round(v["passed"] / v["tests"] * 100, 1) if v["tests"] else None

    return {
        "quality_by_month": list(q_by_month.values()),
        "yield_by_month":   [_ser(r) for r in yield_data],
    }


# ── Supplier Scorecard ────────────────────────────────────────────────────────

@router.get("/scorecard")
def supplier_scorecard(
    business_id: int = Query(...),
    supplier_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """Aggregated per-supplier performance: delivery, quality, exceptions, margin."""
    _ensure_tables(db)
    where = "WHERE sp.BusinessID=:bid AND sp.IsActive=1"
    params: dict = {"bid": business_id}
    if supplier_id:
        where += " AND sp.SupplierID=:sid"; params["sid"] = supplier_id

    rows = db.execute(text(f"""
        SELECT sp.SupplierID, sp.SupplierName, sp.Country, sp.Region,
               sp.SupplierType, sp.CertifiedOrganic, sp.CertifiedGAP, sp.GlobalGAP,
               COUNT(DISTINCT s.ShipmentID)   AS total_shipments,
               SUM(CASE WHEN s.Status='received' THEN 1 ELSE 0 END) AS received,
               SUM(CASE WHEN s.Status='rejected' THEN 1 ELSE 0 END) AS rejected,
               AVG(CASE
                   WHEN s.ReceivedDate IS NOT NULL AND s.ExpectedDate IS NOT NULL
                   THEN CAST(DATEDIFF(day, s.ExpectedDate, s.ReceivedDate) AS FLOAT)
                   ELSE NULL END) AS avg_delay_days,
               COUNT(DISTINCT qt.TestID) AS quality_tests,
               SUM(CASE WHEN qt.PassFail='fail' THEN 1 ELSE 0 END) AS quality_fails,
               COUNT(DISTINCT ex.ExceptionID) AS total_exceptions,
               SUM(CASE WHEN ex.Status='open' THEN 1 ELSE 0 END) AS open_exceptions,
               AVG(CAST(mr.MarginPct AS FLOAT)) AS avg_margin_pct
          FROM ESCI_SupplierProfile sp
          LEFT JOIN ESCI_Shipment s     ON s.SupplierID  = sp.SupplierID AND s.BusinessID  = sp.BusinessID
          LEFT JOIN ESCI_QualityTest qt ON qt.ShipmentID = s.ShipmentID
          LEFT JOIN ESCI_Exception ex   ON ex.SupplierID = sp.SupplierID AND ex.BusinessID = sp.BusinessID
          LEFT JOIN ESCI_MarginRecord mr ON mr.BusinessID = sp.BusinessID
          {where}
         GROUP BY sp.SupplierID, sp.SupplierName, sp.Country, sp.Region,
                  sp.SupplierType, sp.CertifiedOrganic, sp.CertifiedGAP, sp.GlobalGAP
         ORDER BY sp.SupplierName
    """), params).fetchall()

    result = []
    for r in rows:
        d = _ser(r)
        # Compute composite score (0-100): delivery 40%, quality 40%, exception load 20%
        total = d.get("total_shipments") or 0
        recv  = d.get("received") or 0
        rej   = d.get("rejected") or 0
        tests = d.get("quality_tests") or 0
        fails = d.get("quality_fails") or 0
        delivery_score = round((recv / total * 100) if total > 0 else 0, 1)
        quality_score  = round(((tests - fails) / tests * 100) if tests > 0 else 0, 1)
        exc_open  = d.get("open_exceptions") or 0
        exc_total = d.get("total_exceptions") or 0
        exception_score = round(max(0, 100 - exc_open * 10), 1)
        composite = round(delivery_score * 0.4 + quality_score * 0.4 + exception_score * 0.2, 1)
        d["delivery_score"]  = delivery_score
        d["quality_score"]   = quality_score
        d["exception_score"] = exception_score
        d["composite_score"] = composite
        result.append(d)

    return result


# ── Contract vs Market Price Comparison ───────────────────────────────────────

@router.get("/contract-market-comparison")
def contract_market_comparison(
    business_id: int = Query(...),
    db: Session = Depends(get_db),
):
    """Compare contracted agreed prices vs latest market benchmark prices."""
    _ensure_tables(db)
    contracts = db.execute(text("""
        SELECT c.ContractID, c.ProductName, c.ProductCategory,
               c.AgreePrice, c.PriceFloor, c.PriceCeiling, c.Currency,
               c.Status, c.SeasonEnd, sp.SupplierName
          FROM ESCI_Contract c
          LEFT JOIN ESCI_SupplierProfile sp ON sp.SupplierID = c.SupplierID
         WHERE c.BusinessID = :bid AND c.Status = 'active'
    """), {"bid": business_id}).fetchall()

    market = db.execute(text("""
        SELECT Commodity, MAX(PriceDate) AS latest_date,
               AVG(CAST(PricePerUnit AS FLOAT)) AS avg_price,
               MAX(CAST(PricePerUnit AS FLOAT)) AS max_price,
               MIN(CAST(PricePerUnit AS FLOAT)) AS min_price,
               Unit
          FROM ESCI_MarketPrice
         WHERE BusinessID = :bid
           AND PriceDate >= DATEADD(day, -90, GETDATE())
         GROUP BY Commodity, Unit
    """), {"bid": business_id}).fetchall()

    market_map = {r.Commodity.lower(): _ser(r) for r in market}

    result = []
    for c in contracts:
        cd = _ser(c)
        market_key = c.ProductName.lower()
        mp = market_map.get(market_key) or next(
            (v for k, v in market_map.items() if market_key in k or k in market_key), None
        )
        if mp and cd.get("AgreePrice"):
            agree = float(cd["AgreePrice"])
            mkt   = float(mp["avg_price"])
            premium_pct = round((agree - mkt) / mkt * 100, 1) if mkt else None
            cd["market_avg_price"]   = mp["avg_price"]
            cd["market_min_price"]   = mp["min_price"]
            cd["market_max_price"]   = mp["max_price"]
            cd["market_latest_date"] = mp["latest_date"]
            cd["premium_pct"]        = premium_pct
            cd["above_market"]       = agree > mkt if mkt else None
        result.append(cd)

    return result


# ── Bulk CSV Import ───────────────────────────────────────────────────────────

@router.post("/import/demand-forecasts")
def bulk_import_demand_forecasts(body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    """Bulk insert demand forecast rows from a parsed CSV (list of objects)."""
    _ensure_tables(db)
    business_id = body.get("business_id")
    rows: List[dict] = body.get("rows", [])
    if not business_id:
        raise HTTPException(400, "business_id is required")
    if not rows:
        return {"imported": 0, "errors": []}

    imported, errors = 0, []
    for i, r in enumerate(rows):
        try:
            if not r.get("ProductName") or not r.get("PeriodStart"):
                errors.append({"row": i + 1, "error": "ProductName and PeriodStart required"})
                continue
            db.execute(text("""
                INSERT INTO ESCI_DemandForecast
                    (BusinessID, ProductName, ProductCategory, CustomerSegment, PeriodType,
                     PeriodStart, PeriodEnd, ForecastQty, Unit, ActualQty, ConfidencePct, Notes)
                VALUES (:bid, :prod, :cat, :seg, :ptype, :ps, :pe, :fqty, :unit, :aqty, :conf, :notes)
            """), {
                "bid":   business_id,
                "prod":  r["ProductName"],
                "cat":   r.get("ProductCategory"),
                "seg":   r.get("CustomerSegment"),
                "ptype": r.get("PeriodType", "weekly"),
                "ps":    r["PeriodStart"],
                "pe":    r.get("PeriodEnd"),
                "fqty":  r.get("ForecastQty") or 0,
                "unit":  r.get("Unit"),
                "aqty":  r.get("ActualQty"),
                "conf":  r.get("ConfidencePct"),
                "notes": r.get("Notes"),
            })
            imported += 1
        except Exception as e:
            errors.append({"row": i + 1, "error": str(e)})
    db.commit()
    return {"imported": imported, "errors": errors}


@router.post("/import/margin-records")
def bulk_import_margin_records(body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    """Bulk insert margin records from a parsed CSV."""
    _ensure_tables(db)
    business_id = body.get("business_id")
    rows: List[dict] = body.get("rows", [])
    if not business_id:
        raise HTTPException(400, "business_id is required")
    if not rows:
        return {"imported": 0, "errors": []}

    imported, errors = 0, []
    for i, r in enumerate(rows):
        try:
            if not r.get("ProductName") or not r.get("PeriodStart"):
                errors.append({"row": i + 1, "error": "ProductName and PeriodStart required"})
                continue
            db.execute(text("""
                INSERT INTO ESCI_MarginRecord
                    (BusinessID, ProductName, ProductCategory, PeriodStart, PeriodEnd,
                     Qty, Unit, LandedCostUnit, SalePriceUnit, Currency, Notes)
                VALUES (:bid, :prod, :cat, :ps, :pe, :qty, :unit, :lcost, :sprice, :cur, :notes)
            """), {
                "bid":    business_id,
                "prod":   r["ProductName"],
                "cat":    r.get("ProductCategory"),
                "ps":     r["PeriodStart"],
                "pe":     r.get("PeriodEnd"),
                "qty":    r.get("Qty"),
                "unit":   r.get("Unit"),
                "lcost":  r.get("LandedCostUnit"),
                "sprice": r.get("SalePriceUnit"),
                "cur":    r.get("Currency", "USD"),
                "notes":  r.get("Notes"),
            })
            imported += 1
        except Exception as e:
            errors.append({"row": i + 1, "error": str(e)})
    db.commit()
    return {"imported": imported, "errors": errors}


# ── Escalation Rules ──────────────────────────────────────────────────────────

@router.get("/escalation-rules")
def list_escalation_rules(business_id: int = Query(...), db: Session = Depends(get_db)):
    _ensure_tables(db)
    rows = db.execute(text("""
        SELECT * FROM ESCI_EscalationRule WHERE BusinessID=:bid ORDER BY Severity, HoursUntilEscalate
    """), {"bid": business_id}).fetchall()
    return [_ser(r) for r in rows]


@router.post("/escalation-rules")
def create_escalation_rule(body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    _ensure_tables(db)
    if not body.get("BusinessID"):
        raise HTTPException(400, "BusinessID is required")
    row = db.execute(text("""
        INSERT INTO ESCI_EscalationRule (BusinessID, Severity, HoursUntilEscalate, EscalateTo)
        OUTPUT INSERTED.RuleID
        VALUES (:bid, :sev, :hrs, :to)
    """), {
        "bid": body["BusinessID"],
        "sev": body.get("Severity", "critical"),
        "hrs": body.get("HoursUntilEscalate", 4),
        "to":  body.get("EscalateTo"),
    }).fetchone()
    db.commit()
    return {"RuleID": row[0]}


@router.delete("/escalation-rules/{rule_id}")
def delete_escalation_rule(rule_id: int, db: Session = Depends(get_db)):
    _ensure_tables(db)
    db.execute(text("DELETE FROM ESCI_EscalationRule WHERE RuleID=:rid"), {"rid": rule_id})
    db.commit()
    return {"ok": True}


@router.post("/escalation-rules/run")
def run_escalation(business_id: int = Query(...), db: Session = Depends(get_db)):
    """Check all open exceptions against escalation rules; escalate if overdue."""
    _ensure_tables(db)
    rules = db.execute(text("""
        SELECT * FROM ESCI_EscalationRule WHERE BusinessID=:bid AND IsActive=1
    """), {"bid": business_id}).fetchall()

    escalated = 0
    for rule in rules:
        exceptions = db.execute(text("""
            SELECT ExceptionID, Title, Severity, EscalationLevel, DetectedAt
              FROM ESCI_Exception
             WHERE BusinessID=:bid AND Status='open'
               AND Severity=:sev
               AND (EscalationLevel IS NULL OR EscalationLevel < 3)
               AND DetectedAt <= DATEADD(hour, -:hrs, GETDATE())
               AND (EscalatedAt IS NULL OR EscalatedAt <= DATEADD(hour, -:hrs, GETDATE()))
        """), {"bid": business_id, "sev": rule.Severity, "hrs": rule.HoursUntilEscalate}).fetchall()
        for exc in exceptions:
            new_level = (exc.EscalationLevel or 0) + 1
            db.execute(text("""
                UPDATE ESCI_Exception
                   SET EscalationLevel=:lvl, EscalatedAt=GETDATE(),
                       Severity=CASE WHEN Severity='high' AND :lvl>=2 THEN 'critical' ELSE Severity END
                 WHERE ExceptionID=:eid
            """), {"eid": exc.ExceptionID, "lvl": new_level})
            if rule.EscalateTo:
                db.execute(text("""
                    INSERT INTO ESCI_ExceptionNote (ExceptionID, BusinessID, AuthorName, NoteText)
                    VALUES (:eid, :bid, 'System', :note)
                """), {
                    "eid":  exc.ExceptionID,
                    "bid":  business_id,
                    "note": f"Auto-escalated to level {new_level}. Assigned to: {rule.EscalateTo}",
                })
            escalated += 1
    db.commit()
    return {"escalated": escalated}


# ── Supply Chain Report ───────────────────────────────────────────────────────

@router.get("/report")
def supply_chain_report(
    business_id: int = Query(...),
    days: int = Query(30, ge=7, le=365),
    db: Session = Depends(get_db),
):
    """Comprehensive report data bundle for the supply chain period."""
    _ensure_tables(db)

    summary = db.execute(text("""
        SELECT
            (SELECT COUNT(1) FROM ESCI_SupplierProfile WHERE BusinessID=:bid AND IsActive=1) AS active_suppliers,
            (SELECT COUNT(1) FROM ESCI_Contract     WHERE BusinessID=:bid AND Status='active') AS active_contracts,
            (SELECT COUNT(1) FROM ESCI_Shipment     WHERE BusinessID=:bid AND CreatedAt>=DATEADD(day,-:d,GETDATE())) AS total_shipments,
            (SELECT COUNT(1) FROM ESCI_Exception    WHERE BusinessID=:bid AND DetectedAt>=DATEADD(day,-:d,GETDATE())) AS total_exceptions,
            (SELECT COUNT(1) FROM ESCI_Exception    WHERE BusinessID=:bid AND Status='open') AS open_exceptions,
            (SELECT COUNT(1) FROM ESCI_QualityTest  WHERE BusinessID=:bid AND TestedAt>=DATEADD(day,-:d,GETDATE())) AS quality_tests,
            (SELECT SUM(CASE WHEN PassFail='pass' THEN 1 ELSE 0 END)
               FROM ESCI_QualityTest WHERE BusinessID=:bid AND TestedAt>=DATEADD(day,-:d,GETDATE())) AS quality_passed,
            (SELECT AVG(CAST(MarginPct AS FLOAT))
               FROM ESCI_MarginRecord WHERE BusinessID=:bid AND PeriodStart>=DATEADD(day,-:d,GETDATE())) AS avg_margin_pct
    """), {"bid": business_id, "d": days}).fetchone()

    top_exceptions = db.execute(text("""
        SELECT TOP 10 e.ExceptionID, e.Severity, e.ExceptionType, e.Title,
               e.Status, e.DetectedAt, sp.SupplierName
          FROM ESCI_Exception e
          LEFT JOIN ESCI_SupplierProfile sp ON sp.SupplierID=e.SupplierID
         WHERE e.BusinessID=:bid AND e.DetectedAt>=DATEADD(day,-:d,GETDATE())
         ORDER BY CASE e.Severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 ELSE 3 END, e.DetectedAt DESC
    """), {"bid": business_id, "d": days}).fetchall()

    quality_by_supplier = db.execute(text("""
        SELECT sp.SupplierName,
               COUNT(qt.TestID) AS tests,
               SUM(CASE WHEN qt.PassFail='pass' THEN 1 ELSE 0 END) AS passed,
               AVG(CAST(qt.DefectPct AS FLOAT)) AS avg_defect
          FROM ESCI_QualityTest qt
          LEFT JOIN ESCI_Shipment s ON s.ShipmentID=qt.ShipmentID
          LEFT JOIN ESCI_SupplierProfile sp ON sp.SupplierID=s.SupplierID
         WHERE qt.BusinessID=:bid AND qt.TestedAt>=DATEADD(day,-:d,GETDATE())
         GROUP BY sp.SupplierName
         ORDER BY tests DESC
    """), {"bid": business_id, "d": days}).fetchall()

    margin_by_cat = db.execute(text("""
        SELECT ProductCategory,
               COUNT(1) AS records,
               AVG(CAST(MarginPct AS FLOAT)) AS avg_margin_pct,
               SUM(Qty * SalePriceUnit) AS total_revenue
          FROM ESCI_MarginRecord
         WHERE BusinessID=:bid AND PeriodStart>=DATEADD(day,-:d,GETDATE())
         GROUP BY ProductCategory
         ORDER BY avg_margin_pct ASC
    """), {"bid": business_id, "d": days}).fetchall()

    s = _ser(summary) if summary else {}
    qt = int(s.get("quality_tests") or 0)
    qp = int(s.get("quality_passed") or 0)

    return {
        "generated_at":      datetime.datetime.utcnow().isoformat(),
        "period_days":       days,
        "business_id":       business_id,
        "summary": {
            "active_suppliers":  int(s.get("active_suppliers") or 0),
            "active_contracts":  int(s.get("active_contracts") or 0),
            "total_shipments":   int(s.get("total_shipments") or 0),
            "total_exceptions":  int(s.get("total_exceptions") or 0),
            "open_exceptions":   int(s.get("open_exceptions") or 0),
            "quality_tests":     qt,
            "quality_pass_rate": round(qp / qt * 100, 1) if qt else None,
            "avg_margin_pct":    round(float(s["avg_margin_pct"]), 2) if s.get("avg_margin_pct") else None,
        },
        "top_exceptions":        [_ser(r) for r in top_exceptions],
        "quality_by_supplier":   [_ser(r) for r in quality_by_supplier],
        "margin_by_category":    [_ser(r) for r in margin_by_cat],
    }


# ── Supplier Portal ───────────────────────────────────────────────────────────

@router.post("/supplier-portal/tokens")
def create_portal_token(
    body: dict,
    current_user: models.People = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    body = blank_to_none(body)
    """Create a token-authenticated portal link for a supplier."""
    _ensure_tables(db)
    if not body.get("BusinessID") or not body.get("SupplierID"):
        raise HTTPException(400, "BusinessID and SupplierID are required")
    token = secrets.token_urlsafe(32)
    row = db.execute(text("""
        INSERT INTO ESCI_SupplierPortalToken
            (BusinessID, SupplierID, Token, Label, ExpiresAt)
        OUTPUT INSERTED.TokenID
        VALUES (:bid, :sid, :tok, :label, :exp)
    """), {
        "bid":   body["BusinessID"],
        "sid":   body["SupplierID"],
        "tok":   token,
        "label": body.get("Label"),
        "exp":   body.get("ExpiresAt"),
    }).fetchone()
    db.commit()
    return {"TokenID": row[0], "Token": token}


@router.get("/supplier-portal/tokens")
def list_portal_tokens(
    business_id: int = Query(...),
    current_user: models.People = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    rows = db.execute(text("""
        SELECT t.*, sp.SupplierName
          FROM ESCI_SupplierPortalToken t
          LEFT JOIN ESCI_SupplierProfile sp ON sp.SupplierID = t.SupplierID
         WHERE t.BusinessID=:bid
         ORDER BY t.CreatedAt DESC
    """), {"bid": business_id}).fetchall()
    return [_ser(r) for r in rows]


@router.delete("/supplier-portal/tokens/{token_id}")
def revoke_portal_token(
    token_id: int,
    current_user: models.People = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_tables(db)
    db.execute(text(
        "UPDATE ESCI_SupplierPortalToken SET IsActive=0 WHERE TokenID=:tid"
    ), {"tid": token_id})
    db.commit()
    return {"ok": True}


@router.get("/supplier-portal/{token}")
def get_supplier_portal(token: str, db: Session = Depends(get_db)):
    """Public endpoint — returns portal context for a supplier token."""
    _ensure_tables(db)
    tok = db.execute(text("""
        SELECT t.*, sp.SupplierName, sp.Country, sp.Region
          FROM ESCI_SupplierPortalToken t
          LEFT JOIN ESCI_SupplierProfile sp ON sp.SupplierID = t.SupplierID
         WHERE t.Token=:tok AND t.IsActive=1
           AND (t.ExpiresAt IS NULL OR t.ExpiresAt > GETDATE())
    """), {"tok": token}).fetchone()
    if not tok:
        raise HTTPException(404, "Invalid or expired portal link")

    shipments = db.execute(text("""
        SELECT TOP 20 ShipmentID, ShipmentRef, ProductName, Status, ExpectedDate,
               OrderedQty, Unit, OriginLocation
          FROM ESCI_Shipment
         WHERE BusinessID=:bid AND SupplierID=:sid
           AND Status IN ('pending','in_transit')
         ORDER BY ExpectedDate ASC
    """), {"bid": int(tok.BusinessID), "sid": int(tok.SupplierID)}).fetchall()

    return {
        "supplier_name":  tok.SupplierName,
        "supplier_id":    int(tok.SupplierID),
        "business_id":    int(tok.BusinessID),
        "label":          tok.Label,
        "active_shipments": [_ser(s) for s in shipments],
    }


@router.post("/supplier-portal/{token}/quality")
def portal_submit_quality(token: str, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    """Public — supplier submits a quality test result via portal token."""
    _ensure_tables(db)
    tok = db.execute(text("""
        SELECT * FROM ESCI_SupplierPortalToken
         WHERE Token=:tok AND IsActive=1
           AND (ExpiresAt IS NULL OR ExpiresAt > GETDATE())
    """), {"tok": token}).fetchone()
    if not tok:
        raise HTTPException(404, "Invalid or expired portal link")
    if not body.get("ShipmentID"):
        raise HTTPException(400, "ShipmentID is required")

    row = db.execute(text("""
        INSERT INTO ESCI_QualityTest
            (ShipmentID, BusinessID, TestedAt, Tester, Grade, PassFail,
             DefectPct, BrixLevel, MoisturePct, PesticideResult, MicrobialResult, Notes)
        OUTPUT INSERTED.TestID
        VALUES (:sid, :bid, COALESCE(:at, GETDATE()), :tester, :grade, :pf,
                :defect, :brix, :moisture, :pest, :micro, :notes)
    """), {
        "sid":      body["ShipmentID"],
        "bid":      int(tok.BusinessID),
        "at":       body.get("TestedAt"),
        "tester":   body.get("Tester"),
        "grade":    body.get("Grade"),
        "pf":       body.get("PassFail", "pass"),
        "defect":   body.get("DefectPct"),
        "brix":     body.get("BrixLevel"),
        "moisture": body.get("MoisturePct"),
        "pest":     body.get("PesticideResult"),
        "micro":    body.get("MicrobialResult"),
        "notes":    body.get("Notes"),
    }).fetchone()
    db.commit()
    return {"TestID": row[0], "ok": True}


@router.post("/supplier-portal/{token}/event")
def portal_submit_event(token: str, body: dict, db: Session = Depends(get_db)):
    body = blank_to_none(body)
    """Public — supplier submits a shipment status event via portal token."""
    _ensure_tables(db)
    tok = db.execute(text("""
        SELECT * FROM ESCI_SupplierPortalToken
         WHERE Token=:tok AND IsActive=1
           AND (ExpiresAt IS NULL OR ExpiresAt > GETDATE())
    """), {"tok": token}).fetchone()
    if not tok:
        raise HTTPException(404, "Invalid or expired portal link")
    if not body.get("ShipmentID") or not body.get("EventType"):
        raise HTTPException(400, "ShipmentID and EventType are required")

    row = db.execute(text("""
        INSERT INTO ESCI_ShipmentEvent
            (ShipmentID, BusinessID, EventType, OccurredAt, Location, TempC, Notes, RecordedBy)
        OUTPUT INSERTED.EventID
        VALUES (:sid, :bid, :etype, COALESCE(:at, GETDATE()), :loc, :temp, :notes, :by)
    """), {
        "sid":   body["ShipmentID"],
        "bid":   int(tok.BusinessID),
        "etype": body["EventType"],
        "at":    body.get("OccurredAt"),
        "loc":   body.get("Location"),
        "temp":  body.get("TempC"),
        "notes": body.get("Notes"),
        "by":    body.get("RecordedBy"),
    }).fetchone()
    # Update shipment status if provided
    if body.get("NewStatus"):
        db.execute(text(
            "UPDATE ESCI_Shipment SET Status=:st WHERE ShipmentID=:sid"
        ), {"st": body["NewStatus"], "sid": body["ShipmentID"]})
    db.commit()
    return {"EventID": row[0], "ok": True}


# ── Precision Ag Bridge ───────────────────────────────────────────────────────

@router.get("/precision-ag-bridge")
def precision_ag_bridge(
    business_id: int = Query(...),
    db: Session = Depends(get_db),
):
    """Pull field and crop analysis data from Precision Ag to inform yield forecasts."""
    _ensure_tables(db)
    try:
        fields = db.execute(text("""
            SELECT TOP 20 id AS FieldID, name AS FieldName, areaha AS AreaHa,
                   crop AS CropType, business_id AS BusinessID
              FROM fields
             WHERE business_id=:bid
        """), {"bid": business_id}).fetchall()
    except Exception:
        fields = []

    try:
        analyses = db.execute(text("""
            SELECT TOP 20 a.id AS AnalysisID, a.field_id AS FieldID,
                   f.name AS FieldName, a.analysis_type, a.created_at,
                   a.ndvi_mean, a.ndvi_min, a.ndvi_max
              FROM analyses a
              LEFT JOIN fields f ON f.id = a.field_id
             WHERE f.business_id=:bid
             ORDER BY a.created_at DESC
        """), {"bid": business_id}).fetchall()
    except Exception:
        analyses = []

    return {
        "fields":   [_ser(r) for r in fields],
        "analyses": [_ser(r) for r in analyses],
        "note": "Use field NDVI and area data to calibrate yield forecast quantities.",
    }
