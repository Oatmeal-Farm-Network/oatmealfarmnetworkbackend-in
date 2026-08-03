# --- weather.py --- (Weather service + LangChain tool)
import os
import re
import time
from difflib import SequenceMatcher
from typing import Optional, Dict, Any, List
from langchain_core.tools import tool
from config import WEATHER_AVAILABLE

if WEATHER_AVAILABLE:
    import requests

# National Weather Service (api.weather.gov) is a free, keyless, official US
# government API — no signup required. It requires a descriptive User-Agent.
_NWS_HEADERS = {
    "User-Agent": "OatmealFarmNetwork-Saige/1.0 (contact: support@oatmealfarmnetwork.com)",
    "Accept": "application/geo+json",
}

# Open-Meteo (open-meteo.com) is a free, keyless, global weather + geocoding
# API. Used as (a) the geocoder for NWS lookups and (b) a worldwide fallback
# for locations outside NWS coverage (i.e. outside the USA).
_OPEN_METEO_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather-code -> plain-English condition (used by Open-Meteo).
_WMO_CODE_TEXT = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    56: "Light freezing drizzle", 57: "Dense freezing drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Heavy freezing rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}


class WeatherService:
    """Weather service for fetching current and forecast data from weather APIs."""

    def __init__(self):
        self._api_key = os.getenv("WEATHER_API_KEY", "").strip()
        # Default: match main backend `routers/weather.py` (Open-Meteo only, °F/mph).
        # Set WEATHER_API_PROVIDER=nws to use NWS-first with Open-Meteo fallback.
        # WEATHER_API_KEY only matters for "openweathermap" or "weatherapi".
        self._provider = os.getenv("WEATHER_API_PROVIDER", "openmeteo").strip().lower()
        self._cache = {}
        self._cache_ttl = 300  # 5 minutes
        self._use_fahrenheit = self._provider == "openmeteo"
        self._available = WEATHER_AVAILABLE and (
            self._provider in ("nws", "openmeteo") or bool(self._api_key)
        )

    def _is_cache_valid(self, location: str) -> bool:
        """Check if cached data is still valid."""
        if location not in self._cache:
            return False
        data, timestamp = self._cache[location]
        return (time.time() - timestamp) < self._cache_ttl

    def _get_from_cache(self, location: str) -> Optional[Dict[str, Any]]:
        """Get weather data from cache if valid."""
        if self._is_cache_valid(location):
            return self._cache[location][0]
        return None

    def _save_to_cache(self, location: str, data: Dict[str, Any]):
        """Save weather data to cache."""
        self._cache[location] = (data, time.time())

    def _open_meteo_unit_params(self) -> Dict[str, str]:
        """Fahrenheit + mph when using Open-Meteo directly."""
        if self._use_fahrenheit:
            return {"temperature_unit": "fahrenheit", "wind_speed_unit": "mph"}
        return {}

    def _temp_label(self) -> str:
        return "F" if self._use_fahrenheit else "C"

    def _wind_label(self) -> str:
        return "mph" if self._use_fahrenheit else "km/h"

    @staticmethod
    def _normalize_location_text(text: str) -> str:
        cleaned = re.sub(r"[^a-z0-9\s,\-]", " ", (text or "").lower())
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,")
        return cleaned

    @staticmethod
    def _sanitize_location_query(text: str) -> str:
        """Remove temporal phrasing that frequently pollutes place extraction.

        Example: "Des Moines this week" -> "Des Moines"
        """
        cleaned = re.sub(r"\s+", " ", (text or "").strip())
        # Strip common time-range phrases that are not part of place names.
        cleaned = re.sub(
            r"\b(?:this|next|coming)\s+(?:week|weeks|day|days|month|months|year|years)\b",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"\b(?:today|tonight|tomorrow|now|currently|current)\b",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,")
        return cleaned

    @staticmethod
    def _collapse_location_text(text: str) -> str:
        return re.sub(r"[^a-z0-9]", "", (text or "").lower())

    @staticmethod
    def _build_display_name(city: str, state: str, country: str) -> str:
        parts = [part for part in [city, state, country] if part]
        return ", ".join(parts)

    def _generate_location_queries(self, location_query: str, max_queries: int = 5) -> List[str]:
        """
        Generate normalized location query variants without word-block lists.
        Example: "sanjose now" -> ["sanjose now", "sanjose", "now"]
        """
        normalized = self._normalize_location_text(self._sanitize_location_query(location_query))
        tokens = [tok for tok in re.split(r"[\s,]+", normalized) if tok]
        if not tokens:
            return [location_query.strip()]

        queries: List[str] = []

        def _push(q: str):
            q = q.strip()
            if q and q not in queries:
                queries.append(q)

        _push(" ".join(tokens))
        if len(tokens) > 1:
            for end in range(len(tokens) - 1, 0, -1):
                _push(" ".join(tokens[:end]))
            for start in range(1, len(tokens)):
                _push(" ".join(tokens[start:]))

        return queries[:max_queries]

    def _fetch_openweathermap_geocode(self, location_query: str, limit: int = 5) -> List[Dict[str, Any]]:
        if not self._api_key:
            return []
        try:
            geo_url = "http://api.openweathermap.org/geo/1.0/direct"
            geo_params = {"q": location_query, "limit": limit, "appid": self._api_key}
            geo_response = requests.get(geo_url, params=geo_params, timeout=5)
            if geo_response.status_code != 200:
                print(f"[Weather] Geo API error: {geo_response.status_code}")
                return []

            entries = geo_response.json() or []
            results: List[Dict[str, Any]] = []
            for entry in entries:
                city = entry.get("name", "")
                state = entry.get("state", "")
                country = entry.get("country", "")
                results.append(
                    {
                        "city": city,
                        "state": state,
                        "country": country,
                        "display_name": self._build_display_name(city, state, country),
                        "lat": entry.get("lat"),
                        "lon": entry.get("lon"),
                    }
                )
            return results
        except Exception as e:
            print(f"[Weather] OpenWeatherMap geocode error: {e}")
            return []

    def _fetch_weatherapi_geocode(self, location_query: str, limit: int = 5) -> List[Dict[str, Any]]:
        if not self._api_key:
            return []
        try:
            url = "https://api.weatherapi.com/v1/search.json"
            params = {"key": self._api_key, "q": location_query}
            response = requests.get(url, params=params, timeout=5)
            if response.status_code != 200:
                print(f"[Weather] WeatherAPI search error: {response.status_code}")
                return []

            entries = (response.json() or [])[:limit]
            results: List[Dict[str, Any]] = []
            for entry in entries:
                city = entry.get("name", "")
                state = entry.get("region", "")
                country = entry.get("country", "")
                results.append(
                    {
                        "city": city,
                        "state": state,
                        "country": country,
                        "display_name": self._build_display_name(city, state, country),
                        "lat": entry.get("lat"),
                        "lon": entry.get("lon"),
                    }
                )
            return results
        except Exception as e:
            print(f"[Weather] WeatherAPI search error: {e}")
            return []

    def _fetch_open_meteo_geocode(self, location_query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Free, keyless geocoding via Open-Meteo — used for the "nws" provider."""
        try:
            params = {"name": location_query, "count": limit, "language": "en", "format": "json"}
            response = requests.get(_OPEN_METEO_GEOCODE_URL, params=params, timeout=5)
            if response.status_code != 200:
                print(f"[Weather] Open-Meteo geocode error: {response.status_code}")
                return []

            entries = (response.json() or {}).get("results") or []
            results: List[Dict[str, Any]] = []
            for entry in entries[:limit]:
                city = entry.get("name", "")
                state = entry.get("admin1", "")
                country = entry.get("country_code", "") or entry.get("country", "")
                results.append(
                    {
                        "city": city,
                        "state": state,
                        "country": country,
                        "display_name": self._build_display_name(city, state, country),
                        "lat": entry.get("latitude"),
                        "lon": entry.get("longitude"),
                    }
                )
            return results
        except Exception as e:
            print(f"[Weather] Open-Meteo geocode error: {e}")
            return []

    def _geocode_best(self, location: str) -> Optional[Dict[str, Any]]:
        """Resolve a location string to a single best lat/lon/city/state.

        Open-Meteo's raw geocoder only matches bare city names ("Austin"), not
        "City, State, Country" formatted strings ("Austin, Texas, US") — which
        is exactly what `resolve_location()` returns as `canonical_location`
        and what callers often pass back in. Try the direct/fast path first,
        then fall back to the more tolerant multi-variant resolver.
        """
        direct = self._fetch_open_meteo_geocode(location, limit=1)
        if direct:
            return direct[0]

        resolved = self.resolve_location(location, location)
        if resolved.get("status") in ("resolved", "ambiguous"):
            candidates = resolved.get("candidates") or []
            if candidates:
                return candidates[0]
        return None

    def _score_location_candidate(
        self,
        candidate_query: str,
        original_query: str,
        result: Dict[str, Any],
        variant_rank: int,
    ) -> float:
        """Return an *uncapped* relevance score. Callers should rank/compare
        using this raw value and only clip to [0, 1] when displaying a
        user-facing "confidence" — capping here would flatten the gap between
        e.g. "Austin, Texas" and "Austin, Minnesota" when both already exceed
        1.0 from the city-name match alone, hiding the state-match signal."""
        candidate_norm = self._normalize_location_text(candidate_query)
        original_norm = self._normalize_location_text(original_query)
        candidate_compact = self._collapse_location_text(candidate_norm)
        original_compact = self._collapse_location_text(original_norm)

        city = self._collapse_location_text(result.get("city", ""))
        state = self._collapse_location_text(result.get("state", ""))
        country = self._collapse_location_text(result.get("country", ""))
        display = self._normalize_location_text(result.get("display_name", ""))

        score = 0.0

        if city and candidate_compact:
            if city in candidate_compact or candidate_compact in city:
                coverage = min(len(city), len(candidate_compact)) / max(len(city), len(candidate_compact))
                score += 0.45 + (0.25 * coverage)
            else:
                similarity = SequenceMatcher(None, city, candidate_compact).ratio()
                if similarity >= 0.72:
                    score += 0.40 * similarity

        if state and state in candidate_compact:
            score += 0.10
        if country and country in candidate_compact:
            score += 0.08

        if city and city in original_compact:
            score += 0.16
        # A state named explicitly by the user (e.g. "Austin, Texas") is a
        # strong disambiguator between same-named cities in different states —
        # weight it heavily so it isn't washed out by the city-match score.
        if state and state in original_compact:
            score += 0.25
        if country and country in original_compact:
            score += 0.04

        candidate_tokens = set(re.findall(r"[a-z0-9]+", candidate_norm))
        display_tokens = set(re.findall(r"[a-z0-9]+", display))
        if city:
            display_tokens.add(city)

        if candidate_tokens:
            overlap = len(candidate_tokens & display_tokens) / len(candidate_tokens)
            score += 0.18 * overlap
            score -= 0.12 * (1.0 - overlap)

        score += max(0.0, 0.04 - (0.01 * variant_rank))
        return max(0.0, score)


    def resolve_location(self, location_query: str, original_query: str = "", limit: int = 5) -> Dict[str, Any]:
        """
        Resolve location text to a canonical, geocoded location.
        Returns one of: resolved, ambiguous, not_found, unavailable.
        """
        if not self._available:
            return {"status": "unavailable"}

        normalized_query = self._sanitize_location_query((location_query or "").strip())
        if not normalized_query or normalized_query == "Unknown":
            return {"status": "not_found", "query": location_query}

        query_variants = self._generate_location_queries(normalized_query)
        scored_candidates: List[Dict[str, Any]] = []

        for variant_rank, query_variant in enumerate(query_variants):
            if self._provider == "weatherapi":
                raw_candidates = self._fetch_weatherapi_geocode(query_variant, limit=limit)
            elif self._provider == "openweathermap":
                raw_candidates = self._fetch_openweathermap_geocode(query_variant, limit=limit)
            else:
                raw_candidates = self._fetch_open_meteo_geocode(query_variant, limit=limit)

            for candidate in raw_candidates:
                score = self._score_location_candidate(
                    candidate_query=query_variant,
                    original_query=original_query or normalized_query,
                    result=candidate,
                    variant_rank=variant_rank,
                )
                scored_candidates.append(
                    {
                        **candidate,
                        "score": score,  # uncapped — used for ranking/ambiguity checks
                        "confidence": round(min(1.0, score), 3),  # capped — user-facing display value
                        "matched_query": query_variant,
                    }
                )

        if not scored_candidates:
            return {"status": "not_found", "query": location_query}

        deduped: Dict[str, Dict[str, Any]] = {}
        for candidate in scored_candidates:
            key = f"{round(candidate.get('lat') or 0, 4)}:{round(candidate.get('lon') or 0, 4)}:{candidate.get('display_name', '').lower()}"
            existing = deduped.get(key)
            if not existing or candidate["score"] > existing["score"]:
                deduped[key] = candidate

        ranked = sorted(deduped.values(), key=lambda x: x["score"], reverse=True)
        best = ranked[0]
        second = ranked[1] if len(ranked) > 1 else None

        score_gap = best["score"] - (second["score"] if second else 0.0)
        is_ambiguous = second is not None and (best["score"] < 0.78 or score_gap < 0.10)

        if best["score"] < 0.55:
            return {
                "status": "not_found",
                "query": location_query,
                "candidates": ranked[:3],
            }

        if is_ambiguous:
            return {
                "status": "ambiguous",
                "query": location_query,
                "candidates": ranked[:3],
            }

        return {
            "status": "resolved",
            "query": location_query,
            "canonical_location": best["display_name"],
            "confidence": best["confidence"],
            "lat": best.get("lat"),
            "lon": best.get("lon"),
            "candidates": ranked[:3],
        }


    def _fetch_openweathermap(self, location: str) -> Optional[Dict[str, Any]]:
        """Fetch weather from OpenWeatherMap API."""
        if not self._api_key:
            return None
        try:
            geo_url = "http://api.openweathermap.org/geo/1.0/direct"
            geo_params = {"q": location, "limit": 1, "appid": self._api_key}
            geo_response = requests.get(geo_url, params=geo_params, timeout=5)

            if geo_response.status_code != 200:
                print(f"[Weather] Geo API error: {geo_response.status_code}")
                return None

            geo_data = geo_response.json()
            if not geo_data:
                print(f"[Weather] Location not found: {location}")
                return None

            lat, lon = geo_data[0]["lat"], geo_data[0]["lon"]

            weather_url = "https://api.openweathermap.org/data/2.5/weather"
            weather_params = {
                "lat": lat, "lon": lon,
                "appid": self._api_key, "units": "metric"
            }
            weather_response = requests.get(weather_url, params=weather_params, timeout=5)

            if weather_response.status_code != 200:
                print(f"[Weather] Weather API error: {weather_response.status_code}")
                return None

            data = weather_response.json()

            return {
                "location": f"{geo_data[0].get('name', location)}, {geo_data[0].get('country', '')}",
                "temperature": round(data["main"]["temp"]),
                "feels_like": round(data["main"]["feels_like"]),
                "condition": data["weather"][0]["description"].title(),
                "humidity": data["main"]["humidity"],
                "wind_speed": round(data["wind"].get("speed", 0) * 3.6, 1),
                "pressure": data["main"]["pressure"],
                "clouds": data["clouds"]["all"],
                "visibility": data.get("visibility", 0) / 1000 if data.get("visibility") else None,
            }
        except Exception as e:
            print(f"[Weather] OpenWeatherMap error: {e}")
            return None

    def _fetch_weatherapi(self, location: str) -> Optional[Dict[str, Any]]:
        """Fetch weather from WeatherAPI.com."""
        if not self._api_key:
            return None
        try:
            url = "https://api.weatherapi.com/v1/current.json"
            params = {"key": self._api_key, "q": location, "aqi": "no"}
            response = requests.get(url, params=params, timeout=5)

            if response.status_code != 200:
                print(f"[Weather] WeatherAPI error: {response.status_code}")
                return None

            data = response.json()

            return {
                "location": f"{data['location']['name']}, {data['location']['country']}",
                "temperature": round(data["current"]["temp_c"]),
                "feels_like": round(data["current"]["feelslike_c"]),
                "condition": data["current"]["condition"]["text"],
                "humidity": data["current"]["humidity"],
                "wind_speed": round(data["current"]["wind_kph"], 1),
                "pressure": data["current"]["pressure_mb"],
                "clouds": data["current"]["cloud"],
                "visibility": round(data["current"]["vis_km"], 1) if data["current"].get("vis_km") else None,
            }
        except Exception as e:
            print(f"[Weather] WeatherAPI error: {e}")
            return None

    def _fetch_weatherapi_forecast(self, location: str, days: int = 5) -> Optional[Dict[str, Any]]:
        """Fetch weather forecast from WeatherAPI.com."""
        if not self._api_key:
            return None
        try:
            days = min(days, 10)
            url = "https://api.weatherapi.com/v1/forecast.json"
            params = {"key": self._api_key, "q": location, "days": days, "aqi": "no"}
            response = requests.get(url, params=params, timeout=10)

            if response.status_code != 200:
                print(f"[Weather] WeatherAPI forecast error: {response.status_code}")
                return None

            data = response.json()

            forecast_days = []
            for day in data.get("forecast", {}).get("forecastday", []):
                forecast_days.append({
                    "date": day["date"],
                    "max_temp": round(day["day"]["maxtemp_c"]),
                    "min_temp": round(day["day"]["mintemp_c"]),
                    "avg_temp": round(day["day"]["avgtemp_c"]),
                    "condition": day["day"]["condition"]["text"],
                    "rain_chance": day["day"].get("daily_chance_of_rain", 0),
                    "humidity": day["day"].get("avghumidity", 0),
                    "max_wind": round(day["day"].get("maxwind_kph", 0), 1),
                })

            return {
                "location": f"{data['location']['name']}, {data['location']['country']}",
                "current": {
                    "temperature": round(data["current"]["temp_c"]),
                    "condition": data["current"]["condition"]["text"],
                },
                "forecast": forecast_days,
                "forecast_days": len(forecast_days),
            }
        except Exception as e:
            print(f"[Weather] WeatherAPI forecast error: {e}")
            return None

    # ── National Weather Service (free, keyless, USA-only official gov API) ──

    def _fetch_nws_points(self, lat: float, lon: float) -> Optional[Dict[str, Any]]:
        try:
            url = f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}"
            response = requests.get(url, headers=_NWS_HEADERS, timeout=8)
            if response.status_code != 200:
                # Non-200 (often 404) typically means the point is outside
                # NWS coverage (i.e. outside the USA).
                return None
            return response.json()
        except Exception as e:
            print(f"[Weather] NWS points lookup error: {e}")
            return None

    def _fetch_nws_at(self, lat: float, lon: float, display_name: str = "") -> Optional[Dict[str, Any]]:
        """Current conditions from NWS at GPS coordinates (US locations)."""
        points = self._fetch_nws_points(lat, lon)
        if not points:
            return None

        props = points.get("properties", {}) or {}
        rel = (props.get("relativeLocation") or {}).get("properties", {}) or {}
        resolved_name = display_name or self._build_display_name(
            rel.get("city", ""), rel.get("state", ""), ""
        ) or f"{lat:.4f}, {lon:.4f}"

        try:
            stations_url = props.get("observationStations")
            if stations_url:
                st_resp = requests.get(stations_url, headers=_NWS_HEADERS, timeout=8)
                if st_resp.status_code == 200:
                    features = (st_resp.json() or {}).get("features") or []
                    if features:
                        station_id = features[0]["properties"]["stationIdentifier"]
                        obs_resp = requests.get(
                            f"https://api.weather.gov/stations/{station_id}/observations/latest",
                            headers=_NWS_HEADERS, timeout=8,
                        )
                        if obs_resp.status_code == 200:
                            obs = (obs_resp.json() or {}).get("properties") or {}
                            temp_c = (obs.get("temperature") or {}).get("value")
                            if temp_c is not None:
                                heat_c = (obs.get("heatIndex") or {}).get("value")
                                wind_kmh = (obs.get("windSpeed") or {}).get("value")
                                pressure_pa = (obs.get("barometricPressure") or {}).get("value")
                                visibility_m = (obs.get("visibility") or {}).get("value")
                                humidity = (obs.get("relativeHumidity") or {}).get("value")
                                return {
                                    "location": resolved_name,
                                    "temperature": round(temp_c),
                                    "feels_like": round(heat_c) if heat_c is not None else round(temp_c),
                                    "condition": obs.get("textDescription") or "Unknown",
                                    "humidity": round(humidity) if humidity is not None else 0,
                                    "wind_speed": round(wind_kmh, 1) if wind_kmh is not None else 0,
                                    "pressure": round(pressure_pa / 100) if pressure_pa else None,
                                    "clouds": None,
                                    "visibility": round(visibility_m / 1000, 1) if visibility_m else None,
                                    "temp_unit": "C",
                                    "wind_unit": "km/h",
                                }
        except Exception as e:
            print(f"[Weather] NWS observation lookup error: {e}")

        try:
            forecast_url = props.get("forecast")
            if not forecast_url:
                return None
            f_resp = requests.get(forecast_url, headers=_NWS_HEADERS, timeout=8)
            if f_resp.status_code != 200:
                return None
            periods = (f_resp.json() or {}).get("properties", {}).get("periods") or []
            if not periods:
                return None
            period = periods[0]
            temp_f = period.get("temperature")
            temp_c = round((temp_f - 32) * 5 / 9) if temp_f is not None else None
            wind_match = re.search(r"[\d.]+", period.get("windSpeed") or "")
            wind_mph = float(wind_match.group()) if wind_match else 0.0
            return {
                "location": resolved_name,
                "temperature": temp_c,
                "feels_like": temp_c,
                "condition": period.get("shortForecast") or "Unknown",
                "humidity": round((period.get("relativeHumidity") or {}).get("value") or 0),
                "wind_speed": round(wind_mph * 1.60934, 1),
                "pressure": None,
                "clouds": None,
                "visibility": None,
                "temp_unit": "C",
                "wind_unit": "km/h",
            }
        except Exception as e:
            print(f"[Weather] NWS forecast-period fallback error: {e}")
            return None

    def _fetch_nws(self, location: str) -> Optional[Dict[str, Any]]:
        """Current conditions from NWS (US), geocoded by location name."""
        geo = self._geocode_best(location)
        if not geo:
            return None
        return self._fetch_nws_at(geo["lat"], geo["lon"], geo["display_name"] or location)

    def _fetch_nws_forecast_at(self, lat: float, lon: float, days: int, display_name: str = "") -> Optional[Dict[str, Any]]:
        """Multi-day forecast from NWS at GPS coordinates (US locations)."""
        points = self._fetch_nws_points(lat, lon)
        if not points:
            return None

        props = points.get("properties", {}) or {}
        forecast_url = props.get("forecast")
        if not forecast_url:
            return None

        try:
            resp = requests.get(forecast_url, headers=_NWS_HEADERS, timeout=8)
            if resp.status_code != 200:
                return None
            periods = (resp.json() or {}).get("properties", {}).get("periods") or []
        except Exception as e:
            print(f"[Weather] NWS forecast error: {e}")
            return None

        by_date: Dict[str, Dict[str, Any]] = {}
        order: List[str] = []
        for period in periods:
            date = (period.get("startTime") or "")[:10]
            if not date:
                continue
            if date not in by_date:
                by_date[date] = {"max": None, "min": None, "conditions": [], "rain": 0, "wind": 0.0}
                order.append(date)
            temp_f = period.get("temperature")
            temp_c = (temp_f - 32) * 5 / 9 if temp_f is not None else None
            if temp_c is not None:
                if period.get("isDaytime"):
                    by_date[date]["max"] = temp_c
                else:
                    by_date[date]["min"] = temp_c
            if period.get("shortForecast"):
                by_date[date]["conditions"].append(period["shortForecast"])
            rain_pct = (period.get("probabilityOfPrecipitation") or {}).get("value")
            if rain_pct:
                by_date[date]["rain"] = max(by_date[date]["rain"], rain_pct)
            wind_match = re.search(r"[\d.]+", period.get("windSpeed") or "")
            if wind_match:
                by_date[date]["wind"] = max(by_date[date]["wind"], float(wind_match.group()) * 1.60934)

        rel = (props.get("relativeLocation") or {}).get("properties", {}) or {}
        resolved_name = display_name or self._build_display_name(
            rel.get("city", ""), rel.get("state", ""), ""
        ) or f"{lat:.4f}, {lon:.4f}"

        forecast_days = []
        for date in order[:days]:
            d = by_date[date]
            max_t = d["max"] if d["max"] is not None else d["min"]
            min_t = d["min"] if d["min"] is not None else d["max"]
            avg_t = (max_t + min_t) / 2 if max_t is not None and min_t is not None else max_t
            forecast_days.append({
                "date": date,
                "max_temp": round(max_t) if max_t is not None else None,
                "min_temp": round(min_t) if min_t is not None else None,
                "avg_temp": round(avg_t) if avg_t is not None else None,
                "condition": d["conditions"][0] if d["conditions"] else "Unknown",
                "rain_chance": d["rain"],
                "humidity": 0,
                "max_wind": round(d["wind"], 1),
            })

        if not forecast_days:
            return None

        return {
            "location": resolved_name,
            "current": {"temperature": forecast_days[0]["max_temp"], "condition": forecast_days[0]["condition"]},
            "forecast": forecast_days,
            "forecast_days": len(forecast_days),
            "temp_unit": "C",
            "wind_unit": "km/h",
        }

    def _fetch_nws_forecast(self, location: str, days: int = 5) -> Optional[Dict[str, Any]]:
        geo = self._geocode_best(location)
        if not geo:
            return None
        return self._fetch_nws_forecast_at(geo["lat"], geo["lon"], days, geo["display_name"] or location)

    # ── Open-Meteo (free, keyless, worldwide) — fallback for non-US locations ──

    def _fetch_open_meteo_current_at(self, lat: float, lon: float, display_name: str = "") -> Optional[Dict[str, Any]]:
        """Fetch current conditions at GPS coordinates (no geocoding)."""
        try:
            params = {
                "latitude": lat, "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,"
                           "weather_code,wind_speed_10m,surface_pressure,cloud_cover",
                "timezone": "auto",
                **self._open_meteo_unit_params(),
            }
            resp = requests.get(_OPEN_METEO_FORECAST_URL, params=params, timeout=8)
            if resp.status_code != 200:
                print(f"[Weather] Open-Meteo forecast error: {resp.status_code}")
                return None
            current = (resp.json() or {}).get("current") or {}
            if current.get("temperature_2m") is None:
                return None
            return {
                "location": display_name or f"{lat:.4f}, {lon:.4f}",
                "temperature": round(current["temperature_2m"]),
                "feels_like": round(current.get("apparent_temperature", current["temperature_2m"])),
                "condition": _WMO_CODE_TEXT.get(current.get("weather_code"), "Unknown"),
                "humidity": current.get("relative_humidity_2m", 0),
                "wind_speed": round(current.get("wind_speed_10m", 0), 1),
                "pressure": round(current["surface_pressure"]) if current.get("surface_pressure") else None,
                "clouds": current.get("cloud_cover"),
                "visibility": None,
                "temp_unit": self._temp_label(),
                "wind_unit": self._wind_label(),
            }
        except Exception as e:
            print(f"[Weather] Open-Meteo coords error: {e}")
            return None

    def _fetch_open_meteo_current(self, location: str) -> Optional[Dict[str, Any]]:
        geo = self._geocode_best(location)
        if not geo:
            return None
        data = self._fetch_open_meteo_current_at(geo["lat"], geo["lon"], geo["display_name"] or location)
        if data and not data.get("location"):
            data["location"] = location
        return data

    def _fetch_open_meteo_forecast_at(self, lat: float, lon: float, days: int, display_name: str = "") -> Optional[Dict[str, Any]]:
        """Fetch multi-day forecast at GPS coordinates (no geocoding)."""
        try:
            params = {
                "latitude": lat, "longitude": lon,
                "daily": "temperature_2m_max,temperature_2m_min,weather_code,"
                         "precipitation_probability_max,wind_speed_10m_max,relative_humidity_2m_mean",
                "timezone": "auto",
                "forecast_days": min(days, 16),
                **self._open_meteo_unit_params(),
            }
            resp = requests.get(_OPEN_METEO_FORECAST_URL, params=params, timeout=8)
            if resp.status_code != 200:
                print(f"[Weather] Open-Meteo forecast error: {resp.status_code}")
                return None
            daily = (resp.json() or {}).get("daily") or {}
            dates = daily.get("time") or []
            if not dates:
                return None

            forecast_days = []
            for i, date in enumerate(dates):
                max_t = (daily.get("temperature_2m_max") or [None] * len(dates))[i]
                min_t = (daily.get("temperature_2m_min") or [None] * len(dates))[i]
                code = (daily.get("weather_code") or [None] * len(dates))[i]
                rain = (daily.get("precipitation_probability_max") or [0] * len(dates))[i]
                wind = (daily.get("wind_speed_10m_max") or [0] * len(dates))[i]
                humidity = (daily.get("relative_humidity_2m_mean") or [0] * len(dates))[i]
                forecast_days.append({
                    "date": date,
                    "max_temp": round(max_t) if max_t is not None else None,
                    "min_temp": round(min_t) if min_t is not None else None,
                    "avg_temp": round((max_t + min_t) / 2) if max_t is not None and min_t is not None else None,
                    "condition": _WMO_CODE_TEXT.get(code, "Unknown"),
                    "rain_chance": rain or 0,
                    "humidity": humidity or 0,
                    "max_wind": round(wind, 1) if wind is not None else 0,
                })

            return {
                "location": display_name or f"{lat:.4f}, {lon:.4f}",
                "current": {"temperature": forecast_days[0]["max_temp"], "condition": forecast_days[0]["condition"]},
                "forecast": forecast_days,
                "forecast_days": len(forecast_days),
                "temp_unit": self._temp_label(),
                "wind_unit": self._wind_label(),
            }
        except Exception as e:
            print(f"[Weather] Open-Meteo forecast coords error: {e}")
            return None

    def _fetch_open_meteo_forecast(self, location: str, days: int = 5) -> Optional[Dict[str, Any]]:
        geo = self._geocode_best(location)
        if not geo:
            return None
        return self._fetch_open_meteo_forecast_at(
            geo["lat"], geo["lon"], days, geo["display_name"] or location
        )

    def get_weather_by_coords(self, lat: float, lon: float, location_name: str = "") -> Optional[Dict[str, Any]]:
        """Fetch current weather at GPS coordinates — NWS first, Open-Meteo fallback."""
        if not self._available:
            return None
        cache_key = f"coords:{lat:.4f},{lon:.4f}"
        cached = self._get_from_cache(cache_key)
        if cached:
            return cached
        if self._provider == "openmeteo":
            data = self._fetch_open_meteo_current_at(lat, lon, location_name)
        else:
            data = self._fetch_nws_at(lat, lon, location_name)
            if not data:
                print(f"[Weather] NWS unavailable at {lat},{lon} — trying Open-Meteo")
                data = self._fetch_open_meteo_current_at(lat, lon, location_name)
        if data:
            self._save_to_cache(cache_key, data)
        return data

    def get_forecast_by_coords(self, lat: float, lon: float, days: int = 7, location_name: str = "") -> Optional[Dict[str, Any]]:
        """Fetch forecast at GPS coordinates — NWS first, Open-Meteo fallback."""
        if not self._available:
            return None
        cache_key = f"coords_fc:{lat:.4f},{lon:.4f}:{days}"
        cached = self._get_from_cache(cache_key)
        if cached:
            return cached
        if self._provider == "openmeteo":
            data = self._fetch_open_meteo_forecast_at(lat, lon, days, location_name)
        else:
            data = self._fetch_nws_forecast_at(lat, lon, days, location_name)
            if not data:
                print(f"[Weather] NWS forecast unavailable at {lat},{lon} — trying Open-Meteo")
                data = self._fetch_open_meteo_forecast_at(lat, lon, days, location_name)
        if data:
            self._save_to_cache(cache_key, data)
        return data

    def get_forecast(self, location: str, days: int = 5) -> Optional[Dict[str, Any]]:
        """Fetch weather forecast for location."""
        if not self._available or not location or location == "Unknown":
            return None

        print(f"[Weather] Fetching {days}-day forecast for {location}...")

        if self._provider == "weatherapi":
            data = self._fetch_weatherapi_forecast(location, days)
        elif self._provider == "openweathermap":
            print(f"[Weather] Forecast not available with OpenWeatherMap provider (current-weather only)")
            data = None
        elif self._provider == "openmeteo":
            data = self._fetch_open_meteo_forecast(location, days)
        else:
            # NWS first (USA), Open-Meteo worldwide fallback.
            data = self._fetch_nws_forecast(location, days)
            if not data:
                print(f"[Weather] NWS forecast unavailable for '{location}' — trying Open-Meteo (worldwide)")
                data = self._fetch_open_meteo_forecast(location, days)

        if data:
            print(f"[Weather] Forecast data retrieved ({data['forecast_days']} days)")

        return data

    def format_forecast_for_llm(self, forecast_data: Optional[Dict[str, Any]]) -> str:
        """Format forecast data as context string for LLM."""
        if not forecast_data or not forecast_data.get("forecast"):
            return ""

        parts = [f"Weather forecast for {forecast_data['location']}:\n"]

        if forecast_data.get("current"):
            tu = forecast_data.get("temp_unit") or self._temp_label()
            parts.append(f"Current: {forecast_data['current']['temperature']}°{tu}, {forecast_data['current']['condition']}\n")

        parts.append("Forecast:")
        tu = forecast_data.get("temp_unit") or self._temp_label()
        for day in forecast_data["forecast"]:
            rain_str = f", {day['rain_chance']}% rain" if day.get('rain_chance', 0) > 0 else ""
            parts.append(f"  {day['date']}: {day['min_temp']}°{tu} - {day['max_temp']}°{tu}, {day['condition']}{rain_str}")

        return "\n".join(parts)

    def get_weather(self, location: str) -> Optional[Dict[str, Any]]:
        """Fetch current weather for location."""
        if not self._available or not location or location == "Unknown":
            return None

        cached = self._get_from_cache(location)
        if cached:
            print(f"[Weather] Using cached data for {location}")
            return cached

        print(f"[Weather] Fetching weather for {location}...")
        if self._provider == "weatherapi":
            data = self._fetch_weatherapi(location)
        elif self._provider == "openweathermap":
            data = self._fetch_openweathermap(location)
        elif self._provider == "openmeteo":
            data = self._fetch_open_meteo_current(location)
        else:
            # NWS first (USA), Open-Meteo worldwide fallback.
            data = self._fetch_nws(location)
            if not data:
                print(f"[Weather] NWS unavailable for '{location}' — trying Open-Meteo (worldwide)")
                data = self._fetch_open_meteo_current(location)

        if data:
            self._save_to_cache(location, data)
            print(f"[Weather] Weather data retrieved")

        return data

    def format_for_llm(self, weather_data: Optional[Dict[str, Any]]) -> str:
        """Format weather data as context string for LLM."""
        if not weather_data:
            return ""

        parts = ["Current weather conditions:\n"]
        tu = weather_data.get("temp_unit") or self._temp_label()
        wu = weather_data.get("wind_unit") or self._wind_label()
        parts.append(f"Temperature: {weather_data['temperature']}°{tu} (feels like {weather_data['feels_like']}°{tu})")
        parts.append(f"Condition: {weather_data['condition']}")
        parts.append(f"Humidity: {weather_data['humidity']}%")
        parts.append(f"Wind Speed: {weather_data['wind_speed']} {wu}")
        parts.append(f"Pressure: {weather_data['pressure']} hPa")
        if weather_data.get('visibility'):
            parts.append(f"Visibility: {weather_data['visibility']} km")

        return "\n".join(parts)


weather_service = WeatherService()


@tool
def get_weather_tool(location: str) -> str:
    """Get current weather conditions for a specific location.

    Use this tool when weather information is needed to provide accurate farm advice.
    The location can be a city name, region, or any geographic location.

    Args:
        location: The location to get weather for (e.g., "Boston", "New York", "North region")

    Returns:
        A formatted string with current weather conditions including temperature,
        condition, humidity, wind speed, and pressure.
    """
    weather_data = weather_service.get_weather(location)
    if not weather_data:
        return f"Unable to fetch weather data for {location}. Please check the location name or try again later."

    return weather_service.format_for_llm(weather_data)


weather_tools = [get_weather_tool]
