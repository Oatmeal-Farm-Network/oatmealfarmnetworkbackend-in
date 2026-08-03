"""
Weather signal engine.

Reads push subscriptions that have a `location` attached, fetches the
forecast for each unique location, evaluates hazard thresholds, and sends
a push with a deep-link to the matching weather-mitigation phase.

Designed to be triggered from a cron / scheduled task hitting the REST
endpoint `POST /alerts/weather/run`. Per-user dry-run is also supported
via `POST /alerts/weather/check/{user_id}`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

try:
    from weather import weather_service
    _WEATHER_AVAILABLE = True
except Exception as _e:
    print(f"[weather_alerts] weather unavailable: {_e}")
    weather_service = None
    _WEATHER_AVAILABLE = False

try:
    import push_notifications as push
except Exception as _e:
    print(f"[weather_alerts] push unavailable: {_e}")
    push = None


# --------------------------------------------------------------------
# Thresholds (Celsius — WeatherAPI.com returns metric by default)
# --------------------------------------------------------------------
FROST_MAX_C       = 0.0     # day's min ≤ 0°C → frost
HARD_FREEZE_C     = -4.0    # severe cold snap
HEAT_MIN_C        = 35.0    # day's max ≥ 35°C → heat stress
HEAVY_RAIN_CHANCE = 80      # % chance → flood risk
HAIL_KEYWORDS     = ("hail", "ice pellets", "sleet")
HIGH_WIND_KMH     = 50      # gusts/sustained wind
SMOKE_KEYWORDS    = ("smoke", "wildfire")


def _classify_day(day: Dict[str, Any]) -> List[Tuple[str, str, str]]:
    """Return a list of (hazard_key, phase_key, human_reason) tuples."""
    hits: List[Tuple[str, str, str]] = []
    min_t = day.get("min_temp")
    max_t = day.get("max_temp")
    cond  = (day.get("condition") or "").lower()
    rain  = day.get("rain_chance") or 0
    wind  = day.get("max_wind_kmh") or day.get("wind_kmh") or 0

    if isinstance(min_t, (int, float)):
        if min_t <= HARD_FREEZE_C:
            hits.append(("cold_snap", "imminent",
                         f"Overnight low {min_t}°C — hard freeze"))
        elif min_t <= FROST_MAX_C:
            hits.append(("frost", "imminent",
                         f"Overnight low {min_t}°C — frost likely"))

    if isinstance(max_t, (int, float)) and max_t >= HEAT_MIN_C:
        hits.append(("heat", "imminent",
                     f"Daytime high {max_t}°C — heat stress"))

    if rain >= HEAVY_RAIN_CHANCE:
        hits.append(("flood", "imminent",
                     f"{rain}% precipitation — flood risk"))

    if any(k in cond for k in HAIL_KEYWORDS):
        hits.append(("hail", "imminent", f"Forecast: {day.get('condition')}"))

    if any(k in cond for k in SMOKE_KEYWORDS):
        hits.append(("wildfire_smoke", "imminent",
                     f"Forecast: {day.get('condition')}"))

    if isinstance(wind, (int, float)) and wind >= HIGH_WIND_KMH:
        hits.append(("wind", "imminent", f"Wind {wind} km/h"))

    return hits


def _location_key(loc: Dict[str, Any]) -> str:
    """Stable key for deduping location lookups across subscriptions."""
    if not loc:
        return ""
    if loc.get("lat") is not None and loc.get("lon") is not None:
        return f"{round(float(loc['lat']), 3)},{round(float(loc['lon']), 3)}"
    return (loc.get("label") or "").strip().lower()


def _location_query(loc: Dict[str, Any]) -> str:
    """Build the query string the weather service wants."""
    if loc.get("lat") is not None and loc.get("lon") is not None:
        return f"{loc['lat']},{loc['lon']}"
    return loc.get("label") or ""


def _deep_link(hazard: str, phase: str) -> str:
    return f"/saige/weather-mitigation?hazard={hazard}&phase={phase}"


def _format_title(hazard: str, reason: str) -> str:
    human = {
        "frost": "Frost warning",
        "cold_snap": "Hard freeze warning",
        "heat": "Heat stress warning",
        "flood": "Heavy rain / flood risk",
        "hail": "Hail in forecast",
        "wind": "High wind advisory",
        "wildfire_smoke": "Wildfire smoke nearby",
    }.get(hazard, f"Weather alert: {hazard}")
    return human


def run(dry_run: bool = False, days_ahead: int = 2,
        user_id: Optional[str] = None) -> Dict[str, Any]:
    """Scan subscriptions, evaluate hazards, send alerts.

    dry_run: when True, return what *would* be sent without sending.
    days_ahead: how many forecast days to scan (default next 48h).
    user_id: if set, only evaluate that user's subscriptions.
    """
    if not _WEATHER_AVAILABLE or weather_service is None:
        return {"status": "error", "message": "weather service unavailable"}
    if push is None:
        return {"status": "error", "message": "push module unavailable"}

    subs = push.list_subscriptions(user_id=user_id)
    subs = [s for s in subs if s.get("location")]
    if not subs:
        return {"status": "ok", "scanned": 0, "sent": 0, "messages": []}

    # Group subs by location so we only call the weather API once per place.
    by_loc: Dict[str, List[Dict[str, Any]]] = {}
    loc_objs: Dict[str, Dict[str, Any]] = {}
    for s in subs:
        loc = s["location"]
        key = _location_key(loc)
        if not key:
            continue
        by_loc.setdefault(key, []).append(s)
        loc_objs[key] = loc

    messages: List[Dict[str, Any]] = []
    sent_count = 0
    today = datetime.utcnow().date().isoformat()

    for key, sublist in by_loc.items():
        loc = loc_objs[key]
        query = _location_query(loc)
        forecast = weather_service.get_forecast(query, days=max(1, days_ahead))
        if not forecast or not forecast.get("forecast"):
            continue

        for day in forecast["forecast"][:days_ahead]:
            hits = _classify_day(day)
            if not hits:
                continue

            for hazard, phase, reason in hits:
                title = _format_title(hazard, reason)
                body  = f"{reason} on {day.get('date', 'the forecast window')} — tap for mitigation steps."
                url   = _deep_link(hazard, phase)
                tag_parts = ["wx", hazard, day.get("date", today)]
                dedupe_tag = ":".join(str(p) for p in tag_parts)

                for s in sublist:
                    msg_record = {
                        "user_id": s.get("user_id"),
                        "endpoint": s.get("endpoint"),
                        "hazard": hazard,
                        "phase": phase,
                        "date": day.get("date"),
                        "title": title,
                        "body": body,
                        "url": url,
                        "dedupe_tag": dedupe_tag,
                    }
                    if dry_run:
                        msg_record["status"] = "dry_run"
                    else:
                        r = push.send_to(
                            user_id=s.get("user_id"),
                            title=title,
                            body=body,
                            url=url,
                            extra={"hazard": hazard, "phase": phase,
                                   "tag": dedupe_tag},
                        )
                        msg_record["status"] = r.get("status")
                        if r.get("status") == "ok":
                            sent_count += 1
                    messages.append(msg_record)

    return {
        "status": "ok",
        "scanned": len(subs),
        "locations": len(by_loc),
        "sent": sent_count,
        "dry_run": dry_run,
        "messages": messages,
    }


# ──────────────────────────────────────────────────────────────────
# LLM tool — let Saige tell the user what hazards are in their forecast
# ──────────────────────────────────────────────────────────────────
from langchain_core.tools import tool


@tool
def check_my_weather_alerts_tool(days_ahead: int = 2, people_id: str = "") -> str:
    """Check the user's saved push-notification locations against the
    weather forecast and report any hazards (frost, hard freeze, heat
    stress, heavy rain / flood, hail, high wind, wildfire smoke) in the
    next `days_ahead` days. Use when the user asks "what's the weather
    risk this week?", "any frost coming?", "should I worry about
    weather?", or any preventive-planning question that depends on
    upcoming hazards. Read-only — does NOT actually send a push.
    days_ahead: 1 to 5 (default 2). people_id is injected from session
    state — do not guess it."""
    if not _WEATHER_AVAILABLE:
        return "Weather service isn't configured on this server."
    if push is None:
        return "Push subscription store isn't configured on this server."
    if not people_id:
        return ("I can't check your forecast without knowing who you "
                "are. Sign in and try again.")
    n = max(1, min(int(days_ahead or 2), 5))
    result = run(dry_run=True, days_ahead=n, user_id=str(people_id))
    if result.get("status") != "ok":
        return f"Weather alert check failed: {result.get('message', 'unknown error')}"
    if result.get("scanned", 0) == 0:
        return ("You haven't saved any locations to your push "
                "notifications yet, so I can't check a local forecast. "
                "Open the OFN web app, enable notifications, and add a "
                "farm location.")
    msgs = result.get("messages") or []
    if not msgs:
        return (f"No hazards in the next {n} day(s) for your "
                f"{result.get('locations', 0)} saved location(s). "
                f"Looks clear.")
    by_date: Dict[str, List[str]] = {}
    for m in msgs:
        date = m.get("date") or "soon"
        by_date.setdefault(date, []).append(
            f"{m.get('title')} — {m.get('body')}"
        )
    out = [f"Weather hazards in the next {n} day(s):"]
    for date in sorted(by_date.keys()):
        out.append(f"  {date}:")
        for line in by_date[date]:
            out.append(f"    • {line}")
    return "\n".join(out)


weather_alert_tools = [check_my_weather_alerts_tool]
