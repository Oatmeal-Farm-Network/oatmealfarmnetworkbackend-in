"""
Tarrigon — Enterprise Supply Chain Intelligence AI Agent
Pronounced "Tarragon" (the herb). Gemini-powered, follows Thaiyme's architecture.

Memory: Firestore Artemis DB, collection Tarrigon_chats.
RAG:    tarrigon_collection.
Tools:  supply chain reads + writes — suppliers, contracts, shipments, quality,
        margins, forecasts, exceptions, market prices, dashboard KPIs.
        Write tools: update shipment status, create/resolve/assign exceptions,
        update exception severity.

Architecture: request-response with up to 4 Gemini tool-calling loops.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
from auth import get_current_user
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import models
import os, re, datetime, uuid, logging

router = APIRouter(prefix="/api/tarrigon", tags=["tarrigon-ai"])
logger = logging.getLogger("tarrigon")

AGENT_NAME = "Tarrigon"

# ── Firestore / Artemis ───────────────────────────────────────────────────────
GCP_PROJECT              = os.getenv("GOOGLE_CLOUD_PROJECT", "animated-flare-421518").strip()
GCP_CREDS                = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
ARTEMIS_DB               = "artemis"
TARRIGON_RAG_COLLECTION  = "tarrigon_collection"
TARRIGON_CHATS_COLLECTION = "Tarrigon_chats"

SHORT_TERM_N          = int(os.getenv("TARRIGON_SHORT_TERM_N", "20"))
MAX_MESSAGE_CHARS     = int(os.getenv("TARRIGON_MAX_MESSAGE_CHARS", "4000"))
RAG_TOP_K             = int(os.getenv("TARRIGON_RAG_TOP_K", "6"))


# ── Pydantic ──────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    business_id: Optional[int] = None
    page: Optional[str] = None
    messages: List[ChatMessage]


# ── Firestore (lazy) ──────────────────────────────────────────────────────────

_firestore_client = None

def _firestore():
    global _firestore_client
    if _firestore_client:
        return _firestore_client
    try:
        from google.cloud import firestore
        if GCP_CREDS:
            from google.oauth2 import service_account
            creds = service_account.Credentials.from_service_account_file(
                GCP_CREDS, scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            _firestore_client = firestore.Client(
                project=GCP_PROJECT, database=ARTEMIS_DB, credentials=creds
            )
        else:
            _firestore_client = firestore.Client(project=GCP_PROJECT, database=ARTEMIS_DB)
        logger.info("[Tarrigon] Firestore (Artemis) connected")
    except Exception as e:
        logger.warning("[Tarrigon] Firestore unavailable: %s", e)
    return _firestore_client


# ── Access guard ──────────────────────────────────────────────────────────────

def _check_business_access(db: Session, people_id: int, business_id: int, min_level: int = 1):
    row = db.query(models.BusinessAccess).filter(
        models.BusinessAccess.BusinessID == business_id,
        models.BusinessAccess.PeopleID == people_id,
        models.BusinessAccess.Active == 1,
    ).first()
    if not row or row.AccessLevelID < min_level:
        raise HTTPException(403, f"Tarrigon requires AccessLevelID >= {min_level} on business {business_id}.")
    return row.AccessLevelID


# ── Supply chain tool implementations ────────────────────────────────────────

def _ser(row) -> dict:
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


def _dashboard_kpis(db: Session, business_id: int) -> Dict[str, Any]:
    try:
        from routers.esci import _ensure_tables as _ensure_esci
        _ensure_esci(db)
    except Exception:
        pass
    try:
        suppliers = db.execute(text(
            "SELECT COUNT(1) AS n FROM ESCISupplier WHERE BusinessID=:bid AND IsActive=1"
        ), {"bid": business_id}).fetchone()
        in_transit = db.execute(text(
            "SELECT COUNT(1) AS n FROM ESCIShipment WHERE BusinessID=:bid AND Status='in_transit'"
        ), {"bid": business_id}).fetchone()
        open_exc = db.execute(text(
            "SELECT COUNT(1) AS total, "
            "SUM(CASE WHEN Severity='critical' THEN 1 ELSE 0 END) AS critical "
            "FROM ESCIException WHERE BusinessID=:bid AND Status NOT IN ('resolved')"
        ), {"bid": business_id}).fetchone()
        quality = db.execute(text("""
            SELECT COUNT(1) AS total,
                   SUM(CASE WHEN PassFail='pass' THEN 1 ELSE 0 END) AS passed
              FROM ESCIQualityTest
             WHERE BusinessID=:bid AND CreatedAt >= DATEADD(day,-30,GETDATE())
        """), {"bid": business_id}).fetchone()
        margin = db.execute(text("""
            SELECT AVG(CAST(MarginPercent AS FLOAT)) AS avg_margin_pct
              FROM ESCIMarginRecord
             WHERE BusinessID=:bid AND PurchaseDate >= DATEADD(day,-90,CAST(GETDATE() AS DATE))
        """), {"bid": business_id}).fetchone()
        overdue = db.execute(text("""
            SELECT COUNT(1) AS n FROM ESCIShipment
             WHERE BusinessID=:bid AND Status IN ('pending','in_transit')
               AND ExpectedArrival < CAST(GETDATE() AS DATE)
        """), {"bid": business_id}).fetchone()

        qt = int(quality.total) if quality else 0
        qpr = round(int(quality.passed)/qt*100,1) if qt > 0 else None

        return {
            "suppliers_active":      int(suppliers.n) if suppliers else 0,
            "shipments_in_transit":  int(in_transit.n) if in_transit else 0,
            "exceptions_open":       int(open_exc.total) if open_exc else 0,
            "exceptions_critical":   int(open_exc.critical) if open_exc else 0,
            "quality_tests_30d":     qt,
            "quality_pass_rate_pct": qpr,
            "avg_margin_pct_90d":    round(float(margin.avg_margin_pct),2) if margin and margin.avg_margin_pct is not None else None,
            "shipments_overdue":     int(overdue.n) if overdue else 0,
        }
    except Exception as e:
        return {"error": f"Dashboard unavailable: {e}"}


def _list_exceptions(db: Session, business_id: int, status: Optional[str] = "open",
                     severity: Optional[str] = None) -> Dict[str, Any]:
    try:
        where = ["e.BusinessID = :bid"]
        params: Dict[str, Any] = {"bid": business_id}
        if status == "open":
            where.append("e.Status NOT IN ('resolved')")
        elif status:
            where.append("e.Status = :st"); params["st"] = status
        if severity:
            where.append("e.Severity = :sev"); params["sev"] = severity
        rows = db.execute(text(f"""
            SELECT TOP 20
                   e.ExceptionID, e.Category AS ExceptionType, e.Severity, e.Status,
                   e.Title, e.Description AS Detail, e.CreatedAt AS DetectedAt, e.AssignedTo,
                   sup.SupplierName, s.Commodity AS ShipmentProduct
              FROM ESCIException e
              LEFT JOIN ESCISupplier sup ON sup.SupplierID = e.SupplierID
              LEFT JOIN ESCIShipment s ON s.ShipmentID = e.ShipmentID
             WHERE {' AND '.join(where)}
             ORDER BY CASE e.Severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2
                      WHEN 'medium' THEN 3 ELSE 4 END, e.CreatedAt DESC
        """), params).fetchall()
        return {"exceptions": [_ser(r) for r in rows], "count": len(rows)}
    except Exception as e:
        return {"error": f"Exceptions unavailable: {e}"}


def _shipment_status(db: Session, business_id: int, status: Optional[str] = None,
                     days: int = 30) -> Dict[str, Any]:
    try:
        where = ["s.BusinessID = :bid",
                 "s.CreatedAt >= DATEADD(day, -:d, GETDATE())"]
        params: Dict[str, Any] = {"bid": business_id, "d": days}
        if status:
            where.append("s.Status = :st"); params["st"] = status
        rows = db.execute(text(f"""
            SELECT TOP 25
                   s.ShipmentID, s.ShipmentRef, s.Commodity, s.Status,
                   s.QuantityKg, s.ExpectedArrival, s.ActualArrival,
                   s.Origin, s.Destination,
                   sup.SupplierName
              FROM ESCIShipment s
              LEFT JOIN ESCISupplier sup ON sup.SupplierID = s.SupplierID
             WHERE {' AND '.join(where)}
             ORDER BY s.ExpectedArrival ASC
        """), params).fetchall()
        return {"shipments": [_ser(r) for r in rows], "count": len(rows), "days": days}
    except Exception as e:
        return {"error": f"Shipments unavailable: {e}"}


def _quality_summary(db: Session, business_id: int, days: int = 30) -> Dict[str, Any]:
    try:
        overall = db.execute(text("""
            SELECT COUNT(1) AS total,
                   SUM(CASE WHEN PassFail='pass' THEN 1 ELSE 0 END) AS passed,
                   AVG(CAST(ImpuritiesPercent AS FLOAT)) AS avg_defect_pct
              FROM ESCIQualityTest
             WHERE BusinessID=:bid AND CreatedAt >= DATEADD(day,-:d,GETDATE())
        """), {"bid": business_id, "d": days}).fetchone()
        by_grade = db.execute(text("""
            SELECT Grade, COUNT(1) AS n FROM ESCIQualityTest
             WHERE BusinessID=:bid AND CreatedAt >= DATEADD(day,-:d,GETDATE())
               AND Grade IS NOT NULL
             GROUP BY Grade ORDER BY Grade
        """), {"bid": business_id, "d": days}).fetchall()
        recent_fails = db.execute(text("""
            SELECT TOP 5 qt.TestID, qt.PassFail, qt.Grade,
                   qt.ImpuritiesPercent AS DefectPct, qt.CreatedAt AS TestedAt,
                   s.Commodity AS ProductName, sup.SupplierName
              FROM ESCIQualityTest qt
              LEFT JOIN ESCIShipment s ON s.ShipmentID = qt.ShipmentID
              LEFT JOIN ESCISupplier sup ON sup.SupplierID = qt.SupplierID
             WHERE qt.BusinessID=:bid AND qt.PassFail='fail'
               AND qt.CreatedAt >= DATEADD(day,-:d,GETDATE())
             ORDER BY qt.CreatedAt DESC
        """), {"bid": business_id, "d": days}).fetchall()
        total = int(overall.total) if overall else 0
        pass_rate = round(int(overall.passed)/total*100,1) if total > 0 else None
        return {
            "period_days":     days,
            "total_tests":     total,
            "pass_rate_pct":   pass_rate,
            "avg_defect_pct":  round(float(overall.avg_defect_pct),2) if overall and overall.avg_defect_pct else None,
            "by_grade":        {r.Grade: int(r.n) for r in by_grade},
            "recent_failures": [_ser(r) for r in recent_fails],
        }
    except Exception as e:
        return {"error": f"Quality summary unavailable: {e}"}


def _margin_analysis(db: Session, business_id: int, days: int = 90) -> Dict[str, Any]:
    try:
        overall = db.execute(text("""
            SELECT AVG(CAST(MarginPercent AS FLOAT)) AS avg_pct,
                   MIN(CAST(MarginPercent AS FLOAT)) AS min_pct,
                   MAX(CAST(MarginPercent AS FLOAT)) AS max_pct,
                   COUNT(1) AS records
              FROM ESCIMarginRecord
             WHERE BusinessID=:bid AND PurchaseDate >= DATEADD(day,-:d,CAST(GETDATE() AS DATE))
        """), {"bid": business_id, "d": days}).fetchone()
        by_cat = db.execute(text("""
            SELECT Category AS ProductCategory, AVG(CAST(MarginPercent AS FLOAT)) AS avg_pct,
                   COUNT(1) AS records
              FROM ESCIMarginRecord
             WHERE BusinessID=:bid AND PurchaseDate >= DATEADD(day,-:d,CAST(GETDATE() AS DATE))
               AND Category IS NOT NULL
             GROUP BY Category
             ORDER BY avg_pct ASC
        """), {"bid": business_id, "d": days}).fetchall()
        low_margin = db.execute(text("""
            SELECT TOP 5 Commodity AS ProductName, Category AS ProductCategory,
                   CAST(MarginPercent AS FLOAT) AS MarginPct,
                   CAST(CostPerKg AS FLOAT) AS LandedCostUnit,
                   CAST(SalesPricePerKg AS FLOAT) AS SalePriceUnit,
                   PurchaseDate AS PeriodStart
              FROM ESCIMarginRecord
             WHERE BusinessID=:bid AND PurchaseDate >= DATEADD(day,-:d,CAST(GETDATE() AS DATE))
               AND MarginPercent < 15
             ORDER BY MarginPercent ASC
        """), {"bid": business_id, "d": days}).fetchall()
        return {
            "period_days":   days,
            "avg_margin_pct": round(float(overall.avg_pct),2) if overall and overall.avg_pct else None,
            "min_margin_pct": round(float(overall.min_pct),2) if overall and overall.min_pct else None,
            "max_margin_pct": round(float(overall.max_pct),2) if overall and overall.max_pct else None,
            "records":        int(overall.records) if overall else 0,
            "by_category":    [_ser(r) for r in by_cat],
            "low_margin_lines": [_ser(r) for r in low_margin],
        }
    except Exception as e:
        return {"error": f"Margin analysis unavailable: {e}"}


def _demand_supply_gap(db: Session, business_id: int, weeks_ahead: int = 4) -> Dict[str, Any]:
    try:
        today = datetime.date.today()
        future = today + datetime.timedelta(weeks=weeks_ahead)
        demand = db.execute(text("""
            SELECT Commodity AS ProductName, SUM(DemandKg) AS forecast_demand
              FROM ESCIDemandForecast
             WHERE BusinessID=:bid AND ForecastDate BETWEEN :s AND :e
             GROUP BY Commodity
        """), {"bid": business_id, "s": today.isoformat(), "e": future.isoformat()}).fetchall()
        supply = db.execute(text("""
            SELECT Commodity AS ProductName, SUM(ExpectedYieldKg) AS forecast_supply
              FROM ESCIYieldForecast
             WHERE BusinessID=:bid AND ForecastDate BETWEEN :s AND :e
             GROUP BY Commodity
        """), {"bid": business_id, "s": today.isoformat(), "e": future.isoformat()}).fetchall()
        supply_map = {r.ProductName.lower(): float(r.forecast_supply) for r in supply}
        gaps = []
        for d in demand:
            sup = supply_map.get(d.ProductName.lower(), 0.0)
            gap = float(d.forecast_demand) - sup
            gaps.append({
                "product": d.ProductName,
                "unit": "kg",
                "demand": float(d.forecast_demand),
                "supply": sup,
                "gap": gap,
                "shortfall": gap > 0,
            })
        return {
            "weeks_ahead": weeks_ahead,
            "period_start": today.isoformat(),
            "period_end":   future.isoformat(),
            "gaps": sorted(gaps, key=lambda x: x["gap"], reverse=True),
        }
    except Exception as e:
        return {"error": f"Gap analysis unavailable: {e}"}


def _market_price_benchmark(db: Session, business_id: int,
                             commodity: Optional[str] = None) -> Dict[str, Any]:
    try:
        where = "WHERE BusinessID=:bid"
        params: Dict[str, Any] = {"bid": business_id}
        if commodity:
            where += " AND Commodity LIKE :com"; params["com"] = f"%{commodity}%"
        rows = db.execute(text(f"""
            SELECT TOP 20 Commodity, PriceDate, PricePerKg AS PricePerUnit, Source AS Market, Region
              FROM ESCIMarketPrice {where}
             ORDER BY PriceDate DESC
        """), params).fetchall()
        return {"market_prices": [_ser(r) for r in rows], "count": len(rows)}
    except Exception as e:
        return {"error": f"Market prices unavailable: {e}"}


def _supplier_scorecard(db: Session, business_id: int,
                        supplier_id: Optional[int] = None) -> Dict[str, Any]:
    try:
        where = "WHERE sp.BusinessID=:bid AND sp.IsActive=1"
        params: Dict[str, Any] = {"bid": business_id}
        if supplier_id:
            where += " AND sp.SupplierID=:sid"; params["sid"] = supplier_id
        rows = db.execute(text(f"""
            SELECT sp.SupplierID, sp.SupplierName, sp.Country, sp.Category,
                   COUNT(DISTINCT s.ShipmentID) AS total_shipments,
                   SUM(CASE WHEN s.Status='delivered' THEN 1 ELSE 0 END) AS received,
                   SUM(CASE WHEN s.Status='cancelled' THEN 1 ELSE 0 END) AS rejected,
                   AVG(CASE WHEN s.ActualArrival IS NOT NULL AND s.ExpectedArrival IS NOT NULL
                            THEN CAST(DATEDIFF(day, s.ExpectedArrival, s.ActualArrival) AS FLOAT)
                            ELSE NULL END) AS avg_delay_days,
                   COUNT(DISTINCT qt.TestID) AS quality_tests,
                   SUM(CASE WHEN qt.PassFail='fail' THEN 1 ELSE 0 END) AS quality_fails
              FROM ESCISupplier sp
              LEFT JOIN ESCIShipment s ON s.SupplierID=sp.SupplierID AND s.BusinessID=sp.BusinessID
              LEFT JOIN ESCIQualityTest qt ON qt.SupplierID=sp.SupplierID
             {where}
             GROUP BY sp.SupplierID, sp.SupplierName, sp.Country, sp.Category
             ORDER BY sp.SupplierName
        """), params).fetchall()
        return {"suppliers": [_ser(r) for r in rows], "count": len(rows)}
    except Exception as e:
        return {"error": f"Supplier scorecard unavailable: {e}"}


# ── Write tools ──────────────────────────────────────────────────────────────

def _update_shipment_status(db: Session, business_id: int, shipment_id: int,
                             new_status: str, notes: Optional[str] = None) -> Dict[str, Any]:
    valid = {"pending", "in_transit", "delivered", "delayed", "cancelled"}
    if new_status not in valid:
        return {"error": f"Invalid status '{new_status}'. Must be one of: {', '.join(sorted(valid))}."}
    try:
        row = db.execute(text(
            "SELECT ShipmentID, Status, Commodity FROM ESCIShipment "
            "WHERE ShipmentID=:sid AND BusinessID=:bid"
        ), {"sid": shipment_id, "bid": business_id}).fetchone()
        if not row:
            return {"error": f"Shipment {shipment_id} not found for this business."}
        old_status = row.Status
        extra_set = ""
        extra_params: Dict[str, Any] = {}
        if new_status == "delivered":
            extra_set = ", ActualArrival=CAST(GETDATE() AS DATE)"
        if notes:
            extra_set += ", Notes=:notes"
            extra_params["notes"] = notes[:500]
        db.execute(text(
            f"UPDATE ESCIShipment SET Status=:st, UpdatedAt=GETDATE(){extra_set} "
            "WHERE ShipmentID=:sid AND BusinessID=:bid"
        ), {"st": new_status, "sid": shipment_id, "bid": business_id, **extra_params})
        db.commit()
        return {
            "ok": True,
            "shipment_id": shipment_id,
            "product": row.Commodity,
            "old_status": old_status,
            "new_status": new_status,
            "message": f"Shipment {shipment_id} ({row.Commodity}) status updated: {old_status} → {new_status}.",
        }
    except Exception as e:
        return {"error": f"Failed to update shipment: {e}"}


def _create_exception_tool(db: Session, business_id: int, exception_type: str,
                            severity: str, title: str, detail: str,
                            shipment_id: Optional[int] = None,
                            supplier_id: Optional[int] = None) -> Dict[str, Any]:
    valid_types = {"quality_failure", "delay", "volume_shortfall", "temperature_breach",
                   "documentation_missing", "supplier_dispute", "other"}
    valid_sev   = {"critical", "high", "medium", "low"}
    if exception_type not in valid_types:
        return {"error": f"Invalid type '{exception_type}'. Must be one of: {', '.join(sorted(valid_types))}."}
    if severity not in valid_sev:
        return {"error": f"Invalid severity '{severity}'. Must be one of: {', '.join(sorted(valid_sev))}."}
    try:
        db.execute(text("""
            INSERT INTO ESCIException
                (BusinessID, ShipmentID, SupplierID, Category, Severity,
                 Status, Title, Description)
            VALUES (:bid, :sid, :spid, :etype, :sev, 'open', :title, :detail)
        """), {
            "bid": business_id, "sid": shipment_id, "spid": supplier_id,
            "etype": exception_type, "sev": severity,
            "title": title[:200], "detail": detail[:1000],
        })
        db.commit()
        exc_id = db.execute(text("SELECT MAX(ExceptionID) AS id FROM ESCIException WHERE BusinessID=:bid"),
                            {"bid": business_id}).scalar()
        return {
            "ok": True,
            "exception_id": exc_id,
            "message": f"Exception created (ID {exc_id}): [{severity.upper()}] {title}",
        }
    except Exception as e:
        return {"error": f"Failed to create exception: {e}"}


def _resolve_exception_tool(db: Session, business_id: int, exception_id: int,
                             resolution_notes: str) -> Dict[str, Any]:
    try:
        row = db.execute(text(
            "SELECT ExceptionID, Status, Title FROM ESCIException "
            "WHERE ExceptionID=:eid AND BusinessID=:bid"
        ), {"eid": exception_id, "bid": business_id}).fetchone()
        if not row:
            return {"error": f"Exception {exception_id} not found for this business."}
        if row.Status == "resolved":
            return {"error": f"Exception {exception_id} is already resolved."}
        db.execute(text("""
            UPDATE ESCIException
               SET Status='resolved', ResolvedAt=GETDATE(), UpdatedAt=GETDATE(),
                   Description = ISNULL(Description,'') + CHAR(10) + '[Resolution: ' + :notes + ']'
             WHERE ExceptionID=:eid AND BusinessID=:bid
        """), {"notes": resolution_notes[:1000], "eid": exception_id, "bid": business_id})
        db.commit()
        return {
            "ok": True,
            "exception_id": exception_id,
            "title": row.Title,
            "message": f"Exception {exception_id} '{row.Title}' marked as resolved.",
        }
    except Exception as e:
        return {"error": f"Failed to resolve exception: {e}"}


def _assign_exception_tool(db: Session, business_id: int, exception_id: int,
                            assigned_to: str) -> Dict[str, Any]:
    try:
        row = db.execute(text(
            "SELECT ExceptionID, Title, AssignedTo FROM ESCIException "
            "WHERE ExceptionID=:eid AND BusinessID=:bid"
        ), {"eid": exception_id, "bid": business_id}).fetchone()
        if not row:
            return {"error": f"Exception {exception_id} not found for this business."}
        db.execute(text(
            "UPDATE ESCIException SET AssignedTo=:at, UpdatedAt=GETDATE() "
            "WHERE ExceptionID=:eid AND BusinessID=:bid"
        ), {"at": assigned_to[:100], "eid": exception_id, "bid": business_id})
        db.commit()
        prev = row.AssignedTo or "unassigned"
        return {
            "ok": True,
            "exception_id": exception_id,
            "title": row.Title,
            "assigned_to": assigned_to,
            "message": f"Exception {exception_id} reassigned: {prev} → {assigned_to}.",
        }
    except Exception as e:
        return {"error": f"Failed to assign exception: {e}"}


def _update_exception_severity(db: Session, business_id: int, exception_id: int,
                                new_severity: str, reason: Optional[str] = None) -> Dict[str, Any]:
    valid = {"critical", "high", "medium", "low"}
    if new_severity not in valid:
        return {"error": f"Invalid severity '{new_severity}'. Must be one of: {', '.join(sorted(valid))}."}
    try:
        row = db.execute(text(
            "SELECT ExceptionID, Severity, Title FROM ESCIException "
            "WHERE ExceptionID=:eid AND BusinessID=:bid"
        ), {"eid": exception_id, "bid": business_id}).fetchone()
        if not row:
            return {"error": f"Exception {exception_id} not found."}
        old_sev = row.Severity
        notes_append = f"\n[Severity changed {old_sev}→{new_severity}: {reason}]" if reason else f"\n[Severity changed {old_sev}→{new_severity}]"
        db.execute(text("""
            UPDATE ESCIException
               SET Severity=:sev, UpdatedAt=GETDATE(),
                   Description = ISNULL(Description,'') + :note
             WHERE ExceptionID=:eid AND BusinessID=:bid
        """), {"sev": new_severity, "note": notes_append[:500],
               "eid": exception_id, "bid": business_id})
        db.commit()
        return {
            "ok": True,
            "exception_id": exception_id,
            "title": row.Title,
            "old_severity": old_sev,
            "new_severity": new_severity,
            "message": f"Exception {exception_id} severity updated: {old_sev} → {new_severity}.",
        }
    except Exception as e:
        return {"error": f"Failed to update severity: {e}"}


# ── Tool registry ─────────────────────────────────────────────────────────────

def _build_tool_registry(business_id: Optional[int], db: Session) -> Dict[str, Dict[str, Any]]:
    registry: Dict[str, Dict[str, Any]] = {}
    if not business_id:
        return registry

    registry["supply_chain_kpis"] = {
        "desc": "Overall supply chain KPIs: active suppliers, active contracts, shipments in transit, open exceptions (by severity), quality pass rate (last 30 days), average margin % (last 90 days), overdue shipments. Call this first for any 'how is the supply chain doing' or 'give me a summary' question.",
        "params": {},
        "run": lambda **_: _dashboard_kpis(db, business_id),
        "mutating": False,
    }
    registry["list_exceptions"] = {
        "desc": "List open (or resolved) supply chain exceptions — quality failures, temperature breaches, volume shortfalls, delays. Use when asked 'what's flagged', 'any problems', 'critical alerts'.",
        "params": {
            "status":   {"type_": "STRING",  "description": "Filter: 'open' (default) or 'resolved'."},
            "severity": {"type_": "STRING",  "description": "Optional severity filter: critical, high, medium, low."},
        },
        "run": lambda status="open", severity=None, **_: _list_exceptions(db, business_id, status, severity),
        "mutating": False,
    }
    registry["shipment_status"] = {
        "desc": "List recent shipments with status, quantities, expected date. Optional status filter (pending/in_transit/received/rejected). Use for 'where are my shipments', 'what's in transit', 'any overdue'.",
        "params": {
            "status": {"type_": "STRING",  "description": "Optional: pending, in_transit, received, rejected."},
            "days":   {"type_": "INTEGER", "description": "Look-back window in days (default 30)."},
        },
        "run": lambda status=None, days=30, **_: _shipment_status(db, business_id, status, int(days or 30)),
        "mutating": False,
    }
    registry["quality_summary"] = {
        "desc": "Quality test results summary: pass rate, average defect %, by-grade breakdown, recent failures. Use for 'how is quality', 'any failing lots', 'quality pass rate this month'.",
        "params": {
            "days": {"type_": "INTEGER", "description": "Look-back window in days (default 30)."},
        },
        "run": lambda days=30, **_: _quality_summary(db, business_id, int(days or 30)),
        "mutating": False,
    }
    registry["margin_analysis"] = {
        "desc": "Margin analysis: average/min/max margin %, by-category breakdown, lowest-margin product lines. Use for 'what's our margin', 'which products are lowest margin', 'are we above our threshold'.",
        "params": {
            "days": {"type_": "INTEGER", "description": "Look-back window in days (default 90)."},
        },
        "run": lambda days=90, **_: _margin_analysis(db, business_id, int(days or 90)),
        "mutating": False,
    }
    registry["demand_supply_gap"] = {
        "desc": "Demand vs supply forecast gap analysis for the next N weeks. Shows which products have forecasted shortfalls or surplus. Use for 'will we have enough', 'any supply gaps', 'demand vs supply next month'.",
        "params": {
            "weeks_ahead": {"type_": "INTEGER", "description": "How many weeks to look ahead (default 4)."},
        },
        "run": lambda weeks_ahead=4, **_: _demand_supply_gap(db, business_id, int(weeks_ahead or 4)),
        "mutating": False,
    }
    registry["market_price_benchmark"] = {
        "desc": "Commodity market reference prices. Use for 'what's the market price for X', 'are we paying above market', 'benchmark our costs'.",
        "params": {
            "commodity": {"type_": "STRING", "description": "Optional commodity name to search for."},
        },
        "run": lambda commodity=None, **_: _market_price_benchmark(db, business_id, commodity),
        "mutating": False,
    }
    registry["supplier_scorecard"] = {
        "desc": "Supplier performance scorecard: total shipments, received vs rejected counts, average delay days, quality test pass/fail counts, certifications. Use for 'how are our suppliers performing', 'which supplier has the most rejections', 'supplier reliability'.",
        "params": {
            "supplier_id": {"type_": "INTEGER", "description": "Optional — limit to a specific SupplierID."},
        },
        "run": lambda supplier_id=None, **_: _supplier_scorecard(db, business_id, supplier_id),
        "mutating": False,
    }

    # ── Write tools ──────────────────────────────────────────────────────────
    registry["update_shipment_status"] = {
        "desc": "Update the status of a shipment (pending → in_transit → delivered / delayed / cancelled). Use when the user says 'mark shipment X as delivered', 'update shipment status', 'shipment arrived', 'flag shipment as delayed'. Requires ShipmentID (integer).",
        "params": {
            "shipment_id": {"type_": "INTEGER", "description": "The ShipmentID to update (required)."},
            "new_status":  {"type_": "STRING",  "description": "New status: pending, in_transit, delivered, delayed, or cancelled."},
            "notes":       {"type_": "STRING",  "description": "Optional notes to append to the shipment record."},
        },
        "run": lambda shipment_id, new_status, notes=None, **_: _update_shipment_status(
            db, business_id, int(shipment_id), new_status, notes),
        "mutating": True,
    }
    registry["create_exception"] = {
        "desc": "Create a new supply chain exception (quality failure, delay, volume shortfall, temperature breach, etc.). Use when the user says 'log an exception', 'flag this shipment', 'create an alert', 'record a quality failure'.",
        "params": {
            "exception_type": {"type_": "STRING",  "description": "Type: quality_failure, delay, volume_shortfall, temperature_breach, documentation_missing, supplier_dispute, other."},
            "severity":        {"type_": "STRING",  "description": "Severity: critical, high, medium, or low."},
            "title":           {"type_": "STRING",  "description": "Short title for the exception (max 200 chars)."},
            "detail":          {"type_": "STRING",  "description": "Detailed description of the issue (max 1000 chars)."},
            "shipment_id":     {"type_": "INTEGER", "description": "Optional — related ShipmentID."},
            "supplier_id":     {"type_": "INTEGER", "description": "Optional — related SupplierID."},
        },
        "run": lambda exception_type, severity, title, detail, shipment_id=None, supplier_id=None, **_:
            _create_exception_tool(db, business_id, exception_type, severity, title, detail,
                                   int(shipment_id) if shipment_id else None,
                                   int(supplier_id) if supplier_id else None),
        "mutating": True,
    }
    registry["resolve_exception"] = {
        "desc": "Mark a supply chain exception as resolved and record resolution notes. Use when the user says 'resolve exception X', 'close this exception', 'mark as fixed', 'exception handled'.",
        "params": {
            "exception_id":      {"type_": "INTEGER", "description": "The ExceptionID to resolve (required)."},
            "resolution_notes":  {"type_": "STRING",  "description": "Explanation of how the exception was resolved (required)."},
        },
        "run": lambda exception_id, resolution_notes, **_: _resolve_exception_tool(
            db, business_id, int(exception_id), resolution_notes),
        "mutating": True,
    }
    registry["assign_exception"] = {
        "desc": "Assign or reassign an exception to a team member. Use when the user says 'assign exception X to Y', 'who should handle this', 'delegate this exception'.",
        "params": {
            "exception_id":  {"type_": "INTEGER", "description": "The ExceptionID to assign."},
            "assigned_to":   {"type_": "STRING",  "description": "Name or email of the person to assign it to."},
        },
        "run": lambda exception_id, assigned_to, **_: _assign_exception_tool(
            db, business_id, int(exception_id), assigned_to),
        "mutating": True,
    }
    registry["update_exception_severity"] = {
        "desc": "Change the severity of an open exception (e.g. escalate from medium to high, or downgrade from critical to medium). Use when the user says 'escalate exception X', 'downgrade severity', 'this is now critical'.",
        "params": {
            "exception_id":  {"type_": "INTEGER", "description": "The ExceptionID to update."},
            "new_severity":  {"type_": "STRING",  "description": "New severity: critical, high, medium, or low."},
            "reason":        {"type_": "STRING",  "description": "Optional reason for the severity change."},
        },
        "run": lambda exception_id, new_severity, reason=None, **_: _update_exception_severity(
            db, business_id, int(exception_id), new_severity, reason),
        "mutating": True,
    }

    return registry


# ── RAG ───────────────────────────────────────────────────────────────────────

def _rag_search(query: str, n: int = RAG_TOP_K) -> str:
    fs = _firestore()
    if not fs:
        return ""
    try:
        col = fs.collection(TARRIGON_RAG_COLLECTION)
        try:
            from google.cloud.firestore_v1.vector import Vector
            from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
            import ai_vertex as av
            emb_vec = av.embed_query(query)
            vq = col.find_nearest(
                vector_field="embedding",
                query_vector=Vector(emb_vec),
                distance_measure=DistanceMeasure.COSINE,
                limit=n,
            )
            parts = []
            for doc in vq.stream():
                d = doc.to_dict() or {}
                t = d.get("content") or d.get("text") or ""
                if t:
                    parts.append(t)
            if parts:
                return "\n---\n".join(parts)
        except Exception:
            pass
        kws = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 2]
        scored = []
        for doc in col.limit(80).stream():
            d = doc.to_dict() or {}
            content = d.get("content") or d.get("text") or ""
            if not content.strip():
                continue
            score = sum(content.lower().count(k) for k in kws)
            if score > 0:
                scored.append((score, content))
        scored.sort(reverse=True)
        return "\n---\n".join(c for _, c in scored[:n])
    except Exception as e:
        logger.warning("[Tarrigon] RAG error: %s", e)
        return ""


# ── Memory (Firestore) ────────────────────────────────────────────────────────

def _thread_id_for(people_id: int, business_id: int) -> str:
    return f"{people_id}__esci_{business_id}"


def _save_message(people_id: int, business_id: int, role: str, content: str) -> None:
    fs = _firestore()
    if not fs:
        return
    try:
        from google.cloud import firestore as _fs
        thread_id = _thread_id_for(people_id, business_id)
        thread_ref = fs.collection(TARRIGON_CHATS_COLLECTION).document(thread_id)
        now = datetime.datetime.utcnow().isoformat()
        snap = thread_ref.get()
        if snap.exists:
            thread_ref.update({"updated_at": now, "message_count": _fs.Increment(1)})
        else:
            thread_ref.set({
                "thread_id":   thread_id,
                "people_id":   people_id,
                "business_id": business_id,
                "created_at":  now,
                "updated_at":  now,
                "message_count": 1,
            })
        msg_id = f"{now}_{uuid.uuid4().hex[:8]}"
        thread_ref.collection("messages").document(msg_id).set({
            "role":    role,
            "content": (content or "")[:MAX_MESSAGE_CHARS],
            "ts":      now,
        })
    except Exception as e:
        logger.warning("[Tarrigon] save_message failed: %s", e)


def _load_recent_messages(people_id: int, business_id: int,
                           limit: int = SHORT_TERM_N) -> List[Dict[str, str]]:
    fs = _firestore()
    if not fs:
        return []
    try:
        from google.cloud import firestore as _fs
        thread_id = _thread_id_for(people_id, business_id)
        msgs_ref = (
            fs.collection(TARRIGON_CHATS_COLLECTION)
              .document(thread_id)
              .collection("messages")
              .order_by("ts", direction=_fs.Query.DESCENDING)
              .limit(limit)
        )
        rows = [d.to_dict() for d in msgs_ref.stream()]
        rows.reverse()
        return [{"role": r.get("role", "user"), "content": r.get("content", "")} for r in rows]
    except Exception as e:
        logger.warning("[Tarrigon] load_messages failed: %s", e)
        return []


def _delete_thread(people_id: int, business_id: int) -> bool:
    fs = _firestore()
    if not fs:
        return False
    try:
        thread_id = _thread_id_for(people_id, business_id)
        thread_ref = fs.collection(TARRIGON_CHATS_COLLECTION).document(thread_id)
        msgs = thread_ref.collection("messages")
        while True:
            batch_docs = list(msgs.limit(100).stream())
            if not batch_docs:
                break
            for d in batch_docs:
                d.reference.delete()
        thread_ref.delete()
        return True
    except Exception as e:
        logger.warning("[Tarrigon] delete_thread failed: %s", e)
        return False


# ── System prompt ─────────────────────────────────────────────────────────────

def _system_prompt(rag: str, page_context: str, tool_names: List[str]) -> str:
    tool_help = ", ".join(tool_names) if tool_names else "(no tools available)"
    return f"""You are {AGENT_NAME} (pronounced "Tarragon"), a sharp, data-driven enterprise supply chain intelligence advisor for OatmealFarmNetwork.

Your job: help procurement, operations, and finance teams maintain end-to-end supply chain visibility (farm → DC → shelf), catch quality and margin risks early, keep demand and supply forecasts aligned, and resolve exceptions fast.

Tone: precise, concise, commercially-minded. Lead with numbers and action items. Skip pleasantries. One short insight beats three vague observations.

Tool-use rules:
- Available tools: {tool_help}.
- ALWAYS call a tool before answering quantitative questions. Never guess supply chain metrics.
- If a tool returns an error, say so clearly and suggest what data is missing.
- For any question about exceptions, shipments, quality, margins, or forecasts — call the relevant tool first, then summarize in 2-3 bullet points.
- You CAN modify data using write tools (update_shipment_status, create_exception, resolve_exception, assign_exception, update_exception_severity). When the user asks you to update, resolve, assign, or create supply chain records, use the appropriate write tool and confirm the result clearly.
- Before calling a write tool, confirm you have the required ID. If the user says "shipment 42" or "exception 7", extract the integer ID. If ambiguous, call a read tool first to find the right record and confirm with the user.
- After a successful write, tell the user what changed in one sentence (old value → new value).

CURRENT PAGE: {page_context or 'Supply Chain Dashboard'}

KNOWLEDGE BASE (supply chain best-practice references):
{rag or '(no relevant entries)'}
"""


# ── Gemini function-calling ────────────────────────────────────────────────────

def _proto_to_py(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (str, int, float, bool)):
        return v
    if hasattr(v, "items"):
        try:
            return {k: _proto_to_py(val) for k, val in v.items()}
        except Exception:
            pass
    if hasattr(v, "__iter__") and not isinstance(v, (str, bytes, dict)):
        try:
            return [_proto_to_py(x) for x in v]
        except Exception:
            pass
    return v


_JSON_TYPE = {"STRING": "string", "OBJECT": "object", "INTEGER": "integer",
              "NUMBER": "number", "BOOLEAN": "boolean", "ARRAY": "array"}


def _build_gemini_tools(registry: Dict[str, Dict[str, Any]]):
    import ai_vertex as av
    specs = []
    for name, entry in registry.items():
        params_def = entry.get("params") or {}
        properties = {}
        for pname, pdef in params_def.items():
            ptype = (pdef.get("type_") or pdef.get("type") or "STRING").upper()
            properties[pname] = {"type": _JSON_TYPE.get(ptype, "string"),
                                 "description": pdef.get("description", "")}
        spec: Dict[str, Any] = {"name": name, "description": entry["desc"]}
        if properties:
            spec["parameters"] = {"type": "object", "properties": properties}
        specs.append(spec)
    return av.make_tools(specs)


def _call_gemini_with_tools(
    system: str,
    history: List[Dict[str, str]],
    user_msg: str,
    registry: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    tools_called: List[str] = []
    try:
        import ai_vertex as av
        tools = _build_gemini_tools(registry)
        model = av.make_model(
            "gemini-2.5-flash",
            system_instruction=system,
            generation_config={"temperature": 0.3, "max_output_tokens": 4096},
            tools=tools,
        )
        turns = []
        for m in history:
            role = "model" if m.get("role") == "assistant" else "user"
            turns.append((role, m.get("content", "")))
        chat = model.start_chat(history=av.make_history(turns))

        resp = av.send_message(chat, user_msg)
        text_chunks: List[str] = []
        max_loops = 4

        for _ in range(max_loops):
            function_calls: List[tuple] = []
            for cand in (getattr(resp, "candidates", None) or []):
                content = getattr(cand, "content", None)
                for p in (getattr(content, "parts", None) or []):
                    fc = getattr(p, "function_call", None)
                    if fc and getattr(fc, "name", ""):
                        args = _proto_to_py(getattr(fc, "args", {})) or {}
                        function_calls.append((fc.name, args if isinstance(args, dict) else {}))
                    t = getattr(p, "text", None)
                    if t:
                        text_chunks.append(t)

            if not function_calls:
                break

            response_parts = []
            for name, args in function_calls:
                tools_called.append(name)
                entry = registry.get(name)
                if not entry:
                    payload = {"error": f"Unknown tool {name}"}
                else:
                    try:
                        payload = entry["run"](**(args or {}))
                    except TypeError:
                        try:
                            payload = entry["run"]()
                        except Exception as ex:
                            payload = {"error": str(ex)}
                    except Exception as ex:
                        payload = {"error": str(ex)}
                response_parts.append(av.function_response_part(name, payload))
            resp = av.send_message(chat, response_parts)

        final_text = "\n".join(text_chunks).strip()
        if not final_text:
            try:
                final_text = (resp.text or "").strip()
            except Exception:
                pass
        if not final_text:
            final_text = "I couldn't generate a response — could you rephrase your question?"
        return {"content": final_text, "tools_called": tools_called}

    except Exception as e:
        logger.error("[Tarrigon] Gemini error: %s", e, exc_info=True)
        return {"content": f"Tarrigon encountered an error: {e}",
                "tools_called": tools_called, "error": str(e)}


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/chat")
def chat(
    body: ChatRequest,
    current_user: models.People = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not body.messages:
        raise HTTPException(400, "messages is required.")
    user_msg = (body.messages[-1].content or "").strip()
    if not user_msg:
        raise HTTPException(400, "Last message is empty.")
    if len(user_msg) > MAX_MESSAGE_CHARS:
        raise HTTPException(413, f"Message too long (max {MAX_MESSAGE_CHARS} chars).")

    if body.business_id:
        _check_business_access(db, current_user.PeopleID, body.business_id, min_level=1)

    rag = _rag_search(user_msg)
    registry = _build_tool_registry(body.business_id, db)
    history = _load_recent_messages(current_user.PeopleID, body.business_id or 0)
    system = _system_prompt(rag, body.page or "", list(registry.keys()))
    result = _call_gemini_with_tools(system, history, user_msg, registry)
    reply = result["content"]

    if body.business_id:
        _save_message(current_user.PeopleID, body.business_id, "user", user_msg)
        _save_message(current_user.PeopleID, body.business_id, "assistant", reply)

    return {
        "content": result["content"],
        "tools_called": result.get("tools_called", []),
        "rag_hit": bool(rag),
    }


@router.get("/health")
def health():
    out: Dict[str, Any] = {"agent": AGENT_NAME, "ok": True}
    fs = _firestore()
    out["firestore"] = "up" if fs else "down"
    out["gemini_api_key"] = "set" if os.getenv("GOOGLE_API_KEY", "").strip() else "missing"
    out["rag_collection"] = TARRIGON_RAG_COLLECTION
    out["chats_collection"] = TARRIGON_CHATS_COLLECTION
    return out


@router.get("/suggestions")
def suggestions(
    business_id: Optional[int] = Query(None),
    page: Optional[str] = Query(None),
    current_user: models.People = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if business_id:
        _check_business_access(db, current_user.PeopleID, business_id, min_level=1)
    page_lc = (page or "").lower()
    if "exception" in page_lc:
        chips = [
            "Show me all critical exceptions.",
            "Which quality failures are still open?",
            "Summarize today's supply chain alerts.",
            "Any temperature breach exceptions?",
        ]
    elif "quality" in page_lc:
        chips = [
            "What's our quality pass rate this month?",
            "Which supplier has the most failures?",
            "Show me lots with defect % above 10.",
            "How does quality compare to last month?",
        ]
    elif "margin" in page_lc:
        chips = [
            "What's our average margin across all products?",
            "Which product lines are below 15% margin?",
            "Show margin breakdown by category.",
            "Where are we losing the most margin?",
        ]
    elif "forecast" in page_lc:
        chips = [
            "Are there any demand-supply gaps in the next 4 weeks?",
            "Which products are at risk of shortfall?",
            "Show me upcoming harvest forecasts.",
            "Compare demand forecast vs actual for this month.",
        ]
    else:
        chips = [
            "Give me a supply chain overview.",
            "Any open exceptions I should know about?",
            "What's our overall quality pass rate?",
            "Which shipments are overdue?",
        ]
    return {"suggestions": chips}


@router.get("/history")
def history(
    business_id: Optional[int] = Query(None),
    current_user: models.People = Depends(get_current_user),
):
    return {"messages": _load_recent_messages(current_user.PeopleID, business_id or 0)}


@router.delete("/history")
def clear_history(
    business_id: Optional[int] = Query(None),
    current_user: models.People = Depends(get_current_user),
):
    ok = _delete_thread(current_user.PeopleID, business_id or 0)
    return {"ok": ok}
