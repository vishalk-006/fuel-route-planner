from dataclasses import dataclass
from pathlib import Path

from django.conf import settings


@dataclass(frozen=True, slots=True)
class PlannerSettings:
    data_dir: Path
    vehicle_range_miles: float
    vehicle_mpg: float
    corridor_miles: float
    origin_search_miles: float
    stop_penalty: float
    prune_window_miles: float
    cache_seconds: int
    osrm_url: str
    nominatim_url: str
    http_user_agent: str
    http_timeout_seconds: float


def planner_settings() -> PlannerSettings:
    return PlannerSettings(**{key.lower(): value for key, value in settings.FUEL_PLANNER.items()})
