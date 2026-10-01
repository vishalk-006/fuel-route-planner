"""Resolve user input to coordinates.

``"lat,lon"`` and ``"City, ST"`` are resolved locally (the latter from the Census
gazetteer loaded into ``Place``); anything else falls back to Nominatim.
"""

import logging
import re
from dataclasses import dataclass

import requests

from fuelplanner.conf import planner_settings
from fuelplanner.models import Place
from fuelplanner.services.geo import is_in_usa
from fuelplanner.services.http import http_session

logger = logging.getLogger(__name__)

STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}  # fmt: skip
STATE_CODES_BY_NAME = {name.lower(): code for code, name in STATES.items()}
NON_US_REGIONS = frozenset(
    {"AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT", "CANADA", "MEXICO"}
)
COUNTRY_SUFFIXES = frozenset({"USA", "US", "UNITED STATES"})

_ABBREVIATIONS = (
    (re.compile(r"\bsaint\b"), "st"),
    (re.compile(r"\bste\b"), "st"),
    (re.compile(r"\bst\."), "st"),
    (re.compile(r"\bfort\b"), "ft"),
    (re.compile(r"\bft\."), "ft"),
    (re.compile(r"\bmount\b"), "mt"),
    (re.compile(r"\bmt\."), "mt"),
)
_PARENTHESISED = re.compile(r"\(.*?\)")
_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9 ]")
_WHITESPACE = re.compile(r"\s+")
_LAT_LON = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")


class GeocodingError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Location:
    lat: float
    lon: float
    label: str
    source: str


def normalize_place_name(name: str) -> str:
    normalized = _PARENTHESISED.sub("", name.lower().strip())
    for pattern, replacement in _ABBREVIATIONS:
        normalized = pattern.sub(replacement, normalized)
    normalized = _NON_ALPHANUMERIC.sub(" ", normalized)
    return _WHITESPACE.sub(" ", normalized).strip()


def place_keys(name: str) -> list[str]:
    """Lookup keys for a place name; the compact form matches "De Forest" to "DeForest"."""
    key = normalize_place_name(name)
    return [key, key.replace(" ", "")]


def parse_state(token: str) -> str | None:
    token = token.strip().rstrip(".")
    if token.upper() in STATES:
        return token.upper()
    return STATE_CODES_BY_NAME.get(token.lower())


def find_place(city: str, state: str) -> Place | None:
    keys = place_keys(city)
    places = {place.key: place for place in Place.objects.filter(state=state, key__in=keys)}
    return next((places[key] for key in keys if key in places), None)


def geocode(query: str) -> Location:
    query = query.strip()
    if not query:
        raise GeocodingError("Location is empty.")

    if match := _LAT_LON.match(query):
        lat, lon = float(match.group(1)), float(match.group(2))
        if not is_in_usa(lat, lon):
            raise GeocodingError(f"'{query}' is not inside the USA.")
        return Location(lat, lon, query, "coordinates")

    parts = [part.strip() for part in query.split(",") if part.strip()]
    if parts and parts[-1].upper() in COUNTRY_SUFFIXES:
        parts.pop()
    if len(parts) >= 2 and parts[-1].upper() in NON_US_REGIONS:
        raise GeocodingError(f"'{query}' is not inside the USA.")
    if len(parts) == 2 and (state := parse_state(parts[1])) and (place := find_place(parts[0], state)):
        return Location(place.lat, place.lon, f"{place.name}, {state}", "gazetteer")

    return _search_nominatim(query)


def nominatim_search(params: dict[str, str]) -> tuple[float, float, str] | None:
    """First Nominatim hit inside the USA as ``(lat, lon, display_name)``."""
    config = planner_settings()
    response = http_session().get(
        config.nominatim_url,
        params={**params, "format": "jsonv2", "limit": "1", "countrycodes": "us"},
        timeout=config.http_timeout_seconds,
    )
    response.raise_for_status()
    results = response.json()
    if not results:
        return None
    lat, lon = float(results[0]["lat"]), float(results[0]["lon"])
    if not is_in_usa(lat, lon):
        return None
    return lat, lon, results[0].get("display_name", "")


def _search_nominatim(query: str) -> Location:
    try:
        result = nominatim_search({"q": query})
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Nominatim lookup failed for %r: %s", query, exc)
        raise GeocodingError("Geocoding service is unavailable, try again later.") from exc
    if result is None:
        raise GeocodingError(f"Could not find '{query}' in the USA.")
    lat, lon, label = result
    return Location(lat, lon, label or query, "nominatim")
