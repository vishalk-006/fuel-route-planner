"""In-memory spatial index over all fuel stations, built once per process."""

import math
import threading
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from fuelplanner.models import FuelStation
from fuelplanner.services.geo import RoutePoint, haversine_miles

CELL_SIZE_DEGREES = 0.25
MILES_PER_DEGREE_LAT = 69.0
MIN_COS_LAT = 0.01


@dataclass(frozen=True, slots=True)
class Station:
    id: int
    opis_id: int
    name: str
    address: str
    city: str
    state: str
    price: float
    lat: float
    lon: float


@dataclass(frozen=True, slots=True)
class Candidate:
    station: Station
    mile: float
    off_route_miles: float


type Cell = tuple[int, int]


class StationIndex:
    def __init__(self, stations: Iterable[Station]) -> None:
        self._grid: dict[Cell, list[Station]] = defaultdict(list)
        for station in stations:
            self._grid[self._cell(station.lat, station.lon)].append(station)

    @staticmethod
    def _cell(lat: float, lon: float) -> Cell:
        return math.floor(lat / CELL_SIZE_DEGREES), math.floor(lon / CELL_SIZE_DEGREES)

    def near_route(self, samples: Sequence[RoutePoint], corridor_miles: float) -> list[Candidate]:
        """Stations within ``corridor_miles`` of the route, sorted by route mile.

        Each station is placed at the mile of its closest sample, so samples must
        be spaced well below ``corridor_miles``.
        """
        closest: dict[int, Candidate] = {}
        lat_margin = corridor_miles / MILES_PER_DEGREE_LAT
        for sample in samples:
            cos_lat = max(math.cos(math.radians(sample.lat)), MIN_COS_LAT)
            lon_margin = corridor_miles / (MILES_PER_DEGREE_LAT * cos_lat)
            for station in self._stations_in_box(sample, lat_margin, lon_margin):
                distance = haversine_miles(sample.lat, sample.lon, station.lat, station.lon)
                if distance > corridor_miles:
                    continue
                current = closest.get(station.id)
                if current is None or distance < current.off_route_miles:
                    closest[station.id] = Candidate(station, sample.mile, distance)
        return sorted(closest.values(), key=lambda c: (c.mile, c.station.price))

    def _stations_in_box(self, center: RoutePoint, lat_margin: float, lon_margin: float) -> Iterable[Station]:
        min_row, min_col = self._cell(center.lat - lat_margin, center.lon - lon_margin)
        max_row, max_col = self._cell(center.lat + lat_margin, center.lon + lon_margin)
        for row in range(min_row, max_row + 1):
            for col in range(min_col, max_col + 1):
                for station in self._grid.get((row, col), ()):
                    if abs(station.lat - center.lat) <= lat_margin and abs(station.lon - center.lon) <= lon_margin:
                        yield station


_index: StationIndex | None = None
_index_lock = threading.Lock()


def get_station_index() -> StationIndex:
    global _index
    if _index is None:
        with _index_lock:
            if _index is None:
                _index = StationIndex(_load_stations())
    return _index


def reset_station_index() -> None:
    global _index
    with _index_lock:
        _index = None


def _load_stations() -> Iterable[Station]:
    fields = ("id", "opis_id", "name", "address", "city", "state", "price", "lat", "lon")
    for row in FuelStation.objects.values_list(*fields).iterator():
        values = dict(zip(fields, row, strict=True))
        yield Station(**{**values, "price": float(values["price"])})
