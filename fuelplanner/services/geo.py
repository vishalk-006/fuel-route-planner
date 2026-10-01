import math
from collections.abc import Sequence
from itertools import pairwise
from typing import NamedTuple

EARTH_RADIUS_MILES = 3958.8

US_BOUNDING_BOXES = (
    (24.3, 49.5, -125.0, -66.8),
    (51.0, 71.6, -180.0, -129.9),
    (18.8, 22.4, -160.5, -154.7),
)


class LatLon(NamedTuple):
    lat: float
    lon: float


class RoutePoint(NamedTuple):
    lat: float
    lon: float
    mile: float


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def is_in_usa(lat: float, lon: float) -> bool:
    return any(
        min_lat <= lat <= max_lat and min_lon <= lon <= max_lon
        for min_lat, max_lat, min_lon, max_lon in US_BOUNDING_BOXES
    )


def resample(points: Sequence[LatLon], step_miles: float) -> list[RoutePoint]:
    """Points every ``step_miles`` along the polyline, always including both ends."""
    if not points:
        return []

    samples = [RoutePoint(points[0].lat, points[0].lon, 0.0)]
    travelled = 0.0
    next_mark = step_miles
    for start, end in pairwise(points):
        segment = haversine_miles(start.lat, start.lon, end.lat, end.lon)
        while segment > 0 and next_mark <= travelled + segment:
            t = (next_mark - travelled) / segment
            samples.append(
                RoutePoint(
                    start.lat + t * (end.lat - start.lat),
                    start.lon + t * (end.lon - start.lon),
                    next_mark,
                )
            )
            next_mark += step_miles
        travelled += segment

    if samples[-1].mile < travelled:
        samples.append(RoutePoint(points[-1].lat, points[-1].lon, travelled))
    return samples
