# --- user_profile.py --- (User name + org membership lookup for Saige)
"""
Fetches the logged-in user's name and their organization's member list from
the OFN SQL Server database. Used to personalise Saige's prompts.

Tables used (read-only):
  People        — PeopleID, PeopleFirstName, PeopleLastName
  BusinessAccess — BusinessID, PeopleID, Active
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Any

from config import DB_CONFIG

try:
    import pymssql
    _PYMSSQL_OK = True
except ImportError:
    _PYMSSQL_OK = False

logger = logging.getLogger("farm_advisory.user_profile")


def _connect():
    if not _PYMSSQL_OK or not all([
        DB_CONFIG.get("host"), DB_CONFIG.get("user"), DB_CONFIG.get("database")
    ]):
        return None
    try:
        return pymssql.connect(
            server=DB_CONFIG["host"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
            database=DB_CONFIG["database"],
            timeout=8,
            login_timeout=8,
        )
    except Exception as e:
        logger.debug("[user_profile] DB connect failed: %s", e)
        return None


def _query(sql: str, params: tuple) -> List[Dict]:
    conn = _connect()
    if not conn:
        return []
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(sql, params)
        return list(cur.fetchall() or [])
    except Exception as e:
        logger.error("[user_profile] query error: %s", e)
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def get_user_name(people_id: str) -> Optional[str]:
    """Return 'FirstName LastName' for a PeopleID, or None if not found/unavailable."""
    if not people_id:
        return None
    rows = _query(
        "SELECT PeopleFirstName, PeopleLastName FROM People WHERE PeopleID = %s",
        (int(people_id),),
    )
    if not rows:
        return None
    first = (rows[0].get("PeopleFirstName") or "").strip()
    last = (rows[0].get("PeopleLastName") or "").strip()
    full = f"{first} {last}".strip()
    return full or None


def get_user_email(people_id: str) -> Optional[str]:
    """Return the account email for a PeopleID, or None if not found/unavailable."""
    if not people_id:
        return None
    rows = _query(
        "SELECT PeopleEmail FROM People WHERE PeopleID = %s",
        (int(people_id),),
    )
    if not rows:
        return None
    email = (rows[0].get("PeopleEmail") or "").strip()
    return email or None


def get_full_name(people_id: str) -> Optional[str]:
    """Return the full name for a PeopleID, or None if not found/unavailable."""
    if not people_id:
        return None
    rows = _query(
        "SELECT PeopleFirstName, PeopleLastName FROM People WHERE PeopleID = %s",
        (int(people_id),),
    )
    if not rows:
        return None
    first = (rows[0].get("PeopleFirstName") or "").strip()
    last = (rows[0].get("PeopleLastName") or "").strip()
    full = f"{first} {last}".strip()
    return full or None


def get_phone(people_id: str) -> Optional[str]:
    """Return the phone number for a PeopleID, or None if not found/unavailable."""
    if not people_id:
        return None
    rows = _query(
        "SELECT PeoplePhone FROM People WHERE PeopleID = %s",
        (int(people_id),),
    )
    if not rows:
        return None
    phone = (rows[0].get("PeoplePhone") or "").strip()
    return phone or None


def get_address(people_id: str) -> Optional[str]:
    """Return a formatted address string for a PeopleID, or None if not found/unavailable."""
    if not people_id:
        return None
    rows = _query(
        "SELECT PeopleAddress, PeopleCity, PeopleState, PeopleZip, PeopleCountry FROM People WHERE PeopleID = %s",
        (int(people_id),),
    )
    if not rows:
        return None
    address_parts = [
        (rows[0].get("PeopleAddress") or "").strip(),
        (rows[0].get("PeopleCity") or "").strip(),
        (rows[0].get("PeopleState") or "").strip(),
        (rows[0].get("PeopleZip") or "").strip(),
        (rows[0].get("PeopleCountry") or "").strip(),
    ]
    address = ", ".join([p for p in address_parts if p]).strip() or None
    return address


def get_location(people_id: str) -> Optional[str]:
    """Return the location/address string for a PeopleID, or None if not found/unavailable."""
    return get_address(people_id)


def get_account_status(people_id: str) -> Optional[str]:
    """Return the account status for a PeopleID, or None if not found/unavailable."""
    if not people_id:
        return None
    rows = _query(
        "SELECT PeopleStatus FROM People WHERE PeopleID = %s",
        (int(people_id),),
    )
    if not rows:
        return None
    status = (rows[0].get("PeopleStatus") or "").strip()
    return status or None


def get_last_login(people_id: str) -> Optional[str]:
    """Return the last login value for a PeopleID, or None if not found/unavailable."""
    if not people_id:
        return None
    rows = _query(
        "SELECT LastLoginDate FROM People WHERE PeopleID = %s",
        (int(people_id),),
    )
    if not rows:
        return None
    last_login = rows[0].get("LastLoginDate")
    return str(last_login) if last_login is not None else None


def get_timezone(people_id: str) -> Optional[str]:
    """Return the timezone for a PeopleID, or None if not found/unavailable."""
    if not people_id:
        return None
    rows = _query(
        "SELECT PeopleTimezone FROM People WHERE PeopleID = %s",
        (int(people_id),),
    )
    if not rows:
        return None
    timezone = (rows[0].get("PeopleTimezone") or "").strip()
    return timezone or None


def get_org_member_ids(business_id: str) -> List[str]:
    """Return list of PeopleID strings for all active members of a business/org."""
    if not business_id:
        return []
    rows = _query(
        "SELECT PeopleID FROM BusinessAccess WHERE BusinessID = %s AND Active = 1",
        (int(business_id),),
    )
    return [str(r["PeopleID"]) for r in rows if r.get("PeopleID")]


def get_business_name(business_id: str) -> Optional[str]:
    """Return the BusinessName for a given BusinessID, or None if not found."""
    if not business_id:
        return None
    rows = _query(
        "SELECT BusinessName FROM Business WHERE BusinessID = %s",
        (int(business_id),),
    )
    if not rows:
        return None
    name = rows[0].get("BusinessName") or rows[0].get("businessname")
    return str(name).strip() if name else None


def get_business_email(business_id: str) -> Optional[str]:
    """Return the business contact email for a BusinessID."""
    if not business_id:
        return None
    rows = _query(
        "SELECT BusinessEmail FROM Business WHERE BusinessID = %s",
        (int(business_id),),
    )
    if not rows:
        return None
    email = (rows[0].get("BusinessEmail") or "").strip()
    return email or None


def get_business_address(business_id: str) -> Optional[str]:
    """Return formatted business address from the Address table."""
    if not business_id:
        return None
    rows = _query(
        """
        SELECT a.AddressStreet, a.AddressCity, a.AddressState,
               a.AddressZip, a.AddressCountry
        FROM Business b
        LEFT JOIN Address a ON a.AddressID = b.AddressID
        WHERE b.BusinessID = %s
        """,
        (int(business_id),),
    )
    if not rows:
        return None
    r = rows[0]
    parts = [
        (r.get("AddressStreet") or "").strip(),
        (r.get("AddressCity") or "").strip(),
        (r.get("AddressState") or "").strip(),
        (r.get("AddressZip") or "").strip(),
        (r.get("AddressCountry") or "").strip(),
    ]
    address = ", ".join(p for p in parts if p)
    return address or None


def get_business_weather_coords(business_id: str) -> Optional[Dict[str, Any]]:
    """Return saved GPS coordinates from BusinessLocation (same table as main weather API)."""
    if not business_id:
        return None
    rows = _query(
        """
        SELECT Latitude, Longitude, LocationName, Timezone
        FROM BusinessLocation
        WHERE BusinessID = %s
        """,
        (int(business_id),),
    )
    if not rows:
        return None
    r = rows[0]
    lat = r.get("Latitude")
    lon = r.get("Longitude")
    if lat is None or lon is None:
        return None
    return {
        "latitude": float(lat),
        "longitude": float(lon),
        "location_name": (r.get("LocationName") or "").strip() or None,
        "timezone": (r.get("Timezone") or "auto").strip(),
    }


def get_business_location(business_id: str) -> Optional[str]:
    """Return city/state/country for a business, used for weather and regional advice."""
    if not business_id:
        return None
    rows = _query(
        """
        SELECT a.AddressCity, a.AddressState, a.AddressCountry
        FROM Business b
        LEFT JOIN Address a ON a.AddressID = b.AddressID
        WHERE b.BusinessID = %s
        """,
        (int(business_id),),
    )
    if not rows:
        return None
    r = rows[0]
    parts = [
        (r.get("AddressCity") or r.get("addresscity") or "").strip(),
        (r.get("AddressState") or r.get("addressstate") or "").strip(),
        (r.get("AddressCountry") or r.get("addresscountry") or "").strip(),
    ]
    loc = ", ".join(p for p in parts if p)
    return loc or None


def get_primary_business_id(people_id: str) -> Optional[str]:
    """Return the first active BusinessID for this PeopleID, or None if none found."""
    if not people_id:
        return None
    rows = _query(
        "SELECT TOP 1 BusinessID FROM BusinessAccess WHERE PeopleID = %s AND Active = 1 ORDER BY BusinessID",
        (int(people_id),),
    )
    if not rows:
        return None
    bid = rows[0].get("BusinessID") or rows[0].get("businessid")
    return str(bid) if bid else None


def get_org_member_names(business_id: str) -> Dict[str, str]:
    """Return {people_id: 'First Last'} for all active org members."""
    if not business_id:
        return {}
    rows = _query(
        """
        SELECT p.PeopleID, p.PeopleFirstName, p.PeopleLastName
        FROM BusinessAccess ba
        JOIN People p ON ba.PeopleID = p.PeopleID
        WHERE ba.BusinessID = %s AND ba.Active = 1
        """,
        (int(business_id),),
    )
    result: Dict[str, str] = {}
    for r in rows:
        pid = str(r.get("PeopleID") or "")
        first = (r.get("PeopleFirstName") or "").strip()
        last = (r.get("PeopleLastName") or "").strip()
        name = f"{first} {last}".strip()
        if pid and name:
            result[pid] = name
    return result


def get_safe_profile(people_id: str) -> Dict[str, Optional[str] | List[str] | Dict[str, str]]:
    """Return a non-sensitive profile summary for Saige.

    This intentionally excludes password hashes, credentials, tokens, and other
    secrets. It returns only fields that are appropriate to share with an
    authenticated user or guest with appropriate access.
    """
    if not people_id:
        return {}

    rows = _query(
        """
        SELECT
            PeopleID,
            PeopleFirstName,
            PeopleLastName,
            PeopleEmail,
            PeoplePhone,
            PeopleAddress,
            PeopleCity,
            PeopleState,
            PeopleZip,
            PeopleCountry,
            PeopleTimezone,
            PeopleStatus,
            LastLoginDate,
            PeopleUserName
        FROM People
        WHERE PeopleID = %s
        """,
        (int(people_id),),
    )
    if not rows:
        return {}

    row = rows[0]
    people_id = str(row.get("PeopleID")) if row.get("PeopleID") is not None else None
    first = (row.get("PeopleFirstName") or "").strip()
    last = (row.get("PeopleLastName") or "").strip()
    email = (row.get("PeopleEmail") or "").strip()
    phone = get_phone(people_id) if people_id else None
    address = get_address(people_id) if people_id else None
    location = address
    timezone = get_timezone(people_id) if people_id else None
    account_status = get_account_status(people_id) if people_id else None
    last_login = get_last_login(people_id) if people_id else None
    user_name = (row.get("PeopleUserName") or "").strip() or None
    business_id = get_primary_business_id(people_id) if people_id else None
    business_name = get_business_name(str(business_id)) if business_id else None
    business_email = get_business_email(str(business_id)) if business_id else None
    business_address = get_business_address(str(business_id)) if business_id else None
    org_member_ids = get_org_member_ids(str(business_id)) if business_id else []
    org_member_names = get_org_member_names(str(business_id)) if business_id else {}

    profile: Dict[str, Optional[str] | List[str] | Dict[str, str]] = {
        "people_id": people_id,
        "full_name": get_full_name(people_id) if people_id else f"{first} {last}".strip() or None,
        "user_name": user_name,
        "first_name": first or None,
        "last_name": last or None,
        "email": email or None,
        "phone": phone,
        "address": address,
        "location": location,
        "business_id": business_id,
        "business_name": business_name,
        "business_email": business_email,
        "business_address": business_address,
        "primary_business_id": business_id,
        "org_member_ids": org_member_ids,
        "org_member_names": org_member_names,
        "account_status": account_status,
        "last_login": last_login,
        "timezone": timezone,
    }

    blocked_keys = {
        "password",
        "password_hash",
        "passwordsalt",
        "pwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "auth_token",
        "session_key",
        "sessionid",
    }
    return {k: v for k, v in profile.items() if k not in blocked_keys}
