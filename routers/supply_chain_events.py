"""
ESCI — SSE exception stream.

GET /api/esci/stream/exceptions?business_id=&since=
Streams new open exceptions as they are created, polling the DB every 10s.
Used by SupplyChainExceptions.jsx to show a live feed.
"""
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
import asyncio
import json
import datetime

router = APIRouter(prefix="/api/esci", tags=["supply_chain_events"])


def _row_to_json(row) -> str:
    d = dict(row._mapping)
    for k, v in d.items():
        if hasattr(v, 'isoformat'):
            d[k] = v.isoformat()
        elif hasattr(v, '__float__'):
            try:
                d[k] = float(v)
            except Exception:
                pass
    return json.dumps(d)


async def _exception_generator(business_id: int, since: str, db: Session):
    try:
        since_dt = datetime.datetime.fromisoformat(since.replace("Z", "+00:00"))
    except Exception:
        since_dt = datetime.datetime.utcnow()

    cutoff = since_dt.isoformat()
    max_polls = 60  # 10 min @ 10s interval, then close

    for _ in range(max_polls):
        try:
            rows = db.execute(text("""
                SELECT TOP 20
                       e.ExceptionID, e.ExceptionType, e.Severity, e.Status,
                       e.Title, e.Detail, e.DetectedAt, e.AssignedTo,
                       sp.SupplierName, s.ProductName AS ShipmentProduct, s.ShipmentRef
                  FROM ESCI_Exception e
                  LEFT JOIN ESCI_SupplierProfile sp ON sp.SupplierID = e.SupplierID
                  LEFT JOIN ESCI_Shipment s ON s.ShipmentID = e.ShipmentID
                 WHERE e.BusinessID = :bid
                   AND e.DetectedAt > :since
                 ORDER BY e.DetectedAt ASC
            """), {"bid": business_id, "since": cutoff}).fetchall()

            for row in rows:
                d = dict(row._mapping)
                for k, v in d.items():
                    if hasattr(v, 'isoformat'):
                        d[k] = v.isoformat()
                    elif hasattr(v, '__float__'):
                        try:
                            d[k] = float(v)
                        except Exception:
                            pass
                if d.get("DetectedAt"):
                    cutoff = d["DetectedAt"]
                yield f"data: {json.dumps(d)}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

        yield ": heartbeat\n\n"
        await asyncio.sleep(10)

    yield "data: {\"stream\": \"closed\"}\n\n"


@router.get("/stream/exceptions")
def stream_exceptions(
    business_id: int = Query(...),
    since: str = Query(default=""),
    db: Session = Depends(get_db),
):
    """Server-Sent Events stream of new ESCI exceptions."""
    if not since:
        since = datetime.datetime.utcnow().isoformat()
    return StreamingResponse(
        _exception_generator(business_id, since, db),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
