import logging
from dataclasses import dataclass

import requests
from django.core.cache import cache

from fuelplanner.conf import planner_settings
from fuelplanner.services.geo import LatLon
from fuelplanner.services.geocoding import Location
from fuelplanner.services.http import http_session

logger = logging.getLogger(__name__)

METERS_PER_MILE = 1609.344
SECONDS_PER_HOUR = 3600


class RoutingError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Route:
    points: tuple[LatLon, ...]
    distance_miles: float
    duration_hours: float


def get_route(start: Location, finish: Location) -> Route:
    """Driving route from OSRM: a single request, cached per coordinate pair."""
    coordinates = f"{start.lon:.5f},{start.lat:.5f};{finish.lon:.5f},{finish.lat:.5f}"
    cache_key = f"fuelplanner:route:{coordinates}"
    if (route := cache.get(cache_key)) is not None:
        return route

    route = _fetch_route(coordinates)
    cache.set(cache_key, route, planner_settings().cache_seconds)
    return route


def _fetch_route(coordinates: str) -> Route:
    config = planner_settings()
    try:
        response = http_session().get(
            f"{config.osrm_url}/route/v1/driving/{coordinates}",
            params={"overview": "full", "geometries": "geojson", "steps": "false"},
            timeout=config.http_timeout_seconds,
        )
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("OSRM request failed for %s: %s", coordinates, exc)
        raise RoutingError("Routing service is unavailable, try again later.") from exc

    if payload.get("code") != "Ok" or not payload.get("routes"):
        logger.info("OSRM returned no route for %s: %s", coordinates, payload.get("code"))
        raise RoutingError("No drivable route found between these locations.")

    route = payload["routes"][0]
    return Route(
        points=tuple(LatLon(lat, lon) for lon, lat in route["geometry"]["coordinates"]),
        distance_miles=route["distance"] / METERS_PER_MILE,
        duration_hours=route["duration"] / SECONDS_PER_HOUR,
    )
