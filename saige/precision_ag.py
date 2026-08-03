"""
Precision-ag tools for Saige.

Surfaces a farmer's field data (list of fields, latest satellite-based crop
analyses with NDVI/EVI/SAVI-type vegetation indices, and open alerts) to the
LLM so users can ask questions like:
  - "How are my fields doing?"
  - "What's the NDVI on my corn field?"
  - "Are there any active alerts on my fields?"
  - "Show me the trend on field 12."

The underlying data is populated by CropMonitoringBackend (a separate FastAPI
service that runs Sentinel/Landsat analyses and writes to dbo.Field,
dbo.Analysis, dbo.VegetationIndex, dbo.Alert). Saige reads those tables
directly over the shared SQL Server connection — it is never writing to them.

Access control: every query is scoped to the BusinessIDs returned by
dbo.BusinessAccess for the current PeopleID. Field access that the LLM
requests by FieldID is verified against that set before any data is returned,
so a user cannot ask about a field belonging to another business.
"""
from __future__ import annotations

import os
from typing import List, Optional, Dict, Any
from langchain_core.tools import tool

from config import DB_CONFIG, RAG_AVAILABLE

try:
    import pymssql
    _PMS_AVAILABLE = True
except ImportError:
    _PMS_AVAILABLE = False


# ---------------------------------------------------------------------------
# DB helpers (scoped to precision-ag tables; separate from saige.database
# which whitelists only livestock tables).
# ---------------------------------------------------------------------------

def _connect():
    if not _PMS_AVAILABLE or not all([DB_CONFIG.get("host"), DB_CONFIG.get("user"), DB_CONFIG.get("database")]):
        return None
    try:
        return pymssql.connect(
            server=DB_CONFIG["host"],
            port=DB_CONFIG["port"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
            database=DB_CONFIG["database"],
            as_dict=True,
        )
    except Exception as e:
        print(f"[precision_ag] DB connect failed: {e}")
        return None


def _query(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    conn = _connect()
    if conn is None:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        rows = cursor.fetchall() or []
        # Normalize column keys to lowercase — every tool below reads lowercase
        # keys (f["fieldid"], r["businessid"], ...), but pymssql/as_dict can
        # preserve the SQL column case (BusinessID, FieldID), which silently
        # produced empty results.
        return [{(k.lower() if isinstance(k, str) else k): v for k, v in r.items()} for r in rows]
    except Exception as e:
        print(f"[precision_ag] query error: {e}")
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _business_ids_for_people(people_id: Optional[str]) -> List[int]:
    if not people_id:
        return []
    rows = _query(
        "SELECT BusinessID FROM dbo.BusinessAccess WHERE PeopleID = %s AND (Active IS NULL OR Active = 1)",
        (str(people_id),),
    )
    return [int(r["businessid"]) for r in rows if r.get("businessid") is not None]


def _field_accessible(field_id: int, business_ids: List[int]) -> Optional[Dict[str, Any]]:
    if not field_id or not business_ids:
        return None
    placeholders = ",".join(["%s"] * len(business_ids))
    rows = _query(
        f"SELECT * FROM dbo.Field WHERE FieldID = %s AND BusinessID IN ({placeholders}) "
        f"AND (DeletedAt IS NULL)",
        (int(field_id), *business_ids),
    )
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_date(val) -> str:
    if not val:
        return "—"
    s = str(val)
    return s.split(" ")[0].split("T")[0]


def _fmt_num(v, digits: int = 2) -> str:
    try:
        return f"{float(v):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _describe_ndvi(mean: Optional[float]) -> str:
    try:
        v = float(mean)
    except (TypeError, ValueError):
        return ""
    if v >= 0.7:
        return "very healthy / dense canopy"
    if v >= 0.5:
        return "healthy"
    if v >= 0.3:
        return "moderate / stressed"
    if v >= 0.1:
        return "sparse / poor canopy"
    return "bare soil or no vegetation"


# ---------------------------------------------------------------------------
# TOOLS — these expect people_id to be injected by the node from graph state.
# The LLM should NOT try to guess people_id; nodes.py overrides it.
# ---------------------------------------------------------------------------

@tool
def list_my_fields_tool(people_id: str = "") -> str:
    """List every field/plot monitored for the current user in the precision-ag
    system (CropMonitoringBackend). Returns field ID, name, crop type, size
    (hectares), planting date, and whether satellite monitoring is on. Use
    when the user asks "what fields do I have", "show my farm plots", "list
    my crops", or any question that needs the ID of one of their fields.
    Do not pass people_id — it is injected automatically from session state."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "No fields found — your account is not linked to any business with monitored fields."
    placeholders = ",".join(["%s"] * len(biz_ids))
    rows = _query(
        f"SELECT FieldID, Name, CropType, FieldSizeHectares, PlantingDate, "
        f"MonitoringEnabled, Address FROM dbo.Field "
        f"WHERE BusinessID IN ({placeholders}) AND DeletedAt IS NULL "
        f"ORDER BY Name",
        tuple(biz_ids),
    )
    if not rows:
        return "You have no fields set up in the precision-ag system yet. Add one in the Crop Monitor dashboard to start tracking it."
    lines = [f"Fields ({len(rows)}):"]
    for f in rows:
        size = _fmt_num(f.get("fieldsizehectares"), 2)
        planted = _fmt_date(f.get("plantingdate"))
        mon = "monitored" if f.get("monitoringenabled") else "monitoring off"
        crop = f.get("croptype") or "—"
        addr = (f.get("address") or "").strip()
        parts = [f"#{f['fieldid']} {f.get('name') or 'Unnamed'}", f"crop: {crop}",
                 f"size: {size} ha", f"planted: {planted}", mon]
        if addr:
            parts.append(addr)
        lines.append("  • " + " · ".join(parts))
    return "\n".join(lines)


@tool
def get_field_analysis_tool(field_id: int, people_id: str = "") -> str:
    """Get the latest satellite crop analysis for a specific field — vegetation
    indices (NDVI, EVI, SAVI, etc.), analysis date, cloud percent. Also shows
    the trend vs. the previous analysis so the farmer knows if the field is
    improving or declining. Use when the user asks "how is field X doing",
    "what's the NDVI on my corn field", "is my field healthy", or wants to
    judge current crop condition. people_id is injected from session state."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "Cannot look up field analysis — your account is not linked to any business."
    field = _field_accessible(int(field_id), biz_ids)
    if not field:
        return f"Field {field_id} does not exist or is not accessible on your account."
    analyses = _query(
        "SELECT TOP 2 AnalysisID, AnalysisDate, CloudPercent, SatelliteAcquiredAt "
        "FROM dbo.Analysis WHERE FieldID = %s ORDER BY AnalysisDate DESC",
        (int(field_id),),
    )
    if not analyses:
        return (f"Field #{field_id} ({field.get('name') or 'Unnamed'}) has no satellite "
                "analyses yet. Trigger one from the Crop Monitor dashboard or wait for "
                "the next scheduled run.")
    latest = analyses[0]
    prev = analyses[1] if len(analyses) > 1 else None
    latest_idx = _query(
        "SELECT IndexType, MeanValue, MinValue, MaxValue, StdDev "
        "FROM dbo.VegetationIndex WHERE AnalysisID = %s",
        (latest["analysisid"],),
    )
    prev_idx_map: Dict[str, float] = {}
    if prev:
        prev_rows = _query(
            "SELECT IndexType, MeanValue FROM dbo.VegetationIndex WHERE AnalysisID = %s",
            (prev["analysisid"],),
        )
        for r in prev_rows:
            try:
                prev_idx_map[str(r["indextype"]).lower()] = float(r["meanvalue"])
            except (TypeError, ValueError):
                continue

    lines = [
        f"Field #{field_id} — {field.get('name') or 'Unnamed'} ({field.get('croptype') or 'crop n/a'})",
        f"Latest analysis: {_fmt_date(latest.get('analysisdate'))} "
        f"(cloud cover {_fmt_num(latest.get('cloudpercent'), 1)}%)",
    ]
    if not latest_idx:
        lines.append("No vegetation indices recorded for this analysis.")
    else:
        for idx in latest_idx:
            itype = str(idx.get("indextype") or "").upper()
            mean = idx.get("meanvalue")
            try:
                mean_f = float(mean) if mean is not None else None
            except (TypeError, ValueError):
                mean_f = None
            prev_val = prev_idx_map.get(str(idx.get("indextype") or "").lower())
            trend = ""
            if mean_f is not None and prev_val is not None:
                delta = mean_f - prev_val
                arrow = "↑" if delta > 0.02 else ("↓" if delta < -0.02 else "→")
                trend = f"  ({arrow} {delta:+.3f} vs {_fmt_date(prev['analysisdate'])})"
            descriptor = f" — {_describe_ndvi(mean_f)}" if itype == "NDVI" and mean_f is not None else ""
            lines.append(
                f"  • {itype}: mean {_fmt_num(mean_f, 3)} "
                f"(range {_fmt_num(idx.get('minvalue'), 3)}–{_fmt_num(idx.get('maxvalue'), 3)}){descriptor}{trend}"
            )
    return "\n".join(lines)


@tool
def get_field_history_tool(field_id: int, months: int = 6, people_id: str = "") -> str:
    """Get the NDVI / vegetation-index time series for a field over the last N
    months (default 6). Use when the user asks "show trend", "how has field X
    changed", "is my crop getting better or worse over time", or anything that
    needs history rather than a single snapshot. people_id is injected from
    session state."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "Cannot look up field history — your account is not linked to any business."
    field = _field_accessible(int(field_id), biz_ids)
    if not field:
        return f"Field {field_id} does not exist or is not accessible on your account."
    months = max(1, min(int(months or 6), 24))
    rows = _query(
        "SELECT a.AnalysisID, a.AnalysisDate, a.CloudPercent, "
        "       v.IndexType, v.MeanValue "
        "FROM dbo.Analysis a "
        "LEFT JOIN dbo.VegetationIndex v ON v.AnalysisID = a.AnalysisID "
        "WHERE a.FieldID = %s "
        f"  AND a.AnalysisDate >= DATEADD(month, -{months}, GETDATE()) "
        "ORDER BY a.AnalysisDate DESC",
        (int(field_id),),
    )
    if not rows:
        return (f"No analyses in the last {months} months for field #{field_id} "
                f"({field.get('name') or 'Unnamed'}).")
    # Group by AnalysisDate → index map
    by_date: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        d = _fmt_date(r.get("analysisdate"))
        slot = by_date.setdefault(d, {"cloud": r.get("cloudpercent"), "idx": {}})
        it = str(r.get("indextype") or "").upper()
        if it:
            slot["idx"][it] = r.get("meanvalue")
    lines = [
        f"Field #{field_id} — {field.get('name') or 'Unnamed'} ({field.get('croptype') or 'crop n/a'})",
        f"Last {months} months ({len(by_date)} analyses):",
    ]
    ndvi_trend: List[str] = []
    for date, info in sorted(by_date.items(), reverse=True)[:15]:
        parts = [date]
        for key in ["NDVI", "EVI", "SAVI", "NDMI", "NDWI"]:
            if key in info["idx"] and info["idx"][key] is not None:
                parts.append(f"{key}={_fmt_num(info['idx'][key], 3)}")
        if info.get("cloud") is not None:
            parts.append(f"cloud={_fmt_num(info['cloud'], 0)}%")
        lines.append("  • " + " · ".join(parts))
        if "NDVI" in info["idx"] and info["idx"]["NDVI"] is not None:
            ndvi_trend.append(_fmt_num(info["idx"]["NDVI"], 3))
    if len(ndvi_trend) >= 2:
        try:
            first = float(ndvi_trend[-1])
            last = float(ndvi_trend[0])
            delta = last - first
            direction = "rising" if delta > 0.05 else ("falling" if delta < -0.05 else "steady")
            lines.append(f"NDVI trend over window: {direction} ({first:.3f} → {last:.3f}, Δ {delta:+.3f})")
        except ValueError:
            pass
    return "\n".join(lines)


@tool
def get_field_alerts_tool(field_id: int = 0, people_id: str = "") -> str:
    """List active/open precision-ag alerts (low NDVI, stress events, dropped
    monitoring coverage, etc.). Pass field_id=0 to see all open alerts across
    every field on the account; pass a specific field_id to narrow to one
    field. Use when the user asks "any alerts", "anything wrong with my
    fields", "what needs my attention". people_id is injected from session
    state."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "Cannot fetch alerts — your account is not linked to any business."
    placeholders = ",".join(["%s"] * len(biz_ids))
    if field_id and int(field_id) > 0:
        field = _field_accessible(int(field_id), biz_ids)
        if not field:
            return f"Field {field_id} does not exist or is not accessible on your account."
        rows = _query(
            "SELECT TOP 20 a.AlertID, a.AlertType, a.Severity, a.Message, a.Status, "
            "       a.CreatedAt, f.Name as FieldName, a.FieldID "
            "FROM dbo.Alert a LEFT JOIN dbo.Field f ON f.FieldID = a.FieldID "
            "WHERE a.FieldID = %s AND (a.Status IS NULL OR a.Status <> 'resolved') "
            "ORDER BY a.CreatedAt DESC",
            (int(field_id),),
        )
        scope = f"field #{field_id} ({field.get('name') or 'Unnamed'})"
    else:
        rows = _query(
            "SELECT TOP 20 a.AlertID, a.AlertType, a.Severity, a.Message, a.Status, "
            "       a.CreatedAt, f.Name as FieldName, a.FieldID "
            "FROM dbo.Alert a LEFT JOIN dbo.Field f ON f.FieldID = a.FieldID "
            f"WHERE a.BusinessID IN ({placeholders}) "
            "  AND (a.Status IS NULL OR a.Status <> 'resolved') "
            "ORDER BY a.CreatedAt DESC",
            tuple(biz_ids),
        )
        scope = "all your fields"
    if not rows:
        return f"No active alerts on {scope}. All clear."
    lines = [f"Active alerts on {scope} ({len(rows)}):"]
    for a in rows:
        sev = (a.get("severity") or "").upper() or "?"
        atype = a.get("alerttype") or "alert"
        msg = (a.get("message") or "").strip()
        short_msg = msg if len(msg) <= 140 else msg[:140].rstrip() + "…"
        lines.append(
            f"  • [{sev}] field #{a.get('fieldid')} ({a.get('fieldname') or 'Unnamed'}) · "
            f"{atype} · {_fmt_date(a.get('createdat'))}"
            + (f" — {short_msg}" if short_msg else "")
        )
    return "\n".join(lines)



# ---------------------------------------------------------------------------
# HTTP helper — calls the OFN backend (port 8000) for computed endpoints
# ---------------------------------------------------------------------------

import requests as _requests

_BACKEND_URL = os.getenv("OFN_BACKEND_URL", "http://localhost:8000").rstrip("/")
_HTTP_TIMEOUT = 10


def _api_get(path: str) -> Optional[Dict[str, Any]]:
    try:
        r = _requests.get(f"{_BACKEND_URL}{path}", timeout=_HTTP_TIMEOUT)
        return r.json() if r.ok else None
    except Exception as e:
        print(f"[precision_ag] HTTP GET {path} failed: {e}")
        return None


def _api_post(path: str, body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        r = _requests.post(f"{_BACKEND_URL}{path}", json=body, timeout=_HTTP_TIMEOUT)
        return r.json() if r.ok else None
    except Exception as e:
        print(f"[precision_ag] HTTP POST {path} failed: {e}")
        return None


# ---------------------------------------------------------------------------
# SOIL SAMPLES
# ---------------------------------------------------------------------------

@tool
def get_field_soil_samples_tool(field_id: int, people_id: str = "") -> str:
    """Get soil sample data for a field — pH, organic matter, nitrogen, phosphorus,
    potassium, and other nutrients. Saige interprets optimal ranges and flags
    deficiencies or excesses so the farmer knows exactly what amendments are needed.
    Use when the user asks about soil health, nutrient levels, fertilizer recommendations,
    or "what does my soil need". people_id is injected from session state."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "Cannot fetch soil samples — account not linked to any business."
    field = _field_accessible(int(field_id), biz_ids)
    if not field:
        return f"Field {field_id} is not accessible on your account."
    rows = _query(
        "SELECT TOP 10 SampleLabel, SampleDate, Depth_cm, pH, OrganicMatter, "
        "Nitrogen, Phosphorus, Potassium, Sulfur, Calcium, Magnesium, CEC, Notes "
        "FROM dbo.FieldSoilSample WHERE FieldID = %s ORDER BY SampleDate DESC",
        (int(field_id),),
    )
    if not rows:
        return (f"No soil samples on record for field #{field_id} "
                f"({field.get('name') or 'Unnamed'}). "
                "Add samples in the Precision Ag → Soil Samples section.")

    # Optimal ranges for interpretation
    RANGES = {
        "ph": (6.0, 7.0, "acidic (<6)", "optimal (6–7)", "alkaline (>7)"),
        "organicmatter": (2.0, 5.0, "low OM (<2%) — add compost", "good OM (2–5%)", "high OM (>5%)"),
        "nitrogen": (20, 60, "N deficient", "adequate N", "high N"),
        "phosphorus": (15, 40, "P deficient — apply phosphate", "adequate P", "excess P — leaching risk"),
        "potassium": (100, 200, "K deficient — apply potash", "adequate K", "excess K"),
    }

    def _grade(val, key):
        if val is None:
            return "—"
        lo, hi = RANGES[key][0], RANGES[key][1]
        try:
            v = float(val)
            if v < lo:
                return f"{v:.2f} ⚠ {RANGES[key][2]}"
            if v > hi:
                return f"{v:.2f} ℹ {RANGES[key][4]}"
            return f"{v:.2f} ✓ {RANGES[key][3]}"
        except (TypeError, ValueError):
            return "—"

    lines = [f"Soil samples for field #{field_id} ({field.get('name') or 'Unnamed'}) — {len(rows)} record(s):"]
    for s in rows:
        label = s.get("samplelabel") or "Sample"
        date  = _fmt_date(s.get("sampledate"))
        depth = s.get("depth_cm") or "?"
        lines.append(f"\n  [{label} — {date}, depth {depth}cm]")
        lines.append(f"    pH: {_grade(s.get('ph'), 'ph')}")
        lines.append(f"    Organic Matter: {_grade(s.get('organicmatter'), 'organicmatter')}")
        lines.append(f"    N: {_grade(s.get('nitrogen'), 'nitrogen')} kg/ha")
        lines.append(f"    P: {_grade(s.get('phosphorus'), 'phosphorus')} kg/ha")
        lines.append(f"    K: {_grade(s.get('potassium'), 'potassium')} kg/ha")
        if s.get("cec"):
            lines.append(f"    CEC: {_fmt_num(s.get('cec'), 1)} meq/100g")
        if s.get("notes"):
            lines.append(f"    Notes: {s['notes']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# SCOUTING
# ---------------------------------------------------------------------------

# Scouting and journal entries are unified under the FieldNote table — these
# scouting tools read / write Notes filtered to the scouting-style categories.
_SCOUTING_CATEGORIES = ("Scouting", "Pest", "Disease", "Weed", "Nutrient", "Irrigation", "Weather", "General")


@tool
def get_field_scouting_tool(field_id: int, people_id: str = "") -> str:
    """Get recent field scouting observations — pest sightings, disease, weed
    pressure, nutrient deficiency symptoms, irrigation issues. Backed by the
    Field Journal (Notes) table; observations with a Severity set or a
    scouting-style category are returned. Use when the user asks "what
    scouting issues are on my field", "any pests found", "what's been
    observed in the field", or wants to understand in-field conditions beyond
    satellite data. people_id is injected from session state."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "Cannot fetch scouting data — account not linked to any business."
    field = _field_accessible(int(field_id), biz_ids)
    if not field:
        return f"Field {field_id} is not accessible on your account."
    placeholders = ",".join(["%s"] * len(_SCOUTING_CATEGORIES))
    rows = _query(
        f"SELECT TOP 20 NoteID, NoteDate, Category, Severity, Title, Content, "
        f"       Latitude, Longitude, ImageUrl "
        f"FROM dbo.FieldNote "
        f"WHERE FieldID = %s "
        f"  AND (Severity IS NOT NULL OR Category IN ({placeholders})) "
        f"ORDER BY NoteDate DESC, CreatedAt DESC",
        (int(field_id), *_SCOUTING_CATEGORIES),
    )
    if not rows:
        return (f"No scouting observations logged for field #{field_id} "
                f"({field.get('name') or 'Unnamed'}). "
                "Add observations in OatSense → Notes (use a scouting category like Pest/Disease/Weed).")
    lines = [f"Scouting log for field #{field_id} ({field.get('name') or 'Unnamed'}) — {len(rows)} observation(s):"]
    critical_high = [r for r in rows if str(r.get("severity") or "").lower() in ("critical", "high")]
    if critical_high:
        lines.append(f"  ⚠ {len(critical_high)} High/Critical severity issue(s) require attention!")
    for r in rows:
        sev = r.get("severity") or "—"
        cat = r.get("category") or "General"
        title = (r.get("title") or "").strip()
        body  = (r.get("content") or "").strip()
        date  = _fmt_date(r.get("notedate"))
        icon  = {"critical": "🚨", "high": "⚠️", "medium": "⚡", "low": "ℹ️"}.get(sev.lower(), "•")
        line  = f"  {icon} [{(sev or '').upper()}] {cat} — {date}"
        snippet = title or body
        if snippet:
            line += f": {snippet[:120]}"
        lines.append(line)
    return "\n".join(lines)


@tool
def add_scout_observation_tool(
    field_id: int,
    category: str,
    severity: str,
    notes: str,
    people_id: str = "",
) -> str:
    """Log a new scouting observation for a field on behalf of the user. Saved
    as a Field Journal (Notes) entry with the given scouting category and
    severity. Use when the user tells you they found a pest, disease, weed
    issue, or any in-field observation and wants it recorded. Category options:
    Scouting, Pest, Disease, Weed, Irrigation, Nutrient, Weather, General.
    Severity: Low, Medium, High, Critical. people_id is injected from session state."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "Cannot log scouting — account not linked to any business."
    field = _field_accessible(int(field_id), biz_ids)
    if not field:
        return f"Field {field_id} is not accessible on your account."
    import datetime
    title = f"{category} observation" + (f" ({severity})" if severity else "")
    body = {
        "field_id":    int(field_id),
        "business_id": int(field.get("businessid") or 0),
        "people_id":   int(people_id) if people_id and str(people_id).isdigit() else None,
        "note_date":   datetime.date.today().isoformat(),
        "category":    category or "Scouting",
        "title":       title,
        "content":     notes,
        "severity":    severity or None,
    }
    result = _api_post("/api/notes", body)
    if result and result.get("note_id"):
        return (f"✓ Scouting observation logged for field #{field_id} "
                f"({field.get('name') or 'Unnamed'}): [{(severity or '').upper()}] {category} — {notes[:80]}")
    return "Failed to save the scouting observation. Please try again."


# ---------------------------------------------------------------------------
# ACTIVITY LOG
# ---------------------------------------------------------------------------

@tool
def get_field_activity_log_tool(field_id: int, people_id: str = "") -> str:
    """Get the recent field activity log — spray applications, fertilizer
    applications, tillage, irrigation events, planting, harvest, and other
    operations. Use when the user asks "what have we done on this field",
    "what was applied last week", "show me the operation history", or when
    building context for agronomic advice. people_id is injected from session state."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "Cannot fetch activity log — account not linked to any business."
    field = _field_accessible(int(field_id), biz_ids)
    if not field:
        return f"Field {field_id} is not accessible on your account."
    rows = _query(
        "SELECT TOP 20 ActivityDate, ActivityType, Product, Rate, RateUnit, "
        "OperatorName, Notes "
        "FROM dbo.FieldActivityLog WHERE FieldID = %s ORDER BY ActivityDate DESC",
        (int(field_id),),
    )
    if not rows:
        return (f"No activities logged yet for field #{field_id} "
                f"({field.get('name') or 'Unnamed'}). "
                "Log operations in Precision Ag → Activity Log.")
    lines = [f"Activity log for field #{field_id} ({field.get('name') or 'Unnamed'}) — {len(rows)} record(s):"]
    for r in rows:
        date  = _fmt_date(r.get("activitydate"))
        atype = r.get("activitytype") or "Activity"
        product = r.get("product") or ""
        rate    = r.get("rate")
        unit    = r.get("rateunit") or ""
        op      = r.get("operatorname") or ""
        notes   = (r.get("notes") or "").strip()
        rate_str = f" @ {_fmt_num(rate, 1)} {unit}".rstrip() if rate is not None else ""
        op_str   = f" by {op}" if op else ""
        line = f"  • {date} — {atype}: {product}{rate_str}{op_str}"
        if notes:
            line += f" ({notes[:80]})"
        lines.append(line)
    return "\n".join(lines)


@tool
def log_field_activity_tool(
    field_id: int,
    activity_type: str,
    activity_date: str,
    product: str = "",
    rate: float = None,
    rate_unit: str = "",
    operator_name: str = "",
    notes: str = "",
    people_id: str = "",
) -> str:
    """Log a new field operation / activity on behalf of the user. Use when the
    user says they did something on a field and wants it recorded: sprayed,
    fertilized, tilled, irrigated, planted, harvested, etc. activity_type must
    be one of: Spray, Fertilize, Tillage, Irrigation, Harvest, Planting, Scouting,
    Soil Sample, Other. activity_date should be YYYY-MM-DD format (default today).
    people_id is injected from session state."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "Cannot log activity — account not linked to any business."
    field = _field_accessible(int(field_id), biz_ids)
    if not field:
        return f"Field {field_id} is not accessible on your account."
    body = {
        "activity_date": activity_date,
        "activity_type": activity_type,
        "product": product or None,
        "rate": rate,
        "rate_unit": rate_unit or None,
        "operator_name": operator_name or None,
        "notes": notes or None,
        "people_id": int(people_id) if people_id and str(people_id).isdigit() else None,
    }
    result = _api_post(f"/api/fields/{field_id}/activity-log", body)
    if result and result.get("activity_id"):
        detail = f"{activity_type}"
        if product:
            detail += f": {product}"
        if rate is not None:
            detail += f" @ {rate} {rate_unit}"
        return (f"✓ Activity logged for field #{field_id} "
                f"({field.get('name') or 'Unnamed'}) on {activity_date}: {detail}")
    return "Failed to save the activity. Please try again."


@tool
def add_soil_sample_tool(
    field_id: int,
    sample_label: str,
    ph: float = None,
    organic_matter: float = None,
    nitrogen: float = None,
    phosphorus: float = None,
    potassium: float = None,
    sample_date: str = "",
    depth_cm: int = 30,
    notes: str = "",
    people_id: str = "",
) -> str:
    """Record a new soil sample result for a field on behalf of the user. Use
    when the user gives you their soil test results and wants them stored.
    sample_label is a short name (e.g. 'North corner'), ph is the pH value,
    organic_matter is OM%, nitrogen/phosphorus/potassium are in kg/ha,
    depth_cm is sampling depth (default 30cm). people_id is injected from session state."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "Cannot save soil sample — account not linked to any business."
    field = _field_accessible(int(field_id), biz_ids)
    if not field:
        return f"Field {field_id} is not accessible on your account."
    import datetime
    body = {
        "sample_label": sample_label,
        "sample_date": sample_date or datetime.date.today().isoformat(),
        "depth_cm": depth_cm,
        "ph": ph,
        "organic_matter": organic_matter,
        "nitrogen": nitrogen,
        "phosphorus": phosphorus,
        "potassium": potassium,
        "notes": notes or None,
    }
    result = _api_post(f"/api/fields/{field_id}/soil-samples", body)
    if result and result.get("sample_id"):
        parts = [f"pH={ph}" if ph is not None else None,
                 f"OM={organic_matter}%" if organic_matter is not None else None,
                 f"N={nitrogen}" if nitrogen is not None else None]
        summary = ", ".join(p for p in parts if p)
        return (f"✓ Soil sample '{sample_label}' saved for field #{field_id} "
                f"({field.get('name') or 'Unnamed'}): {summary or 'data recorded'}")
    return "Failed to save the soil sample. Please try again."


# ---------------------------------------------------------------------------
# GDD — Growing Degree Days
# ---------------------------------------------------------------------------

@tool
def get_field_gdd_tool(field_id: int, days: int = 180, people_id: str = "") -> str:
    """Get accumulated Growing Degree Days (GDD) for a field — the heat unit
    total that determines crop development stage. Saige interprets GDD against
    crop-specific milestones (emergence, flowering, maturity) to tell the farmer
    where their crop is in its development cycle. Use when the user asks about
    crop growth stage, development progress, when to expect flowering/harvest,
    or "how many GDD have we accumulated". people_id is injected from session state."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "Cannot fetch GDD — account not linked to any business."
    field = _field_accessible(int(field_id), biz_ids)
    if not field:
        return f"Field {field_id} is not accessible on your account."
    data = _api_get(f"/api/fields/{field_id}/gdd?days={max(30, min(int(days), 365))}")
    if not data:
        return (f"Could not retrieve GDD data for field #{field_id}. "
                "Ensure the field has GPS coordinates set.")
    total = data.get("total_gdd", 0)
    base  = data.get("base_temp_f", 50)
    crop  = data.get("crop_type") or "Unknown crop"
    daily = data.get("daily") or []
    avg   = total / max(len(daily), 1)
    lines = [
        f"Growing Degree Days — field #{field_id} ({field.get('name') or 'Unnamed'})",
        f"Crop: {crop} | Base temperature: {base}°F | Period: {days} days",
        f"Total accumulated GDD: {total:.0f}",
        f"Average GDD/day: {avg:.1f}",
    ]
    if daily:
        recent = daily[-7:] if len(daily) >= 7 else daily
        recent_total = sum(d.get("gdd", 0) for d in recent)
        lines.append(f"Last 7 days: {recent_total:.0f} GDD ({recent_total/7:.1f}/day avg)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# IRRIGATION SCHEDULING
# ---------------------------------------------------------------------------

@tool
def get_field_irrigation_tool(field_id: int, days: int = 30, people_id: str = "") -> str:
    """Get irrigation scheduling recommendation for a field based on actual
    ET₀ (evapotranspiration) and precipitation data from Open-Meteo weather.
    Returns whether to irrigate now, soon, or not needed — with specific water
    deficit in inches. Use when the user asks "should I irrigate", "when should I
    water my field", "what's the water deficit", or "is my crop water-stressed".
    people_id is injected from session state."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "Cannot fetch irrigation data — account not linked to any business."
    field = _field_accessible(int(field_id), biz_ids)
    if not field:
        return f"Field {field_id} is not accessible on your account."
    data = _api_get(f"/api/fields/{field_id}/irrigation?days={max(7, min(int(days), 60))}")
    if not data:
        return (f"Could not retrieve irrigation data for field #{field_id}. "
                "Ensure the field has GPS coordinates set.")
    rec    = data.get("recommendation") or "—"
    urgency = data.get("urgency") or "low"
    deficit = data.get("cumulative_deficit_in") or 0
    kc      = data.get("kc") or 1.0
    crop    = data.get("crop_type") or "Unknown"
    daily   = data.get("daily") or []
    urgency_prefix = {"high": "🚨", "medium": "⚠️", "low": "✅"}.get(urgency, "•")
    lines = [
        f"Irrigation schedule — field #{field_id} ({field.get('name') or 'Unnamed'})",
        f"Crop: {crop} | Crop coefficient (Kc): {kc}",
        f"{urgency_prefix} Recommendation: {rec}",
        f"Cumulative water deficit: {deficit:.2f} inches",
    ]
    if daily:
        last7 = daily[-7:]
        tp = sum(d.get("precip_in", 0) for d in last7)
        te = sum(d.get("etc_in", 0)   for d in last7)
        lines.append(f"Last 7 days: {tp:.2f}\" precip, {te:.2f}\" crop water use (ETc)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# YIELD FORECAST
# ---------------------------------------------------------------------------

@tool
def get_field_yield_forecast_tool(field_id: int, people_id: str = "") -> str:
    """Get the current NDVI-based yield forecast for a field — an estimate of
    expected harvest yield in kg/ha, compared to the crop-type baseline and
    the trend over recent satellite passes. Use when the user asks "what yield
    am I looking at", "will this be a good harvest", "how does my field compare
    to average yield", "is yield improving". people_id is injected from session state."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "Cannot fetch yield forecast — account not linked to any business."
    field = _field_accessible(int(field_id), biz_ids)
    if not field:
        return f"Field {field_id} is not accessible on your account."
    data = _api_get(f"/api/fields/{field_id}/yield-forecast")
    if not data:
        return f"Could not retrieve yield forecast for field #{field_id}."
    forecast = data.get("forecast_kgha")
    baseline = data.get("baseline_kgha")
    trend    = data.get("trend_pct")
    conf     = data.get("confidence") or "low"
    crop     = data.get("crop_type") or "Unknown"
    history  = data.get("history") or []
    if forecast is None:
        return (f"No yield forecast available for field #{field_id} ({field.get('name') or 'Unnamed'}). "
                "Run satellite analyses first.")
    vs_baseline = ((forecast - baseline) / baseline * 100) if baseline else None
    conf_note = {"high": "high confidence", "medium": "medium confidence", "low": "low confidence — more analyses needed"}.get(conf, conf)
    lines = [
        f"Yield forecast — field #{field_id} ({field.get('name') or 'Unnamed'})",
        f"Crop: {crop}",
        f"Forecast: {int(forecast):,} kg/ha ({conf_note})",
        f"Baseline (avg for {crop}): {int(baseline or 0):,} kg/ha",
    ]
    if vs_baseline is not None:
        dir_word = "above" if vs_baseline >= 0 else "below"
        lines.append(f"Performance vs baseline: {abs(vs_baseline):.1f}% {dir_word} average")
    if trend is not None:
        trend_word = "improving" if trend > 0 else ("declining" if trend < 0 else "stable")
        lines.append(f"NDVI trend: {trend_word} ({trend:+.1f}% since first analysis)")
    if history:
        latest_ndvi = history[0].get("ndvi")
        if latest_ndvi:
            lines.append(f"Latest NDVI: {latest_ndvi:.4f}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CARBON & SUSTAINABILITY
# ---------------------------------------------------------------------------

@tool
def get_field_carbon_tool(field_id: int, people_id: str = "") -> str:
    """Get carbon and sustainability metrics for a field — soil organic matter
    (OM) trends, estimated soil organic carbon (SOC) stocks, crop rotation
    diversity, cover crop history, and a sustainability score. Use when the
    user asks about "carbon", "soil health trends", "how sustainable is my
    farm", "cover crop history", "crop rotation diversity", or wants to
    understand their regenerative ag progress. people_id is injected from session state."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "Cannot fetch carbon data — account not linked to any business."
    field = _field_accessible(int(field_id), biz_ids)
    if not field:
        return f"Field {field_id} is not accessible on your account."
    data = _api_get(f"/api/fields/{field_id}/carbon")
    if not data:
        return f"Could not retrieve carbon data for field #{field_id}."
    score    = data.get("sustainability_score") or 0
    cc       = data.get("cover_crop_seasons") or 0
    om_trend = data.get("om_trend_pct")
    soc      = data.get("latest_soc_MgCha")
    om_hist  = data.get("om_history") or []
    rotations = data.get("rotation_history") or []
    score_label = "Good" if score >= 75 else ("Fair" if score >= 50 else "Needs improvement")
    lines = [
        f"Carbon & sustainability — field #{field_id} ({field.get('name') or 'Unnamed'})",
        f"Sustainability score: {score}/100 ({score_label})",
    ]
    if soc is not None:
        lines.append(f"Soil organic carbon stock: {soc} Mg C/ha")
    if om_trend is not None:
        trend_dir = "increasing ↑" if om_trend > 0 else ("decreasing ↓" if om_trend < 0 else "stable →")
        lines.append(f"Organic matter trend: {om_trend:+.2f}% ({trend_dir})")
    if om_hist:
        latest_om = om_hist[-1]
        lines.append(f"Latest OM: {latest_om.get('om_pct')}% ({latest_om.get('date') or latest_om.get('label')})")
    lines.append(f"Cover crop seasons recorded: {cc}")
    if rotations:
        unique_crops = list(set(r.get("crop") for r in rotations if r.get("crop")))
        lines.append(f"Rotation history: {len(rotations)} seasons, {len(unique_crops)} different crops")
        recent = rotations[:3]
        lines.append("  Recent rotation: " + " → ".join(r.get("crop") or "?" for r in reversed(recent)))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# BENCHMARK — compare all fields for the business
# ---------------------------------------------------------------------------

@tool
def get_farm_benchmark_tool(people_id: str = "") -> str:
    """Compare all fields on the farm by NDVI, health score, and trend — a
    ranking that shows which fields are performing best and which need attention.
    Use when the user asks "which of my fields is doing best", "compare my
    fields", "which field needs the most work", "show me a farm overview".
    people_id is injected from session state."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "Cannot run benchmark — account not linked to any business."
    # Use first business ID for the benchmark
    biz_id = biz_ids[0]
    data = _api_get(f"/api/businesses/{biz_id}/benchmark")
    if not data:
        return "Could not retrieve benchmark data."
    fields = data.get("fields") or []
    if not fields:
        return "No fields with satellite data found for benchmarking."
    with_ndvi = [f for f in fields if f.get("ndvi") is not None]
    if not with_ndvi:
        return ("No fields have NDVI data yet. Run satellite analyses in "
                "Precision Ag → Analyses to start tracking performance.")
    avg_ndvi = sum(f["ndvi"] for f in with_ndvi) / len(with_ndvi)
    lines = [
        f"Farm benchmark — {len(fields)} field(s) across your operation",
        f"Average NDVI across all fields: {avg_ndvi:.3f}",
        "",
        "Ranking by NDVI:",
    ]
    for i, f in enumerate(fields, 1):
        ndvi    = f.get("ndvi")
        health  = f.get("health")
        trend   = f.get("trend")
        crop    = f.get("crop_type") or "—"
        medal   = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"#{i}")
        ndvi_str = f"{ndvi:.3f}" if ndvi is not None else "no data"
        health_str = f"{health}%" if health is not None else "—"
        trend_str = (f"{trend:+.4f}" if trend is not None else "—")
        vs = f" ({(ndvi - avg_ndvi):+.3f} vs avg)" if ndvi is not None else ""
        lines.append(f"  {medal} {f.get('name') or 'Unnamed'} [{crop}] — "
                     f"NDVI {ndvi_str}{vs} | Health {health_str} | Trend {trend_str}")
    if len(with_ndvi) >= 2:
        best  = with_ndvi[0]
        worst = with_ndvi[-1]
        lines.append("")
        lines.append(f"Best performer: {best.get('name') or 'Unnamed'} (NDVI {best['ndvi']:.3f})")
        lines.append(f"Needs most attention: {worst.get('name') or 'Unnamed'} (NDVI {worst['ndvi']:.3f})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# WEATHER (field-specific, for context in agronomic advice)
# ---------------------------------------------------------------------------

@tool
def get_field_weather_tool(field_id: int, days: int = 14, people_id: str = "") -> str:
    """Get recent weather data for a field — temperature (high/low), precipitation,
    and reference ET₀. Use when the user asks about recent weather, temperature
    conditions, rainfall totals, frost risk context, or when giving agronomic
    advice that depends on current conditions. people_id is injected from session state."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "Cannot fetch weather — account not linked to any business."
    field = _field_accessible(int(field_id), biz_ids)
    if not field:
        return f"Field {field_id} is not accessible on your account."
    data = _api_get(f"/api/fields/{field_id}/weather?days={max(7, min(int(days), 30))}")
    if not data:
        return (f"Could not fetch weather for field #{field_id}. "
                "Ensure the field has GPS coordinates set.")
    daily = data.get("daily") or []
    if not daily:
        return "No weather data returned."
    recent = daily[-days:] if len(daily) >= days else daily
    # Compute summary
    precip_total = sum(d.get("precip", 0) or 0 for d in recent)
    tmax_vals = [d["temp_max"] for d in recent if d.get("temp_max") is not None]
    tmin_vals = [d["temp_min"] for d in recent if d.get("temp_min") is not None]
    avg_tmax = sum(tmax_vals) / len(tmax_vals) if tmax_vals else None
    avg_tmin = sum(tmin_vals) / len(tmin_vals) if tmin_vals else None
    lines = [
        f"Weather — field #{field_id} ({field.get('name') or 'Unnamed'}), last {len(recent)} days",
        f"Total precipitation: {precip_total:.2f} inches",
    ]
    if avg_tmax is not None:
        lines.append(f"Avg high: {avg_tmax:.1f}°F | Avg low: {avg_tmin:.1f}°F")
    # Last 7 days summary
    last7 = recent[-7:]
    lines.append("\nLast 7 days:")
    for d in last7:
        tmax = _fmt_num(d.get("temp_max"), 0) + "°F" if d.get("temp_max") is not None else "—"
        tmin = _fmt_num(d.get("temp_min"), 0) + "°F" if d.get("temp_min") is not None else "—"
        precip = _fmt_num(d.get("precip"), 2) + '"' if d.get("precip") is not None else "—"
        lines.append(f"  {d['date']} — High {tmax}, Low {tmin}, Precip {precip}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# BIOMASS — current estimate + auto-resolver for low confidence
# ---------------------------------------------------------------------------

def _confidence_advice(conf: float) -> str:
    """Plain-language explanation of why a satellite biomass confidence is low,
    with concrete steps the farmer can take to improve it."""
    return (
        "Confidence is low because the NDVI signal driving the estimate is weak — "
        "usually the canopy is sparse, the field has just emerged, or the most recent "
        "cloud-free pass was suboptimal. To improve it: "
        "(a) wait until canopy closure and re-run, "
        "(b) average several recent satellite passes to cancel noise, or "
        "(c) take a ground biomass clipping to calibrate. "
        "I can do (b) right now — just say "
        "\"improve confidence on field X\" and I'll average the recent passes for you."
    )


@tool
def get_field_biomass_tool(field_id: int, people_id: str = "") -> str:
    """Get the current dry-matter biomass estimate (kg DM/ha) for a field, with
    confidence and capture date. If confidence is low (<40%) the response also
    explains *why* and tells the user how to improve it (including offering the
    auto-resolver tool). Use when the user asks "what's my biomass", "how much
    forage do I have", "what does the biomass number mean", or asks why the
    confidence is low. people_id is injected from session state."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "Cannot fetch biomass — account not linked to any business."
    field = _field_accessible(int(field_id), biz_ids)
    if not field:
        return f"Field {field_id} is not accessible on your account."
    data = _api_get(f"/api/fields/{field_id}/biomass")
    if not data:
        return (f"Could not retrieve biomass data for field #{field_id}. "
                "Try running a satellite analysis first.")

    sat = data.get("satellite")
    upl = data.get("upload")
    if not sat and not upl:
        return (f"No biomass analysis on record for field #{field_id} "
                f"({field.get('name') or 'Unnamed'}). "
                "Run an analysis from the Precision Ag dashboard.")

    lines = [f"Biomass — field #{field_id} ({field.get('name') or 'Unnamed'})"]
    if sat:
        bm   = sat.get("biomass_kg_per_ha")
        conf = sat.get("confidence")
        cap  = _fmt_date(sat.get("captured_at"))
        ver  = sat.get("model_version") or "—"
        bm_s = f"{bm:,.0f}" if bm is not None else "—"
        conf_s = f"{conf*100:.0f}%" if conf is not None else "—"
        lines.append(f"Satellite estimate: {bm_s} kg DM/ha · confidence {conf_s} · {cap} · model {ver}")
        if conf is not None and conf < 0.4:
            lines.append("")
            lines.append(f"⚠ Low confidence ({conf_s}). {_confidence_advice(conf)}")
    if upl:
        bm   = upl.get("biomass_kg_per_ha")
        conf = upl.get("confidence")
        cap  = _fmt_date(upl.get("captured_at"))
        bm_s = f"{bm:,.0f}" if bm is not None else "—"
        conf_s = f"{conf*100:.0f}%" if conf is not None else "—"
        lines.append(f"Upload estimate: {bm_s} kg DM/ha · confidence {conf_s} · {cap}")
    return "\n".join(lines)


@tool
def improve_field_biomass_confidence_tool(field_id: int, people_id: str = "") -> str:
    """Run a fresh satellite biomass analysis and average it with the most recent
    prior passes to produce a higher-confidence combined estimate. Use when the
    user asks to "improve confidence", "fix the biomass confidence", "average the
    biomass", or follows up after seeing a low-confidence biomass number and
    wants Saige to resolve it. people_id is injected from session state."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "Cannot improve biomass — account not linked to any business."
    field = _field_accessible(int(field_id), biz_ids)
    if not field:
        return f"Field {field_id} is not accessible on your account."
    result = _api_post(f"/api/fields/{field_id}/biomass/resolve", {})
    if not result:
        return ("Could not improve biomass confidence — the satellite endpoint "
                "did not respond. Make sure a recent NDVI analysis exists for this "
                "field, then try again.")

    n     = result.get("n_samples") or 0
    fresh = result.get("fresh_sample") or {}
    avg_bm   = result.get("averaged_biomass_kg_per_ha")
    avg_conf = result.get("averaged_confidence")
    fresh_conf = fresh.get("confidence")

    avg_bm_s   = f"{avg_bm:,.0f}" if avg_bm is not None else "—"
    avg_conf_s = f"{avg_conf*100:.0f}%" if avg_conf is not None else "—"
    fresh_conf_s = f"{fresh_conf*100:.0f}%" if fresh_conf is not None else "—"

    lines = [
        f"✓ Improved biomass estimate for field #{field_id} ({field.get('name') or 'Unnamed'})",
        f"Averaged across {n} satellite pass(es).",
        f"Combined biomass: {avg_bm_s} kg DM/ha",
        f"Combined confidence: {avg_conf_s} (single-pass was {fresh_conf_s})",
    ]
    if avg_conf is not None and avg_conf < 0.4:
        lines.append("")
        lines.append(
            "Confidence is still low even after averaging. The underlying canopy "
            "signal is weak — wait for more growth and re-run, or take a ground "
            "biomass clipping to calibrate."
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MATURITY ENGINE — peak-antioxidant harvest prediction
# ---------------------------------------------------------------------------

@tool
def get_field_maturity_tool(field_id: int, people_id: str = "") -> str:
    """Get the current ripeness/maturity status for a field, including the
    predicted peak-antioxidant harvest date when enough samples have been
    logged. Returns the most recent Brix / anthocyanin / firmness readings,
    a published cultivar reference for context, the trend fit, and (when set)
    the buyer's shelf-target alignment. Use when the user asks "when should I
    harvest", "when is my fruit at peak", "what's the maturity on my berries",
    "is my field ripe yet", or any harvest-timing question.
    people_id is injected from session state."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "Cannot fetch maturity — account not linked to any business."
    field = _field_accessible(int(field_id), biz_ids)
    if not field:
        return f"Field {field_id} is not accessible on your account."
    data = _api_get(f"/api/fields/{field_id}/maturity")
    if not data:
        return (f"Could not retrieve maturity data for field #{field_id}. "
                "The maturity endpoint did not respond.")

    name = field.get("name") or "Unnamed"
    crop = data.get("crop_type") or "Unknown crop"
    samples = data.get("samples") or []
    pred = data.get("prediction") or {}
    arrival = data.get("arrival")
    ref = data.get("cultivar_reference")

    lines = [f"Maturity — field #{field_id} ({name}) · {crop}"]
    lines.append(f"Samples on record: {len(samples)}")

    if samples:
        s = samples[-1]
        bits = []
        if s.get("brix_degrees")     is not None: bits.append(f"Brix {s['brix_degrees']:.1f}°Bx")
        if s.get("anthocyanin_mg_g") is not None: bits.append(f"Anthocyanin {s['anthocyanin_mg_g']:.2f} mg/g")
        if s.get("firmness_kgf")     is not None: bits.append(f"Firmness {s['firmness_kgf']:.2f} kgf")
        if bits:
            lines.append(f"Latest sample ({s.get('sample_date')}): " + " · ".join(bits))

    status = pred.get("status")
    if status == "no_data":
        lines.append("")
        lines.append("⚠ No prediction yet — log your first refractometer or NIR reading to start.")
    elif status == "insufficient_metric":
        lines.append("")
        lines.append("⚠ Samples on file don't include Brix, anthocyanin, or color — those drive the projection.")
    else:
        peak = pred.get("predicted_peak_date")
        conf = pred.get("confidence")
        method = pred.get("method") or "—"
        conf_s = f"{conf*100:.0f}%" if conf is not None else "—"
        if peak:
            lines.append(f"Predicted peak: {peak} · confidence {conf_s} · method {method}")
        if pred.get("progress_pct") is not None:
            lines.append(f"Progress to ripe: {pred['progress_pct']:.0f}% (metric: {pred.get('metric')})")
        if pred.get("r_squared") is not None:
            lines.append(f"Trend fit R²: {pred['r_squared']}")
        if pred.get("message"):
            lines.append(pred["message"])

    if ref:
        lines.append("")
        lines.append(
            f"Cultivar reference: ripe ≈ {ref.get('brix_ripe')}°Bx, "
            f"peak anthocyanin ≈ {ref.get('anthocyanin_peak_mg_g')} mg/g."
        )

    if arrival:
        lines.append("")
        lines.append("— Ready-on-shelf plan —")
        if arrival.get("destination_label"):
            lines.append(f"Destination: {arrival['destination_label']}")
        if arrival.get("status") == "incomplete_destination":
            lines.append(arrival.get("message") or "Destination incomplete.")
        else:
            if arrival.get("projected_shelf_date"):
                lines.append(f"Projected shelf date (from peak): {arrival['projected_shelf_date']}")
            if arrival.get("shelf_target_date"):
                lines.append(f"Buyer shelf target: {arrival['shelf_target_date']}")
            if arrival.get("latest_pick_date"):
                lines.append(f"Latest pick to hit target: {arrival['latest_pick_date']}")
            if arrival.get("alignment_message"):
                lines.append(arrival["alignment_message"])

    return "\n".join(lines)


@tool
def log_maturity_sample_tool(
    field_id: int,
    sample_date: str = "",
    brix: float = None,
    anthocyanin_mg_g: float = None,
    firmness_kgf: float = None,
    notes: str = "",
    people_id: str = "",
) -> str:
    """Log a ripeness/quality sample for a field — refractometer Brix, handheld
    NIR anthocyanin, and/or penetrometer firmness. The sample feeds directly
    into the maturity-curve fit and improves the peak-harvest prediction. Use
    when the user says "log a sample", "I just measured Brix on my berries",
    "record an anthocyanin reading", or similar. sample_date is YYYY-MM-DD
    (defaults to today). people_id is injected from session state."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "Cannot log sample — account not linked to any business."
    field = _field_accessible(int(field_id), biz_ids)
    if not field:
        return f"Field {field_id} is not accessible on your account."

    if brix is None and anthocyanin_mg_g is None and firmness_kgf is None:
        return ("Need at least one measurement (Brix, anthocyanin, or firmness) "
                "to log a maturity sample.")

    body = {
        "field_id":         int(field_id),
        "business_id":      int(field.get("businessid")),
        "sample_date":      sample_date or "",
        "brix_degrees":     brix,
        "anthocyanin_mg_g": anthocyanin_mg_g,
        "firmness_kgf":     firmness_kgf,
        "notes":            notes,
    }
    result = _api_post(f"/api/fields/{field_id}/maturity/samples", body)
    if not result:
        return "Could not save the sample — the maturity endpoint did not accept the payload."

    bits = []
    if result.get("brix_degrees")     is not None: bits.append(f"Brix {result['brix_degrees']:.1f}°Bx")
    if result.get("anthocyanin_mg_g") is not None: bits.append(f"Anthocyanin {result['anthocyanin_mg_g']:.2f} mg/g")
    if result.get("firmness_kgf")     is not None: bits.append(f"Firmness {result['firmness_kgf']:.2f} kgf")
    return (f"✓ Logged sample on {result.get('sample_date')}: " + " · ".join(bits) +
            ". Ask 'when should I harvest field {0}?' to see the updated prediction.".format(field_id))


# ---------------------------------------------------------------------------
# CLIMATE FORECAST — predictive 72h+ stress detection with mitigation advice
# ---------------------------------------------------------------------------

@tool
def get_field_climate_forecast_tool(field_id: int, hours: int = 72, people_id: str = "") -> str:
    """Predictive climate-stress forecast for a field over the next `hours` (default 72,
    max 168 = 7 days). Detects upcoming heatwaves, frost, high-VPD drought stress,
    saturating rainfall, and damaging wind BEFORE they hit, with concrete mitigation
    actions tailored to the crop (open tunnel side-walls, schedule pre-cool irrigation,
    fire frost sprinklers, secure plastic, emergency pick before fruit-split rain, etc.).
    Use when the user asks "what's the forecast", "is there a heatwave coming",
    "should I worry about frost tonight", "do I need to ventilate the tunnel",
    or any forward-looking weather/crop-stress question. people_id is injected from
    session state."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "Cannot fetch climate forecast — account not linked to any business."
    field = _field_accessible(int(field_id), biz_ids)
    if not field:
        return f"Field {field_id} is not accessible on your account."

    h = max(24, min(int(hours or 72), 168))
    data = _api_get(f"/api/fields/{field_id}/climate-forecast?hours={h}")
    if not data:
        return (f"Could not fetch the climate forecast for field #{field_id}. "
                "Ensure the field has GPS coordinates set and Open-Meteo is reachable.")

    summary = data.get("summary") or {}
    events  = data.get("events")  or []
    field_name = data.get("field_name") or f"field #{field_id}"
    crop = data.get("crop_type") or "unknown crop"

    lines = [
        f"Climate-stress forecast — {field_name} ({crop}), next {h}h",
        f"  Highs/lows: {summary.get('max_temp_f', '—')}°F / {summary.get('min_temp_f', '—')}°F",
        f"  Peak VPD:   {summary.get('max_vpd_kpa', '—')} kPa",
        f"  Peak wind:  {summary.get('max_wind_mph', '—')} mph",
        f"  Total rain: {summary.get('total_precip_in', '—')} in",
    ]
    if not events:
        lines.append("\nNo crop-stress events detected in the forecast window. Routine operations OK.")
        return "\n".join(lines)

    lines.append(f"\n{len(events)} event(s) detected — listed by severity, then onset:")
    for ev in events:
        lines.append(
            f"\n• {ev['kind'].upper()} ({ev['severity']}) — onset in {ev['onset_hours_out']}h, "
            f"duration {ev['duration_hours']}h, peak {ev['peak_value']} {ev['units']}"
        )
        lines.append(f"  Why: {ev['reason']}")
        for i, action in enumerate(ev.get("recommended_actions") or [], 1):
            lines.append(f"  Action {i}: {action}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# WATER USE — WaPOR/OpenET evapotranspiration
# ---------------------------------------------------------------------------

@tool
def get_field_water_use_tool(field_id: int, people_id: str = "") -> str:
    """Crop water-use snapshot for a field — actual evapotranspiration (ETa)
    plus a 12-period series — sourced from FAO WaPOR / OpenET via the crop
    monitoring service. Use this for "how much water is my crop actually
    using", "is the field consuming water normally for the season", "is ET
    matching the irrigation I'm putting on", or any question about
    real-world (not just modeled) water use. Pair with
    get_field_irrigation_tool to compare actual ET to the deficit model."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "Cannot fetch water use — account not linked to any business."
    field = _field_accessible(int(field_id), biz_ids)
    if not field:
        return f"Field {field_id} is not accessible on your account."

    field_name = field.get("name") or field.get("fieldname") or f"field #{field_id}"
    snap   = _api_get(f"/api/fields/{field_id}/water-use")
    series = _api_get(f"/api/fields/{field_id}/water-use/series?limit=12")

    if not snap and not series:
        return (f"No WaPOR/OpenET water-use data is available for {field_name}. "
                "The field may be outside the WaPOR coverage area, or the satellite "
                "service is currently unreachable.")

    lines = [f"Crop water use — {field_name}"]
    snap_data = (snap or {}).get("wapor") or {}
    if isinstance(snap_data, dict):
        eta = snap_data.get("eta_mm") or snap_data.get("value") or snap_data.get("mean")
        units = snap_data.get("units") or "mm"
        when  = snap_data.get("date") or snap_data.get("acquired_at")
        if eta is not None:
            lines.append(f"  Latest actual ET: {eta} {units}" + (f" ({when})" if when else ""))

    series_rows = ((series or {}).get("wapor") or {}).get("series") or []
    if isinstance(series_rows, list) and series_rows:
        recent = series_rows[-6:]
        lines.append("  Recent series (most recent last):")
        for r in recent:
            d = r.get("date") or r.get("period") or "?"
            v = r.get("eta_mm") or r.get("value") or r.get("mean")
            if v is not None:
                lines.append(f"    {d}: {v} mm")

    if len(lines) == 1:
        lines.append("  No values returned (the field may be outside coverage).")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# AGRONOMY — CropMonitor's full per-field snapshot + recommendations
# ---------------------------------------------------------------------------

@tool
def get_field_agronomy_tool(field_id: int, people_id: str = "") -> str:
    """Composite agronomy snapshot from the satellite crop-monitoring service:
    current weather + 7-day forecast + GDD + predicted growth stage + latest
    vegetation indices + irrigation signal + per-product spray decision
    (herbicide/fungicide/insecticide) + crop-specific named pest & disease
    alerts (e.g. Gray Leaf Spot, Fusarium Head Blight, European Corn Borer)
    + concrete operational recommendations driven off the field's health
    score and NDVI. Use for "give me the full picture on this field", "what
    should I do this week", "what's the model recommending", "should I spray
    today", "any disease pressure?", or as a fast pre-flight before writing
    a Field Assessment Report. Cheap to call (cached server-side)."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "Cannot fetch agronomy snapshot — account not linked to any business."
    field = _field_accessible(int(field_id), biz_ids)
    if not field:
        return f"Field {field_id} is not accessible on your account."

    field_name = field.get("name") or field.get("fieldname") or f"field #{field_id}"
    agro = _api_get(f"/api/fields/{field_id}/agronomy") or {}
    recs = _api_get(f"/api/fields/{field_id}/recommendations") or {}

    if not agro and not recs:
        return (f"CropMonitor returned no agronomy data for {field_name}. "
                "Ensure the field has GPS coordinates and a recent satellite analysis.")

    lines = [f"Agronomy snapshot — {field_name}"]

    weather = agro.get("weather") or {}
    if weather:
        t = weather.get("temperature_c") or weather.get("temperature")
        rh = weather.get("humidity") or weather.get("relative_humidity")
        wind = weather.get("wind_speed") or weather.get("wind")
        cond = weather.get("conditions")
        bits = [f"temp={t}°C", f"RH={rh}%", f"wind={wind}kph"]
        if cond: bits.append(cond)
        lines.append(f"  Weather now: {', '.join(str(b) for b in bits if b)}")

    fcs = agro.get("forecast_summary") or []
    if fcs:
        lines.append(f"  Next {len(fcs)} days:")
        for f in fcs[:3]:
            d = f.get("date"); mx = f.get("max_c"); mn = f.get("min_c")
            p  = f.get("precip_mm"); w = f.get("max_wind_kph"); rh = f.get("humidity")
            cond = f.get("conditions")
            lines.append(f"    {d}: {mn}-{mx}°C, precip {p}mm, wind {w}kph, RH {rh}%{(', ' + cond) if cond else ''}")

    gdd = agro.get("gdd") or {}
    if isinstance(gdd, dict) and gdd.get("gdd") is not None:
        lines.append(f"  GDD accumulated: {gdd.get('gdd')} (base {gdd.get('base_temp_c')}°C since {gdd.get('start_date')})")
    if agro.get("growth_stage"):
        lines.append(f"  Predicted growth stage: {agro['growth_stage']}")

    indices = agro.get("indices") or {}
    if isinstance(indices, dict) and indices:
        bits = []
        for k in ("NDVI", "NDRE", "NDMI", "EVI", "SAVI"):
            v = indices.get(k)
            if isinstance(v, dict): v = v.get("mean")
            if v is not None: bits.append(f"{k}={v:.2f}" if isinstance(v, (int, float)) else f"{k}={v}")
        if bits:
            lines.append(f"  Latest indices: {', '.join(bits)}")

    irr = agro.get("irrigation_advice") or agro.get("irrigation") or {}
    if isinstance(irr, dict) and (irr.get("recommendation") or irr.get("status")):
        lines.append(f"  Irrigation signal: {irr.get('recommendation') or irr.get('status')}")

    # Per-product spray decisions (herbicide / fungicide / insecticide)
    sbp = agro.get("spray_by_product") or {}
    if isinstance(sbp, dict) and any(k in sbp for k in ("herbicide", "fungicide", "insecticide")):
        lines.append("  Spray decision today:")
        for k in ("herbicide", "fungicide", "insecticide"):
            v = sbp.get(k) or {}
            dec = v.get("decision")
            if not dec: continue
            fails = ", ".join(f"{r.get('field')}>{r.get('threshold')}" for r in (v.get("reasons") or []))
            warns = ", ".join(f"{r.get('field')}>{r.get('threshold')}" for r in (v.get("warnings") or []))
            extra = f" (fails: {fails})" if fails else (f" (watch: {warns})" if warns else "")
            lines.append(f"    {k.title()}: {dec}{extra}")

    # Crop-specific named pest/disease alerts (from rule table)
    pda = agro.get("pest_disease_alerts") or []
    if isinstance(pda, list) and pda:
        lines.append(f"  Pest & disease alerts ({len(pda)}):")
        for a in pda[:5]:
            sev = a.get("severity", "?"); name = a.get("name", "?")
            atype = a.get("type", "?"); why = a.get("why", "")
            lines.append(f"    [{sev}] {name} ({atype}): {a.get('action', '')}")
            if why:
                lines.append(f"        why: {why}")

    # Provider visibility — flag when running on fallback so Saige can caveat
    wps = agro.get("weather_provider_status") or {}
    if isinstance(wps, dict) and wps.get("provider") and wps.get("provider") != "weatherapi":
        lines.append(f"  (weather served by fallback: {wps.get('provider')})")

    # Generic disease_risk only matters when no specific alert fired
    if not pda:
        dis = agro.get("disease_risk") or {}
        if isinstance(dis, dict) and (dis.get("risk") or dis.get("level")):
            lines.append(f"  Disease risk (generic): {dis.get('risk') or dis.get('level')}")

    rec_list = recs.get("recommendations") if isinstance(recs, dict) else None
    if isinstance(rec_list, list) and rec_list:
        hs = recs.get("health_score")
        if hs is not None:
            lines.append(f"\nHealth score: {hs}")
        lines.append("Operational recommendations:")
        for i, r in enumerate(rec_list[:6], 1):
            if isinstance(r, dict):
                txt = r.get("action") or r.get("text") or r.get("title") or str(r)
                lines.append(f"  {i}. {txt}")
            else:
                lines.append(f"  {i}. {r}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# STRESS ZONES — k-means clustering on the latest vegetation-index raster
# ---------------------------------------------------------------------------

@tool
def get_field_zones_tool(field_id: int, num_zones: int = 4, index: str = "NDVI", people_id: str = "") -> str:
    """K-means stress zones for a field — clusters the latest Sentinel-2
    vegetation-index raster into N management zones (default 4) sorted from
    lowest = stress to highest = best. Returns per-zone area % + mean index
    + a one-line read of the spread. Use when the user asks "where are the
    stressed parts of this field", "show me management zones", "is this
    field uniform", or anything about variable-rate prescriptions or in-
    field variability. `index` defaults to NDVI but can be NDRE, EVI,
    GNDVI, NDWI. `num_zones` accepts 2-6."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "Cannot fetch zones — account not linked to any business."
    field = _field_accessible(int(field_id), biz_ids)
    if not field:
        return f"Field {field_id} is not accessible on your account."

    idx = (index or "NDVI").strip().upper()
    if idx not in {"NDVI", "NDRE", "EVI", "GNDVI", "NDWI"}:
        return f"Unknown index '{index}'. Use one of NDVI, NDRE, EVI, GNDVI, NDWI."
    nz = max(2, min(int(num_zones or 4), 6))

    field_name = field.get("name") or field.get("fieldname") or f"field #{field_id}"
    payload = _api_get(f"/api/fields/{field_id}/zones?index={idx}&num_zones={nz}&grid=48")
    if not payload or not payload.get("zones"):
        return (f"No {idx} zones available for {field_name}. "
                "Likely cause: no clear-sky Sentinel-2 scene in the last 30 days.")

    zones = payload.get("zones") or []
    raster = payload.get("raster") or {}
    image_date = payload.get("image_date")
    cached = (payload.get("_meta") or {}).get("cached")

    lines = [
        f"{idx} stress zones — {field_name}"
        + (f" (scene {image_date})" if image_date else "")
        + (" [cached]" if cached else "")
    ]
    lines.append(f"  Raster: {raster.get('valid_pixels')} valid pixels, "
                 f"{idx} range {raster.get('min')}–{raster.get('max')} (mean {raster.get('mean')})")
    lines.append(f"  {nz} zones (zone 1 = lowest = most stressed):")
    for z in zones:
        z1 = (z.get("zone") or 0) + 1
        lines.append(
            f"    Zone {z1}: {z.get('area_pct')}% of field, "
            f"mean {idx} {z.get('mean')}, centroid {z.get('centroid')}, "
            f"{z.get('pixel_count')} px"
        )

    # Quick read for the LLM
    if zones:
        worst = zones[0]
        best  = zones[-1]
        spread = (best.get("mean") or 0) - (worst.get("mean") or 0)
        if spread > 0.20:
            lines.append(f"  Read: high in-field variability (spread {spread:.2f}). VRT prescriptions likely worth the effort.")
        elif spread > 0.10:
            lines.append(f"  Read: moderate variability (spread {spread:.2f}). Worth scouting the lowest zone.")
        else:
            lines.append(f"  Read: field is fairly uniform (spread {spread:.2f}). Treat as a single zone for now.")
        if (worst.get("area_pct") or 0) >= 10:
            lines.append(f"  Stressed zone (#{(worst.get('zone') or 0) + 1}) covers ≥{worst.get('area_pct'):.0f}% — scout that area.")

    lines.append("  Variable-rate Rx export: `/api/fields/{id}/zones/prescription?fmt=geojson` (or fmt=csv).".replace("{id}", str(field_id)))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# FIELD ASSESSMENT REPORTS — historical consultant snapshots (RAG)
# ---------------------------------------------------------------------------

@tool
def get_field_assessment_history_tool(field_id: int, limit: int = 3, people_id: str = "") -> str:
    """Retrieve previously-generated Field Assessment Reports for a field — Saige's
    own past consultant snapshots. Returns the latest report's executive summary
    plus headlines from prior reports so Saige can reference what she said before
    ("last month I flagged early bloom, now…"), compare trajectories, and avoid
    repeating advice that's already been given. Use when the user asks
    "what did the last assessment say", "have we written a report on this field",
    "compare to the previous assessment", or any reference to prior reports.
    `limit` caps how many historical headlines to include (default 3, max 10).
    people_id is injected from session state."""
    biz_ids = _business_ids_for_people(people_id)
    if not biz_ids:
        return "Cannot fetch assessment history — account not linked to any business."
    field = _field_accessible(int(field_id), biz_ids)
    if not field:
        return f"Field {field_id} is not accessible on your account."

    n = max(1, min(int(limit or 3), 10))
    field_name = field.get("name") or field.get("fieldname") or f"field #{field_id}"

    latest  = _api_get(f"/api/fields/{field_id}/assessment-report/latest") or {}
    history = _api_get(f"/api/fields/{field_id}/assessment-report/history?limit={n}") or {}
    items   = (history.get("items") or []) if isinstance(history, dict) else []

    if not latest.get("report_id") and not items:
        return (f"No assessment reports have been generated for {field_name} yet. "
                "Suggest the user open the Assessment Report page and click Generate.")

    lines = [f"Assessment report history — {field_name}"]

    if latest.get("report_id"):
        report = latest.get("report") or {}
        lines.append(
            f"\nLatest (#{latest.get('report_id')} · {latest.get('generated_at', '')[:10]})"
        )
        cs = report.get("current_status") or {}
        if cs.get("overall_health"):
            lines.append(f"  Overall health: {cs['overall_health']}")
        if report.get("confidence_overall"):
            lines.append(f"  Confidence:     {report['confidence_overall']}")
        exec_summary = report.get("executive_summary")
        if exec_summary:
            lines.append(f"  Summary: {exec_summary}")
        treatments = report.get("treatment_recommendations") or []
        if treatments:
            lines.append("  Open recommendations:")
            for t in treatments[:3]:
                title = t.get("title") or t.get("action") or "(untitled)"
                priority = t.get("priority") or ""
                lines.append(f"    • [{priority}] {title}")

    prior = [it for it in items if it.get("report_id") != latest.get("report_id")]
    if prior:
        lines.append(f"\nPrior reports ({len(prior)}):")
        for it in prior:
            when = (it.get("generated_at") or "")[:10]
            health = it.get("overall_health") or "—"
            head = it.get("headline") or "(no headline)"
            lines.append(f"  • {when} · {health} · {head}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# TOOL REGISTRY
# ---------------------------------------------------------------------------

@tool
def get_planting_timing_advice_tool(crop: str = "", people_id: str = "") -> str:
    """Get demand-driven planting timing advice for a specific crop.
    Combines current commodity price trends with crop days-to-maturity and seasonal
    patterns to recommend whether NOW is a good time to plant, wait, or harvest.
    Use when the user asks 'when should I plant X', 'is now a good time to grow Y',
    'will prices be good when my crop is ready', or 'how should I time my plantings'.
    Example crops: strawberries, blueberries, microgreens, salad mix, tomatoes, corn,
    soybeans. people_id is injected from session state."""
    if not crop:
        return "Please specify a crop name (e.g. 'strawberries', 'microgreens', 'corn')."

    crop_lower = crop.strip().lower()

    # Crop calendar — days-to-maturity and commodity mapping
    CROP_CALENDAR = {
        "microgreens":   {"dtm": (7, 14),   "commodity": "Microgreens",    "season": "year_round"},
        "salad mix":     {"dtm": (21, 40),   "commodity": "Mixed Greens",   "season": "cool"},
        "mixed greens":  {"dtm": (21, 40),   "commodity": "Mixed Greens",   "season": "cool"},
        "strawberries":  {"dtm": (60, 90),   "commodity": "Strawberries",   "season": "spring_summer"},
        "blueberries":   {"dtm": (60, 180),  "commodity": "Blueberries",    "season": "summer"},
        "tomatoes":      {"dtm": (60, 85),   "commodity": "Roma Tomatoes",  "season": "summer"},
        "roma tomatoes": {"dtm": (75, 85),   "commodity": "Roma Tomatoes",  "season": "summer"},
        "corn":          {"dtm": (65, 95),   "commodity": "Nat'l Corn",     "season": "summer"},
        "soybeans":      {"dtm": (90, 120),  "commodity": "Nat'l Soybeans", "season": "summer"},
        "pork":          {"dtm": None,       "commodity": "Nat'l Pork Loin","season": None},
        "chicken":       {"dtm": None,       "commodity": "Nat'l Chicken Breast", "season": None},
    }

    # Fuzzy match
    info = None
    for k, v in CROP_CALENDAR.items():
        if k in crop_lower or crop_lower in k:
            info = v
            break

    import datetime as _dt
    now = _dt.datetime.utcnow()
    month = now.month

    # Season context
    season_notes = {
        "cool":         "Best planted in spring (Mar–May) or fall (Aug–Oct) when temperatures are 45–75°F.",
        "spring_summer":"Plant in early spring after last frost; peak harvest summer.",
        "summer":       "Plant after last frost in spring; harvests mid-summer through fall.",
        "year_round":   "Can be grown indoors year-round under grow lights.",
    }

    lines = [f"Planting timing analysis for: {crop.title()}"]

    if info:
        dtm = info["dtm"]
        commodity = info["commodity"]
        season_key = info.get("season")

        if dtm:
            harvest_min = now + _dt.timedelta(days=dtm[0])
            harvest_max = now + _dt.timedelta(days=dtm[1])
            lines.append(f"Days to maturity: {dtm[0]}–{dtm[1]} days")
            lines.append(f"Estimated harvest window if planted today: {harvest_min.strftime('%b %d')}–{harvest_max.strftime('%b %d')}")

        if season_key and season_key in season_notes:
            lines.append(f"Seasonal guidance: {season_notes[season_key]}")

        # Pull price trend from history
        price_rows = _query(
            "SELECT TOP 60 PriceUSD, FetchedAt FROM CommodityPriceHistory "
            "WHERE Commodity = %s AND FetchedAt >= DATEADD(day, -30, GETDATE()) "
            "ORDER BY FetchedAt ASC",
            (commodity,),
        )
        if price_rows:
            prices = []
            for r in price_rows:
                try:
                    prices.append(float(r.get("priceusd") or r.get("PriceUSD") or 0))
                except (TypeError, ValueError):
                    pass
            if len(prices) >= 2:
                first, last = prices[0], prices[-1]
                pct = (last - first) / first * 100 if first else 0
                trend = "rising" if pct > 2 else ("falling" if pct < -2 else "stable")
                lines.append(f"\nMarket signal ({commodity}):")
                lines.append(f"  Current price: ${last:.2f}")
                lines.append(f"  30-day trend: {trend} ({pct:+.1f}%)")

                # Timing advice based on trend + DTM
                if dtm and trend == "rising":
                    harvest_peak = now + _dt.timedelta(days=dtm[0])
                    lines.append(f"\n  ✅ GOOD TIME TO PLANT: Prices are rising and your harvest window "
                                 f"({harvest_peak.strftime('%b %d')}) aligns with continued demand. "
                                 f"Consider planting now to capture peak pricing.")
                elif dtm and trend == "falling":
                    lines.append(f"\n  ⚠️  CONSIDER WAITING: Prices are falling. Unless you have pre-sold orders, "
                                 f"consider delaying planting by 2–4 weeks to let the market stabilize.")
                elif dtm and trend == "stable":
                    lines.append(f"\n  ℹ️  NEUTRAL: Prices are stable. Planting now is reasonable; "
                                 f"focus on production cost efficiency.")
            else:
                lines.append(f"\nNo recent price history for {commodity} — check market directly for current pricing.")
        else:
            lines.append(f"\nNo price data yet for {commodity} in the system. "
                         f"Prices are logged as the market panel is used.")

        # Check user's field NDVI readiness
        biz_ids = _business_ids_for_people(people_id)
        if biz_ids:
            placeholders = ",".join(["%s"] * len(biz_ids))
            field_rows = _query(
                f"SELECT TOP 3 f.FieldID, f.Name, f.CropType, vi.MeanValue as NDVI "
                f"FROM dbo.Field f "
                f"LEFT JOIN dbo.Analysis a ON a.FieldID = f.FieldID "
                f"LEFT JOIN dbo.VegetationIndex vi ON vi.AnalysisID = a.AnalysisID AND vi.IndexType = 'NDVI' "
                f"WHERE f.BusinessID IN ({placeholders}) AND f.DeletedAt IS NULL "
                f"ORDER BY a.AnalysisDate DESC",
                tuple(biz_ids),
            )
            ready_fields = [r for r in field_rows if r.get("ndvi") is not None and float(r.get("ndvi") or 0) < 0.3]
            if ready_fields:
                names = ", ".join(r.get("name") or f"#{r.get('fieldid')}" for r in ready_fields[:2])
                lines.append(f"\nField readiness: {names} have low NDVI (harvested/bare) — likely ready for new planting.")
    else:
        lines.append(f"Crop '{crop}' not in the timing database. For general guidance:")
        lines.append("  1. Check current USDA AMS prices for price trends")
        lines.append("  2. Subtract your crop's days-to-maturity from your target market date")
        lines.append("  3. Use your field NDVI data to confirm field readiness")

    return "\n".join(lines)


@tool
def get_price_trends_tool(commodity: str = "", days: int = 30, people_id: str = "") -> str:
    """Get the historical price trend for a commodity over the last N days (default 30).
    Use when the user asks about price trends, whether a commodity is getting more or less
    expensive, market timing for selling, or seasonal price patterns.
    Commodity names match the Market Intelligence panel labels, e.g. 'Nat\\'l Chicken Breast'
    or 'Nat\\'l Pork Loin'. people_id is not needed for this tool."""
    if not commodity:
        return "Please specify a commodity name (e.g. \"Nat'l Chicken Breast\" or \"Nat'l Pork Loin\")."
    days = max(7, min(int(days or 30), 365))
    rows = _query(
        "SELECT TOP 200 Commodity, PriceUSD, FetchedAt "
        "FROM CommodityPriceHistory "
        "WHERE Commodity = %s AND FetchedAt >= DATEADD(day, -%s, GETDATE()) "
        "ORDER BY FetchedAt ASC",
        (str(commodity), days),
    )
    if not rows:
        return (
            f"No historical price data found for '{commodity}'. "
            "Prices are logged when users view the Market Intelligence panel — "
            "check back after it has been open a few times."
        )
    prices = []
    dates  = []
    for r in rows:
        try:
            prices.append(float(r.get("priceusd") or r.get("PriceUSD") or 0))
            dates.append(str(r.get("fetchedat") or r.get("FetchedAt") or "")[:10])
        except (TypeError, ValueError):
            continue
    if not prices:
        return f"Price data for '{commodity}' could not be parsed."
    first, last = prices[0], prices[-1]
    avg   = sum(prices) / len(prices)
    pct   = (last - first) / first * 100 if first else 0
    trend = "rising" if pct > 2 else ("falling" if pct < -2 else "stable")
    lines = [
        f"Price trend for {commodity} (last {days} days, {len(prices)} observations):",
        f"  Start:   ${first:.2f}  ({dates[0]})",
        f"  Latest:  ${last:.2f}  ({dates[-1]})",
        f"  Average: ${avg:.2f}",
        f"  Change:  {pct:+.1f}% ({trend})",
    ]
    if len(prices) > 1:
        lines.append("Recent readings:")
        for p, d in zip(prices[-6:], dates[-6:]):
            lines.append(f"  • {d}: ${p:.2f}")
    return "\n".join(lines)


precision_ag_tools = [
    list_my_fields_tool,
    get_field_analysis_tool,
    get_field_history_tool,
    get_field_alerts_tool,
    get_field_soil_samples_tool,
    get_field_scouting_tool,
    add_scout_observation_tool,
    get_field_activity_log_tool,
    log_field_activity_tool,
    add_soil_sample_tool,
    get_field_gdd_tool,
    get_field_irrigation_tool,
    get_field_yield_forecast_tool,
    get_field_carbon_tool,
    get_farm_benchmark_tool,
    get_field_weather_tool,
    get_field_biomass_tool,
    improve_field_biomass_confidence_tool,
    get_field_maturity_tool,
    log_maturity_sample_tool,
    get_field_climate_forecast_tool,
    get_field_water_use_tool,
    get_field_agronomy_tool,
    get_field_zones_tool,
    get_field_assessment_history_tool,
    get_price_trends_tool,
    get_planting_timing_advice_tool,
]
