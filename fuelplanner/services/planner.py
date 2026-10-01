import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass

from fuelplanner.conf import planner_settings
from fuelplanner.services.geo import LatLon, RoutePoint, resample
from fuelplanner.services.geocoding import Location, geocode
from fuelplanner.services.optimizer import FuelPlan, Vehicle, plan_fuel_stops, prune_candidates
from fuelplanner.services.routing import get_route
from fuelplanner.services.stations import get_station_index

logger = logging.getLogger(__name__)

SAMPLE_STEP_MILES = 1.0


@dataclass(frozen=True, slots=True)
class TripRequest:
    start: str
    finish: str
    corridor_miles: float
    stop_penalty: float


@dataclass(frozen=True, slots=True)
class TripPlan:
    request: TripRequest
    start: Location
    finish: Location
    distance_miles: float
    duration_hours: float
    vehicle: Vehicle
    fuel_plan: FuelPlan
    stations_in_corridor: int
    route: tuple[RoutePoint, ...]


def plan_trip(request: TripRequest) -> TripPlan:
    started = time.perf_counter()
    config = planner_settings()
    vehicle = Vehicle(range_miles=config.vehicle_range_miles, mpg=config.vehicle_mpg)

    start = geocode(request.start)
    finish = geocode(request.finish)
    route = get_route(start, finish)
    samples = _scaled_samples(route.points, route.distance_miles)

    candidates = get_station_index().near_route(samples, request.corridor_miles)
    fuel_plan = plan_fuel_stops(
        prune_candidates(candidates, config.prune_window_miles),
        route.distance_miles,
        vehicle,
        origin_search_miles=config.origin_search_miles,
        stop_penalty=request.stop_penalty,
    )

    logger.info(
        "Planned %r -> %r: %.0f mi, %d stops, %d candidates in %.0f ms",
        request.start,
        request.finish,
        route.distance_miles,
        len(fuel_plan.stops),
        len(candidates),
        (time.perf_counter() - started) * 1000,
    )
    return TripPlan(
        request=request,
        start=start,
        finish=finish,
        distance_miles=route.distance_miles,
        duration_hours=route.duration_hours,
        vehicle=vehicle,
        fuel_plan=fuel_plan,
        stations_in_corridor=len(candidates),
        route=tuple(samples),
    )


def _scaled_samples(points: Sequence[LatLon], distance_miles: float) -> list[RoutePoint]:
    """Resample the route and rescale mileage so it agrees with the router's distance."""
    samples = resample(points, SAMPLE_STEP_MILES)
    measured = samples[-1].mile
    if measured <= 0:
        return samples
    scale = distance_miles / measured
    return [RoutePoint(sample.lat, sample.lon, sample.mile * scale) for sample in samples]
