"""
Event discovery tools for Saige.

Exposes farm-event information (upcoming events, event details, attendee
counts) to the LLM agent so users can ask questions like:
  - "What events are coming up at Shady Oak Farm?"
  - "How many people are registered for the spring shearing?"
  - "Tell me about event 42."

Tools call the main OFN backend HTTP API rather than querying the database
directly — this keeps event business logic (publish/sold-out/etc.) in one
place.
"""
from __future__ import annotations

import os
from typing import Optional
import requests
from langchain_core.tools import tool


BACKEND_URL = os.getenv("OFN_BACKEND_URL", "http://localhost:8000").rstrip("/")
HTTP_TIMEOUT = 5


def _fmt_date(iso: Optional[str]) -> str:
    if not iso:
        return "TBD"
    return str(iso).split("T")[0]


def _fmt_money(v) -> str:
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_event_line(ev: dict) -> str:
    name = ev.get("EventName") or ev.get("Title") or f"Event {ev.get('EventID')}"
    host = ev.get("BusinessName") or ""
    start = _fmt_date(ev.get("EventStartDate") or ev.get("StartDate"))
    end = _fmt_date(ev.get("EventEndDate") or ev.get("EndDate"))
    loc = ev.get("Location") or ev.get("City") or ""
    fee = ev.get("RegistrationFee")
    date_part = start if start == end or not end or end == "TBD" else f"{start} → {end}"
    parts = [f"#{ev.get('EventID')} — {name}"]
    if host:
        parts.append(f"hosted by {host}")
    parts.append(date_part)
    if loc:
        parts.append(loc)
    if fee is not None:
        parts.append(_fmt_money(fee))
    return " · ".join(parts)


@tool
def list_upcoming_events_tool(business_id: int = 0, limit: int = 10) -> str:
    """List upcoming published farm events on OatmealFarmNetwork.
    Optionally filter by business_id (a farm/ranch's BusinessID) to show only
    that farm's upcoming events. Pass business_id=0 to list events across all
    farms. Returns event ID, name, host farm, date, location, and registration
    fee. Use when the user asks "what's coming up", "what events are at
    [farm]", "upcoming clinics/auctions/tours"."""
    params = {"limit": max(1, min(int(limit or 10), 50))}
    if business_id and int(business_id) > 0:
        params["business_id"] = int(business_id)
    try:
        r = requests.get(f"{BACKEND_URL}/api/events", params=params, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        events = r.json() or []
    except Exception as e:
        return f"Could not fetch events ({e})."
    if not events:
        scope = f" for business {business_id}" if business_id else ""
        return f"No upcoming published events found{scope}."
    lines = [f"Upcoming events ({len(events)}):"]
    for ev in events:
        lines.append(f"  • {_fmt_event_line(ev)}")
    return "\n".join(lines)


@tool
def get_event_details_tool(event_id: int) -> str:
    """Get full details for a specific farm event by event_id — name, host,
    description, dates, location, registration fee, capacity, attendee count.
    Use when the user asks about a specific event by name or ID, or wants
    details like "when is the spring shearing", "where is event 42", "is there
    still space at the goat clinic"."""
    if not event_id or int(event_id) <= 0:
        return "Event ID is required."
    try:
        r = requests.get(f"{BACKEND_URL}/api/events/{int(event_id)}", timeout=HTTP_TIMEOUT)
        if r.status_code == 404:
            return f"Event {event_id} not found."
        r.raise_for_status()
        ev = r.json() or {}
    except Exception as e:
        return f"Could not fetch event {event_id} ({e})."

    name = ev.get("EventName") or ev.get("Title") or f"Event {event_id}"
    host = ev.get("BusinessName") or "Unknown host"
    start = _fmt_date(ev.get("EventStartDate") or ev.get("StartDate"))
    end = _fmt_date(ev.get("EventEndDate") or ev.get("EndDate"))
    loc = ev.get("Location") or ev.get("Address") or ev.get("City") or "Location TBD"
    fee = ev.get("RegistrationFee")
    capacity = ev.get("Capacity") or ev.get("MaxAttendees")
    registered = ev.get("RegisteredCount") or ev.get("AttendeeCount")
    desc = (ev.get("Description") or "").strip()

    lines = [f"{name}", f"Hosted by: {host}"]
    lines.append(f"Dates: {start}" + (f" → {end}" if end and end != start else ""))
    lines.append(f"Location: {loc}")
    if fee is not None:
        lines.append(f"Registration fee: {_fmt_money(fee)}")
    if capacity is not None:
        reg_txt = f"{registered}" if registered is not None else "?"
        lines.append(f"Capacity: {reg_txt} / {capacity} registered")
    elif registered is not None:
        lines.append(f"Registered: {registered}")
    if desc:
        short = desc if len(desc) <= 400 else desc[:400].rstrip() + "…"
        lines.append(f"About: {short}")
    return "\n".join(lines)


@tool
def event_attendee_count_tool(event_id: int) -> str:
    """Return how many people are registered for a specific event.
    Use when the user asks "how many registered", "is it sold out", "how full
    is the event". Provide event_id."""
    if not event_id or int(event_id) <= 0:
        return "Event ID is required."
    try:
        r = requests.get(f"{BACKEND_URL}/api/events/{int(event_id)}", timeout=HTTP_TIMEOUT)
        if r.status_code == 404:
            return f"Event {event_id} not found."
        r.raise_for_status()
        ev = r.json() or {}
    except Exception as e:
        return f"Could not fetch event {event_id} ({e})."
    registered = ev.get("RegisteredCount") or ev.get("AttendeeCount") or 0
    capacity = ev.get("Capacity") or ev.get("MaxAttendees")
    name = ev.get("EventName") or ev.get("Title") or f"Event {event_id}"
    if capacity:
        pct = int(round((float(registered) / float(capacity)) * 100)) if capacity else 0
        status = "SOLD OUT" if registered >= capacity else f"{pct}% full"
        return f"{name}: {registered} of {capacity} registered ({status})."
    return f"{name}: {registered} registered (no capacity limit set)."


event_tools = [
    list_upcoming_events_tool,
    get_event_details_tool,
    event_attendee_count_tool,
]
