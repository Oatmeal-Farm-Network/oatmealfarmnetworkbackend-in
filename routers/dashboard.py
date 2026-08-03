from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/biz-summary")
@router.get("/summary")
def dashboard_summary(business_id: int = Query(...), db: Session = Depends(get_db)):
    try:
        row = db.execute(
            text("""
                SELECT
                  (SELECT COUNT(*) FROM Field               WHERE BusinessID=:b)                                                                           AS fields,
                  (SELECT COUNT(*) FROM Animals             WHERE BusinessID=:b)                                                                           AS animals,
                  (SELECT COUNT(*) FROM MarketplaceOrderItems WHERE SellerBusinessID=:b AND SellerStatus IN ('pending','confirmed','processing'))           AS pending_orders,
                  (SELECT COUNT(*) FROM OFNEvents WHERE BusinessID=:b AND IsPublished=1 AND (EventStartDate IS NULL OR EventStartDate >= CAST(GETDATE() AS DATE))) AS upcoming_events,
                  (SELECT COUNT(*) FROM blog                WHERE BusinessID=:b AND IsPublished=1)                                                         AS blog_posts,
                  (SELECT COUNT(*) FROM SFProducts          WHERE BusinessID=:b AND Publishproduct=1)                                                      AS products,
                  (SELECT COUNT(*) FROM Services            WHERE BusinessID=:b)                                                                           AS services,
                  (SELECT COUNT(*) FROM Produce             WHERE BusinessID=:b AND IsActive=1)                                                            AS produce,
                  (CASE WHEN EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='OFNAggregatorB2BOrder')
                        THEN (SELECT COUNT(*) FROM OFNAggregatorB2BOrder WHERE BusinessID=:b AND Status IN ('placed','confirmed','picking','dispatched'))
                        ELSE 0 END)                                                                                                                        AS aggregator_b2b_open,
                  (CASE WHEN EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='OFNAggregatorFarm')
                        THEN (SELECT COUNT(*) FROM OFNAggregatorFarm WHERE BusinessID=:b AND Status='active')
                        ELSE 0 END)                                                                                                                        AS aggregator_farms
            """),
            {"b": business_id},
        ).fetchone()
    except Exception:
        row = None

    if row is None:
        return {"fields": 0, "animals": 0, "pending_orders": 0, "upcoming_events": 0,
                "blog_posts": 0, "products": 0, "services": 0, "produce": 0,
                "aggregator_b2b_open": 0, "aggregator_farms": 0}

    return {
        "fields":              row.fields              or 0,
        "animals":             row.animals             or 0,
        "pending_orders":      row.pending_orders      or 0,
        "upcoming_events":     row.upcoming_events     or 0,
        "blog_posts":          row.blog_posts          or 0,
        "products":            row.products            or 0,
        "services":            row.services            or 0,
        "produce":             row.produce             or 0,
        "aggregator_b2b_open": row.aggregator_b2b_open or 0,
        "aggregator_farms":    row.aggregator_farms    or 0,
    }
