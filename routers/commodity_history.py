# routers/commodity_history.py
# Commodity price history + live quotes.
# India deploy: mandi modal prices via farmer.in (Agmarknet / GoI).
# Optional: set COMMODITY_MARKET=us to keep USDA/Yahoo behavior.

from fastapi import APIRouter, Query, BackgroundTasks, Header, HTTPException
from sqlalchemy import text
from database import engine, SessionLocal
from typing import Optional
from datetime import datetime, timedelta
from collections import defaultdict
import os
import requests as _req
from requests.adapters import HTTPAdapter
import ssl
import urllib3
import logging

_log = logging.getLogger(__name__)

# india (default for India repo) | us
_MARKET = (os.getenv("COMMODITY_MARKET") or "india").strip().lower()

# ── India mandi cache ─────────────────────────────────────────────────────────
_MANDI_URL = os.getenv(
    "INDIA_MANDI_PRICES_URL",
    "https://farmer.in/api/open/prices.json",
)
_MANDI_CACHE: dict = {}          # id -> quote dict (API shape)
_MANDI_RAW: list = []            # full commodity objects for /mandi
_MANDI_CACHE_AT: datetime | None = None
_MANDI_META: dict = {}
_MANDI_TTL = timedelta(minutes=30)

# Priority staples shown first on the India commodity page
_INDIA_PRIORITY = [
    "wheat", "rice", "maize", "bajra", "jowar", "ragi",
    "tur", "moong", "urad", "chana", "masur",
    "soybean", "groundnut", "mustard", "sunflower",
    "cotton", "sugarcane",
    "onion", "potato", "tomato", "chilli", "turmeric",
]

# ── Yahoo Finance futures quote cache (US mode) ───────────────────────────────
_YF_SYMBOLS = ["ZC=F", "ZS=F", "ZW=F", "LE=F", "GF=F", "HE=F", "DC=F", "CT=F"]
_YF_CACHE: dict = {}
_YF_CACHE_AT: datetime | None = None
_YF_TTL = timedelta(minutes=5)
_STOOQ_SYMBOLS = ["zc.f", "zs.f", "zw.f", "le.f", "gf.f", "he.f", "dc.f", "ct.f"]
_STOOQ_TO_KEY = {s: s.upper().replace(".F", "=F") for s in _STOOQ_SYMBOLS}
_STOOQ_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; OFN-India/1.0)"}

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class _NoSNIAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(*args, **kwargs)


_fv_session = _req.Session()
_fv_session.mount("https://www.marketnews.usda.gov", _NoSNIAdapter())

_MLR_COMMODITIES = [
    {"key": "Nat'l Chicken Breast", "report": "LM_PY0305", "match": "Boneless Skinless"},
    {"key": "Nat'l Pork Loin", "report": "LM_PK602", "match": "Pork Loin"},
]
_FV_COMMODITIES = [
    {"key": "Strawberries", "commName": "STRAWBERRIES", "repType": "termMktAvgPriceList"},
    {"key": "Blueberries", "commName": "BLUEBERRIES", "repType": "termMktAvgPriceList"},
    {"key": "Microgreens", "commName": "MICRO GREENS", "repType": "termMktAvgPriceList"},
    {"key": "Mixed Greens", "commName": "SALAD MIX", "repType": "termMktAvgPriceList"},
    {"key": "Roma Tomatoes", "commName": "TOMATOES", "repType": "termMktAvgPriceList"},
]
_MLR_BASE = "https://mpr.datamart.ams.usda.gov/services/public/LMR/Report"
_FV_BASE = "https://www.marketnews.usda.gov/mnp/fv-report-top-filters"

router = APIRouter(prefix="/api/commodity-prices", tags=["commodity_history"])

try:
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
except Exception as _e:
    print(f"CommodityPriceHistory table setup error: {_e}")


def _norm_mandi_item(item: dict) -> dict | None:
    """Normalize farmer.in commodity object → quote + catalog fields."""
    if not isinstance(item, dict):
        return None
    cid = (item.get("id") or "").strip()
    name = (item.get("name") or cid or "").strip()
    if not cid or not name:
        return None
    try:
        price = float(item.get("price") or 0)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    try:
        change = float(item.get("change") or 0)
    except (TypeError, ValueError):
        change = 0.0
    prev = price - change
    pct = round(change / prev * 100, 2) if prev else 0.0
    try:
        msp = float(item["msp"]) if item.get("msp") is not None else None
    except (TypeError, ValueError):
        msp = None
    try:
        pmin = float(item["min"]) if item.get("min") is not None else None
        pmax = float(item["max"]) if item.get("max") is not None else None
    except (TypeError, ValueError):
        pmin = pmax = None

    return {
        "id": cid,
        "name": name,
        "hindi": item.get("hindi") or "",
        "icon": item.get("icon") or "🌾",
        "category": item.get("category") or "Other",
        "unit": item.get("unit") or "quintal",
        "currency": "INR",
        "price": round(price, 2),
        "change": round(change, 2),
        "pct": pct,
        "prev": round(prev, 2),
        "min": pmin,
        "max": pmax,
        "msp": msp,
        "msp_season": item.get("msp_season"),
        "season": item.get("season"),
        "major_states": item.get("major_states") or [],
        "trend": item.get("trend") or ("up" if change > 0 else ("down" if change < 0 else "flat")),
        "updated": item.get("updated"),
        "url": f"https://agmarknet.gov.in/",
    }


def _fetch_mandi_feed(force: bool = False) -> dict:
    """Fetch + cache farmer.in mandi JSON. Returns quotes keyed by commodity id."""
    global _MANDI_CACHE, _MANDI_RAW, _MANDI_CACHE_AT, _MANDI_META
    now = datetime.utcnow()
    if (
        not force
        and _MANDI_CACHE
        and _MANDI_CACHE_AT
        and (now - _MANDI_CACHE_AT) <= _MANDI_TTL
    ):
        return _MANDI_CACHE

    try:
        r = _req.get(
            _MANDI_URL,
            timeout=20,
            headers={"User-Agent": "OFN-India/1.0", "Accept": "application/json"},
        )
        r.raise_for_status()
        payload = r.json()
    except Exception as e:
        _log.warning(f"[commodity_history] mandi feed error: {e}")
        return _MANDI_CACHE

    commodities = payload.get("commodities") or []
    quotes = {}
    raw = []
    for item in commodities:
        norm = _norm_mandi_item(item)
        if not norm:
            continue
        raw.append(norm)
        quotes[norm["id"]] = {
            "price": norm["price"],
            "change": norm["change"],
            "pct": norm["pct"],
            "prev": norm["prev"],
            "name": norm["name"],
            "unit": norm["unit"],
            "currency": "INR",
            "hindi": norm["hindi"],
            "icon": norm["icon"],
            "category": norm["category"],
            "msp": norm["msp"],
            "min": norm["min"],
            "max": norm["max"],
        }

    if quotes:
        _MANDI_CACHE = quotes
        _MANDI_RAW = raw
        _MANDI_CACHE_AT = now
        _MANDI_META = {
            "source": payload.get("source") or "farmer.in",
            "attribution": payload.get("attribution")
            or "Agmarknet / Government of India via farmer.in",
            "license": payload.get("license"),
            "updated": payload.get("updated"),
            "website": payload.get("website") or "https://farmer.in",
        }
        _log.info(f"[commodity_history] mandi feed loaded: {len(quotes)} commodities")
    return _MANDI_CACHE


def _store_mandi_history(quotes: dict) -> dict:
    """Insert mandi modal prices into history (PriceUSD holds INR).

    Only stores priority staples to avoid flooding the table with 100+ rows
    on every scheduler tick. Skips insert when today's last price matches.
    """
    stored = {}
    if not quotes:
        return stored
    priority = set(_INDIA_PRIORITY)
    try:
        with SessionLocal() as db:
            for cid, q in quotes.items():
                if priority and cid not in priority:
                    continue
                label = (q.get("name") or cid)[:80]
                price = float(q.get("price") or 0)
                if price <= 0:
                    continue
                # Dedup: skip if same rounded price already stored today
                exists = db.execute(
                    text(
                        """
                        SELECT TOP 1 PriceUSD FROM CommodityPriceHistory
                        WHERE Commodity = :c AND FetchedAt >= CAST(GETDATE() AS DATE)
                        ORDER BY FetchedAt DESC
                        """
                    ),
                    {"c": label},
                ).scalar()
                if exists is not None and abs(float(exists) - price) < 0.01:
                    stored[label] = float(exists)
                    continue
                db.execute(
                    text(
                        "INSERT INTO CommodityPriceHistory (Commodity, PriceUSD) "
                        "VALUES (:c, :p)"
                    ),
                    {"c": label, "p": price},
                )
                stored[label] = price
            db.commit()
    except Exception as e:
        _log.error(f"[commodity_history] mandi history store error: {e}")
    return stored


def _fetch_via_yfinance() -> dict:
    import yfinance as yf
    out = {}
    tickers = yf.Tickers(" ".join(_YF_SYMBOLS))
    for sym, t in tickers.tickers.items():
        try:
            fi = t.fast_info
            price = fi.last_price
            prev = fi.previous_close
            if not price:
                continue
            change = round((price - prev) if prev else 0.0, 4)
            pct = round(change / prev * 100 if prev else 0.0, 2)
            out[sym] = {
                "price": round(float(price), 4),
                "change": change,
                "pct": pct,
                "prev": round(float(prev or 0), 4),
                "name": sym,
            }
        except Exception:
            pass
    return out


def _fetch_via_stooq() -> dict:
    out = {}
    symbols_str = ",".join(_STOOQ_SYMBOLS)
    try:
        r = _req.get(
            f"https://stooq.com/q/l/?s={symbols_str}&f=sd2t2ohlcv&h&e=csv",
            headers=_STOOQ_HEADERS,
            timeout=8,
        )
        if not r.ok:
            return out
        for line in r.text.strip().splitlines()[1:]:
            parts = line.split(",")
            if len(parts) < 7:
                continue
            sym_raw = parts[0].strip().upper()
            key = _STOOQ_TO_KEY.get(sym_raw.lower(), sym_raw.replace(".F", "=F"))
            try:
                open_p = float(parts[3])
                close_p = float(parts[6])
                change = round(close_p - open_p, 4)
                pct = round(change / open_p * 100 if open_p else 0.0, 2)
                out[key] = {
                    "price": round(close_p, 4),
                    "change": change,
                    "pct": pct,
                    "prev": round(open_p, 4),
                    "name": key,
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


def _fetch_and_store_usda() -> dict:
    stored = {}
    try:
        for c in _MLR_COMMODITIES:
            try:
                r = _req.get(f"{_MLR_BASE}?Report_ID={c['report']}&key=&q=", timeout=10)
                if not r.ok:
                    continue
                data = r.json()
                results = data.get("results") or []
                row = next(
                    (
                        x
                        for x in results
                        if c["match"].lower() in (x.get("label") or "").lower()
                    ),
                    results[0] if results else None,
                )
                if not row:
                    continue
                price = float(row.get("price") or row.get("avg_price") or 0)
                if price <= 0:
                    continue
                with SessionLocal() as db:
                    db.execute(
                        text(
                            "INSERT INTO CommodityPriceHistory (Commodity, PriceUSD) "
                            "VALUES (:c, :p)"
                        ),
                        {"c": c["key"], "p": price},
                    )
                    db.commit()
                stored[c["key"]] = price
            except Exception as e:
                _log.warning(f"[commodity_history] MLR fetch error for {c['key']}: {e}")

        for c in _FV_COMMODITIES:
            try:
                r = _fv_session.get(
                    _FV_BASE,
                    params={
                        "startIndex": 1,
                        "type": "terminal",
                        "repType": c["repType"],
                        "run": "Run",
                        "format": "json",
                        "commodity": c["commName"],
                        "organic": "N",
                    },
                    timeout=10,
                )
                if not r.ok:
                    continue
                data = r.json()
                items = data.get("Result") or data.get("results") or []
                if not items:
                    continue
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
                    db.execute(
                        text(
                            "INSERT INTO CommodityPriceHistory (Commodity, PriceUSD) "
                            "VALUES (:c, :p)"
                        ),
                        {"c": c["key"], "p": round(avg, 4)},
                    )
                    db.commit()
                stored[c["key"]] = round(avg, 4)
            except Exception as e:
                _log.warning(f"[commodity_history] FV fetch error for {c['key']}: {e}")
    except Exception as e:
        _log.error(f"[commodity_history] USDA fetch error: {e}")
    return stored


def _fetch_and_store_prices() -> dict:
    """Fetch live prices and persist history. India mandi by default."""
    if _MARKET == "us":
        return _fetch_and_store_usda()
    quotes = _fetch_mandi_feed(force=True)
    return _store_mandi_history(quotes)


@router.post("/fetch")
def fetch_prices(
    background_tasks: BackgroundTasks,
    x_cron_secret: Optional[str] = Header(None, alias="X-Cron-Secret"),
):
    """Trigger a live price fetch. Cloud Scheduler should send X-Cron-Secret."""
    expected = (os.getenv("CRON_SECRET") or "").strip()
    if expected and x_cron_secret != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not expected and os.getenv("K_SERVICE"):
        raise HTTPException(status_code=401, detail="CRON_SECRET is not configured")
    background_tasks.add_task(_fetch_and_store_prices)
    return {"ok": True, "message": "Price fetch queued", "market": _MARKET}


@router.get("/mandi")
def get_mandi_catalog(
    category: Optional[str] = None,
    q: Optional[str] = None,
    state: Optional[str] = None,
    limit: int = Query(60, ge=1, le=200),
):
    """India mandi catalog: modal ₹/quintal, MSP, season, states."""
    _fetch_mandi_feed()
    items = list(_MANDI_RAW)

    if category:
        cat = category.strip().lower()
        items = [i for i in items if (i.get("category") or "").lower() == cat]

    if state:
        st = state.strip().lower()
        items = [
            i
            for i in items
            if any(st in str(s).lower() for s in (i.get("major_states") or []))
        ]

    if q:
        needle = q.strip().lower()
        items = [
            i
            for i in items
            if needle in (i.get("name") or "").lower()
            or needle in (i.get("hindi") or "").lower()
            or needle in (i.get("id") or "").lower()
            or needle in (i.get("category") or "").lower()
        ]

    rank = {cid: idx for idx, cid in enumerate(_INDIA_PRIORITY)}
    items.sort(key=lambda i: (rank.get(i["id"], 999), i.get("name") or ""))

    cats = sorted({i.get("category") or "Other" for i in _MANDI_RAW})
    states = sorted({
        str(s).strip()
        for i in _MANDI_RAW
        for s in (i.get("major_states") or [])
        if s and str(s).strip()
    })
    return {
        "market": "india_mandi",
        "currency": "INR",
        "unit_default": "quintal",
        "meta": _MANDI_META,
        "fetched_at": _MANDI_CACHE_AT.isoformat() if _MANDI_CACHE_AT else None,
        "categories": cats,
        "states": states,
        "count": len(items[:limit]),
        "commodities": items[:limit],
    }


@router.get("/history")
def get_price_history(
    commodity: Optional[str] = None,
    days: int = Query(30, ge=1, le=365),
    background_tasks: BackgroundTasks = None,
):
    """Price points per commodity over the last N days with trend stats."""
    since = datetime.utcnow() - timedelta(days=days)

    with SessionLocal() as db:
        recent = db.execute(
            text(
                "SELECT TOP 1 1 FROM CommodityPriceHistory "
                "WHERE FetchedAt >= DATEADD(hour, -24, GETDATE())"
            )
        ).scalar()
        if not recent and background_tasks is not None:
            background_tasks.add_task(_fetch_and_store_prices)

        if commodity:
            rows = (
                db.execute(
                    text(
                        """
                        SELECT Commodity, PriceUSD, FetchedAt
                        FROM CommodityPriceHistory
                        WHERE Commodity = :c AND FetchedAt >= :since
                        ORDER BY FetchedAt ASC
                        """
                    ),
                    {"c": commodity, "since": since},
                )
                .mappings()
                .all()
            )
        else:
            rows = (
                db.execute(
                    text(
                        """
                        SELECT Commodity, PriceUSD, FetchedAt
                        FROM CommodityPriceHistory
                        WHERE FetchedAt >= :since
                        ORDER BY Commodity, FetchedAt ASC
                        """
                    ),
                    {"since": since},
                )
                .mappings()
                .all()
            )

    by_commodity: dict = defaultdict(list)
    for r in rows:
        ts = r["FetchedAt"]
        by_commodity[r["Commodity"]].append(
            {
                "price": float(r["PriceUSD"]),
                "at": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
            }
        )

    currency = "INR" if _MARKET != "us" else "USD"
    result = {}
    for comm, pts in by_commodity.items():
        prices = [p["price"] for p in pts]
        first, last = prices[0], prices[-1]
        pct = round((last - first) / first * 100, 2) if first else None
        result[comm] = {
            "points": pts,
            "latest": last,
            "avg_7d": round(sum(prices[-7:]) / len(prices[-7:]), 4) if prices else None,
            "avg_30d": round(sum(prices) / len(prices), 4) if prices else None,
            "pct_change": pct,
            "trend": "rising"
            if pct and pct > 2
            else ("falling" if pct and pct < -2 else "stable"),
            "currency": currency,
        }
    return result


@router.get("/quotes")
def get_futures_quotes():
    """Live quotes. India: mandi modal ₹/qtl. US: Yahoo/Stooq futures."""
    now = datetime.utcnow()
    if _MARKET != "us":
        quotes = _fetch_mandi_feed()
        return {
            "quotes": quotes,
            "market": "india_mandi",
            "currency": "INR",
            "unit_default": "quintal",
            "meta": _MANDI_META,
            "fetched_at": _MANDI_CACHE_AT.isoformat() if _MANDI_CACHE_AT else None,
            "stale": bool(_MANDI_CACHE_AT and (now - _MANDI_CACHE_AT) > _MANDI_TTL),
        }

    if not _YF_CACHE or not _YF_CACHE_AT or (now - _YF_CACHE_AT) > _YF_TTL:
        _fetch_yf_quotes()
    return {
        "quotes": _YF_CACHE,
        "market": "us_futures",
        "currency": "USD",
        "fetched_at": _YF_CACHE_AT.isoformat() if _YF_CACHE_AT else None,
        "stale": bool(_YF_CACHE_AT and (now - _YF_CACHE_AT) > _YF_TTL),
    }
