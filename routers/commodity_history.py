# routers/commodity_history.py
# Time-series storage for live commodity prices submitted via /api/market-alerts/check.
# Exposes a trend endpoint for Market Intelligence sparklines and Saige analysis tools.

from fastapi import APIRouter, Depends, Query, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, engine, SessionLocal
from typing import Optional
from datetime import datetime, timedelta
from collections import defaultdict
import requests as _req
from requests.adapters import HTTPAdapter
import ssl
import urllib3
import logging

_log = logging.getLogger(__name__)

# ── Yahoo Finance futures quote cache (5-min TTL) ─────────────────────────────
_YF_SYMBOLS = ["ZC=F", "ZS=F", "ZW=F", "LE=F", "GF=F", "HE=F", "DC=F", "CT=F"]
_YF_CACHE: dict = {}          # symbol -> quote dict
_YF_CACHE_AT: datetime | None = None
_YF_TTL = timedelta(minutes=5)
_STOOQ_SYMBOLS = ["zc.f", "zs.f", "zw.f", "le.f", "gf.f", "he.f", "dc.f", "ct.f"]
# map stooq symbol -> canonical YF-style key
_STOOQ_TO_KEY = {s: s.upper().replace(".F", "=F") for s in _STOOQ_SYMBOLS}
_STOOQ_HEADERS = {"User-Agent": "Mozilla/5.0"}

def _fetch_via_yfinance() -> dict:
    """Try yfinance library (handles Yahoo Finance crumb auth automatically)."""
    import yfinance as yf  # imported lazily — not always installed
    out = {}
    tickers = yf.Tickers(" ".join(_YF_SYMBOLS))
    for sym, t in tickers.tickers.items():
        try:
            fi = t.fast_info
            price = fi.last_price
            prev  = fi.previous_close
            if not price:
                continue
            change = round((price - prev) if prev else 0.0, 4)
            pct    = round(change / prev * 100 if prev else 0.0, 2)
            out[sym] = {
                "price":  round(float(price), 4),
                "change": change,
                "pct":    pct,
                "prev":   round(float(prev or 0), 4),
                "name":   sym,
            }
        except Exception:
            pass
    return out

def _fetch_via_stooq() -> dict:
    """Fallback: Stooq CSV. Change = Close - Open (open ≈ prev settlement for futures)."""
    out = {}
    symbols_str = ",".join(_STOOQ_SYMBOLS)
    try:
        r = _req.get(
            f"https://stooq.com/q/l/?s={symbols_str}&f=sd2t2ohlcv&h&e=csv",
            headers=_STOOQ_HEADERS, timeout=8,
        )
        if not r.ok:
            return out
        lines = r.text.strip().splitlines()
        for line in lines[1:]:   # skip header
            parts = line.split(",")
            if len(parts) < 7:
                continue
            sym_raw = parts[0].strip().upper()
            key = _STOOQ_TO_KEY.get(sym_raw.lower(), sym_raw.replace(".F", "=F"))
            try:
                open_p  = float(parts[3])
                close_p = float(parts[6])
                change  = round(close_p - open_p, 4)
                pct     = round(change / open_p * 100 if open_p else 0.0, 2)
                out[key] = {
                    "price":  round(close_p, 4),
                    "change": change,
                    "pct":    pct,
                    "prev":   round(open_p, 4),
                    "name":   key,
                }
            except (ValueError, IndexError):
                pass
    except Exception as e:
        _log.warning(f"[commodity_history] Stooq fetch error: {e}")
    return out

def _fetch_yf_quotes() -> dict:
    global _YF_CACHE, _YF_CACHE_AT
    out: dict = {}
    try:
        out = _fetch_via_yfinance()
    except Exception as e:
        _log.info(f"[commodity_history] yfinance unavailable ({e}), trying Stooq")
    if not out:
        out = _fetch_via_stooq()
    if out:
        _YF_CACHE = out
        _YF_CACHE_AT = datetime.utcnow()
    return _YF_CACHE

# marketnews.usda.gov uses an older TLS config that triggers TLSV1_UNRECOGNIZED_NAME
# when the standard SNI path is used. A session with check_hostname=False fixes it.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class _NoSNIAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs['ssl_context'] = ctx
        super().init_poolmanager(*args, **kwargs)

_fv_session = _req.Session()
_fv_session.mount('https://www.marketnews.usda.gov', _NoSNIAdapter())

# ── USDA AMS commodity definitions ────────────────────────────────────────────
# Livestock/poultry (Market Livestock Reporter — mpr.datamart.ams.usda.gov)
_MLR_COMMODITIES = [
    {"key": "Nat'l Chicken Breast", "report": "LM_PY0305", "match": "Boneless Skinless"},
    {"key": "Nat'l Pork Loin",      "report": "LM_PK602",  "match": "Pork Loin"},
]

# Specialty produce (USDA AMS Market News fruit-and-vegetable terminal reports)
# Uses the National Retail Report (marketnews.usda.gov) JSON endpoint.
_FV_COMMODITIES = [
    {"key": "Strawberries",    "commName": "STRAWBERRIES",    "repType": "termMktAvgPriceList"},
    {"key": "Blueberries",     "commName": "BLUEBERRIES",     "repType": "termMktAvgPriceList"},
    {"key": "Microgreens",     "commName": "MICRO GREENS",    "repType": "termMktAvgPriceList"},
    {"key": "Mixed Greens",    "commName": "SALAD MIX",       "repType": "termMktAvgPriceList"},
    {"key": "Roma Tomatoes",   "commName": "TOMATOES",        "repType": "termMktAvgPriceList"},
]

_MLR_BASE = "https://mpr.datamart.ams.usda.gov/services/public/LMR/Report"
_FV_BASE  = "https://www.marketnews.usda.gov/mnp/fv-report-top-filters"

router = APIRouter(prefix="/api/commodity-prices", tags=["commodity_history"])

with engine.begin() as _conn:
    _conn.execute(text("""
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='CommodityPriceHistory')
        BEGIN
            CREATE TABLE CommodityPriceHistory (
                HistoryID   INT IDENTITY(1,1) PRIMARY KEY,
                Commodity   VARCHAR(80)   NOT NULL,
                PriceUSD    DECIMAL(12,4) NOT NULL,
                FetchedAt   DATETIME      NOT NULL DEFAULT GETDATE()
            )
            CREATE INDEX IX_CommodityHistory_Commodity
                ON CommodityPriceHistory (Commodity, FetchedAt DESC)
        END
    """))


def _fetch_and_store_prices() -> dict:
    """Fetch live commodity prices from USDA AMS and insert into CommodityPriceHistory.
    Called by the /fetch endpoint (Cloud Scheduler) and auto-triggered on stale data."""
    stored = {}
    try:
        # Livestock / poultry via Market Livestock Reporter
        for c in _MLR_COMMODITIES:
            try:
                r = _req.get(f"{_MLR_BASE}?Report_ID={c['report']}&key=&q=", timeout=10)
                if not r.ok:
                    continue
                data = r.json()
                results = data.get("results") or []
                row = next((x for x in results if c["match"].lower() in (x.get("label") or "").lower()), results[0] if results else None)
                if not row:
                    continue
                price = float(row.get("price") or row.get("avg_price") or 0)
                if price <= 0:
                    continue
                with SessionLocal() as db:
                    db.execute(text("INSERT INTO CommodityPriceHistory (Commodity, PriceUSD) VALUES (:c, :p)"),
                               {"c": c["key"], "p": price})
                    db.commit()
                stored[c["key"]] = price
            except Exception as e:
                _log.warning(f"[commodity_history] MLR fetch error for {c['key']}: {e}")

        # Specialty produce via USDA FV Market News
        for c in _FV_COMMODITIES:
            try:
                r = _fv_session.get(_FV_BASE, params={
                    "startIndex": 1, "type": "terminal", "repType": c["repType"],
                    "run": "Run", "format": "json", "commodity": c["commName"],
                    "organic": "N",
                }, timeout=10)
                if not r.ok:
                    continue
                data = r.json()
                items = data.get("Result") or data.get("results") or []
                if not items:
                    continue
                # Average the first few price rows
                prices = []
                for item in items[:5]:
                    p = item.get("avgPrice") or item.get("AvgPrice") or item.get("price") or 0
                    try:
                        prices.append(float(str(p).replace("$", "").strip()))
                    except (ValueError, TypeError):
                        pass
                if not prices:
                    continue
                avg = sum(prices) / len(prices)
                with SessionLocal() as db:
                    db.execute(text("INSERT INTO CommodityPriceHistory (Commodity, PriceUSD) VALUES (:c, :p)"),
                               {"c": c["key"], "p": round(avg, 4)})
                    db.commit()
                stored[c["key"]] = round(avg, 4)
            except Exception as e:
                _log.warning(f"[commodity_history] FV fetch error for {c['key']}: {e}")

    except Exception as e:
        _log.error(f"[commodity_history] _fetch_and_store_prices error: {e}")

    return stored


@router.post("/fetch")
def fetch_prices(background_tasks: BackgroundTasks):
    """Trigger a live USDA price fetch and persist to history.
    Called daily by Cloud Scheduler — no auth required (internal webhook).
    Returns immediately; fetch runs in background."""
    background_tasks.add_task(_fetch_and_store_prices)
    return {"ok": True, "message": "Price fetch queued"}


@router.get("/history")
def get_price_history(
    commodity: Optional[str] = None,
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = None,
):
    """Returns price data points per commodity over the last N days with trend stats.
    No auth required — prices are aggregate market data, not user-specific.
    Auto-fetches from USDA if no data exists for the last 24 hours (cold-start)."""
    since = datetime.utcnow() - timedelta(days=days)

    # Cold-start: if the table has no recent data, kick off a fetch synchronously
    recent = db.execute(text(
        "SELECT TOP 1 1 FROM CommodityPriceHistory WHERE FetchedAt >= DATEADD(hour, -24, GETDATE())"
    )).scalar()
    if not recent:
        background_tasks.add_task(_fetch_and_store_prices)

    if commodity:
        rows = db.execute(text("""
            SELECT Commodity, PriceUSD, FetchedAt
            FROM CommodityPriceHistory
            WHERE Commodity = :c AND FetchedAt >= :since
            ORDER BY FetchedAt ASC
        """), {"c": commodity, "since": since}).mappings().all()
    else:
        rows = db.execute(text("""
            SELECT Commodity, PriceUSD, FetchedAt
            FROM CommodityPriceHistory
            WHERE FetchedAt >= :since
            ORDER BY Commodity, FetchedAt ASC
        """), {"since": since}).mappings().all()

    by_commodity: dict = defaultdict(list)
    for r in rows:
        ts = r["FetchedAt"]
        by_commodity[r["Commodity"]].append({
            "price": float(r["PriceUSD"]),
            "at": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
        })

    result = {}
    for comm, pts in by_commodity.items():
        prices = [p["price"] for p in pts]
        first, last = prices[0], prices[-1]
        pct = round((last - first) / first * 100, 2) if first else None
        result[comm] = {
            "points": pts,
            "latest": last,
            "avg_7d":  round(sum(prices[-7:]) / len(prices[-7:]), 4) if prices else None,
            "avg_30d": round(sum(prices) / len(prices), 4) if prices else None,
            "pct_change": pct,
            "trend": "rising" if pct and pct > 2 else ("falling" if pct and pct < -2 else "stable"),
        }
    return result


@router.get("/quotes")
def get_futures_quotes():
    """Live delayed futures quotes from Yahoo Finance for 8 ag commodities.
    Cached for 5 minutes server-side. No auth required."""
    now = datetime.utcnow()
    if not _YF_CACHE or not _YF_CACHE_AT or (now - _YF_CACHE_AT) > _YF_TTL:
        _fetch_yf_quotes()
    return {
        "quotes": _YF_CACHE,
        "fetched_at": _YF_CACHE_AT.isoformat() if _YF_CACHE_AT else None,
        "stale": bool(_YF_CACHE_AT and (now - _YF_CACHE_AT) > _YF_TTL),
    }
