"""
routers/supplier_scorecard.py
Supplier performance scoring: on-time delivery rate, spend analytics, PO volume.
Data sourced from PurchaseOrder, POReceipt, and PackhouseInspection.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
from typing import Optional

router = APIRouter(prefix="/api/supplier-scorecard", tags=["supplier_scorecard"])


def _score(on_time_pct, avg_days_late):
    """Composite score 0-100: 70% on-time rate, 30% lateness penalty."""
    if on_time_pct is None:
        return 50  # unknown
    base = on_time_pct * 0.7 + 30
    if avg_days_late and avg_days_late > 0:
        base -= min(avg_days_late * 1.5, 20)
    return int(min(100, max(0, round(base))))


@router.get("/vendors")
def list_vendor_scores(business_id: int = Query(...), db: Session = Depends(get_db)):
    """Per-vendor scorecard from PurchaseOrders + receipts."""
    rows = db.execute(text("""
        SELECT
            po.SupplierName,
            COUNT(DISTINCT po.POID)                                              AS TotalPOs,
            ISNULL(SUM(po.TotalAmount), 0)                                       AS TotalSpend,
            SUM(CASE WHEN po.Status IN ('received','closed') THEN 1 ELSE 0 END) AS ReceivedPOs,
            SUM(CASE WHEN po.Status = 'pending_approval'     THEN 1 ELSE 0 END) AS PendingApproval,
            MAX(po.OrderDate)                                                    AS LastOrderDate,
            SUM(CASE WHEN r.ReceivedDate IS NOT NULL
                          AND po.ExpectedDelivery IS NOT NULL
                          AND r.ReceivedDate <= po.ExpectedDelivery
                     THEN 1 ELSE 0 END)                                          AS OnTimeCount,
            SUM(CASE WHEN r.ReceivedDate IS NOT NULL
                     THEN 1 ELSE 0 END)                                          AS TotalReceived,
            AVG(CASE WHEN r.ReceivedDate IS NOT NULL
                          AND po.ExpectedDelivery IS NOT NULL
                     THEN DATEDIFF(day, po.ExpectedDelivery, r.ReceivedDate)
                     ELSE NULL END)                                              AS AvgDaysLate
        FROM PurchaseOrder po
        LEFT JOIN POReceipt r ON r.POID = po.POID
        WHERE po.BusinessID = :bid
        GROUP BY po.SupplierName
        ORDER BY TotalSpend DESC
    """), {"bid": business_id}).fetchall()

    result = []
    for r in rows:
        m = dict(r._mapping)
        total_recv = m.get("TotalReceived") or 0
        on_time = m.get("OnTimeCount") or 0
        on_time_pct = round(on_time / total_recv * 100, 1) if total_recv > 0 else None
        avg_late = m.get("AvgDaysLate")
        if avg_late is not None:
            avg_late = int(avg_late)
        result.append({
            "supplier_name": m["SupplierName"],
            "total_pos": m["TotalPOs"],
            "total_spend": float(m["TotalSpend"] or 0),
            "received_pos": m.get("ReceivedPOs", 0),
            "pending_approval": m.get("PendingApproval", 0),
            "last_order_date": str(m["LastOrderDate"])[:10] if m.get("LastOrderDate") else None,
            "on_time_pct": on_time_pct,
            "avg_days_late": avg_late,
            "score": _score(on_time_pct, avg_late),
        })
    return result


@router.get("/summary")
def scorecard_summary(business_id: int = Query(...), db: Session = Depends(get_db)):
    """Aggregate procurement health metrics."""
    r = db.execute(text("""
        SELECT
            COUNT(DISTINCT po.SupplierName)                                      AS VendorCount,
            COUNT(DISTINCT po.POID)                                              AS TotalPOs,
            ISNULL(SUM(po.TotalAmount), 0)                                       AS TotalSpend,
            SUM(CASE WHEN po.Status = 'pending_approval'     THEN 1 ELSE 0 END) AS PendingApproval,
            SUM(CASE WHEN r.ReceivedDate IS NOT NULL
                          AND po.ExpectedDelivery IS NOT NULL
                          AND r.ReceivedDate <= po.ExpectedDelivery
                     THEN 1 ELSE 0 END)                                          AS OnTimeCount,
            SUM(CASE WHEN r.ReceivedDate IS NOT NULL
                     THEN 1 ELSE 0 END)                                          AS TotalReceived
        FROM PurchaseOrder po
        LEFT JOIN POReceipt r ON r.POID = po.POID
        WHERE po.BusinessID = :bid
    """), {"bid": business_id}).fetchone()
    m = dict(r._mapping) if r else {}
    total_recv = m.get("TotalReceived") or 0
    on_time = m.get("OnTimeCount") or 0
    return {
        "vendor_count": m.get("VendorCount", 0),
        "total_pos": m.get("TotalPOs", 0),
        "total_spend": float(m.get("TotalSpend") or 0),
        "pending_approval": m.get("PendingApproval", 0),
        "on_time_pct": round(on_time / total_recv * 100, 1) if total_recv > 0 else None,
    }


@router.get("/vendor/{supplier_name}")
def vendor_detail(supplier_name: str, business_id: int = Query(...),
                  db: Session = Depends(get_db)):
    """PO history for one supplier."""
    rows = db.execute(text("""
        SELECT po.POID, po.PONumber, po.OrderDate, po.ExpectedDelivery,
               po.TotalAmount, po.Status, po.Currency,
               r.ReceivedDate,
               CASE WHEN r.ReceivedDate IS NOT NULL AND po.ExpectedDelivery IS NOT NULL
                    THEN DATEDIFF(day, po.ExpectedDelivery, r.ReceivedDate)
                    ELSE NULL END AS DaysLate
        FROM PurchaseOrder po
        LEFT JOIN POReceipt r ON r.POID = po.POID
        WHERE po.BusinessID=:bid AND po.SupplierName=:sn
        ORDER BY po.OrderDate DESC
    """), {"bid": business_id, "sn": supplier_name}).fetchall()
    return [{
        "po_id": r.POID,
        "po_number": r.PONumber,
        "order_date": str(r.OrderDate)[:10] if r.OrderDate else None,
        "expected_delivery": str(r.ExpectedDelivery)[:10] if r.ExpectedDelivery else None,
        "received_date": str(r.ReceivedDate)[:10] if r.ReceivedDate else None,
        "total_amount": float(r.TotalAmount or 0),
        "status": r.Status,
        "currency": r.Currency,
        "days_late": int(r.DaysLate) if r.DaysLate is not None else None,
        "on_time": (r.DaysLate is not None and r.DaysLate <= 0) if r.ReceivedDate else None,
    } for r in rows]
