import json
import time
from pathlib import Path

import requests
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from fuelplanner.conf import planner_settings
from fuelplanner.importers import gazetteer
from fuelplanner.importers.fuel_prices import StationRecord, read_us_stations
from fuelplanner.models import FuelStation, Place
from fuelplanner.services.geocoding import STATES, nominatim_search
from fuelplanner.services.stations import reset_station_index

NOMINATIM_MIN_INTERVAL_SECONDS = 1.1
CACHE_FLUSH_EVERY = 20

type Coordinates = tuple[float, float]
type GeocodeCache = dict[str, Coordinates | None]


class Command(BaseCommand):
    help = "Load Census gazetteer places and geocoded fuel stations into the database."

    def add_arguments(self, parser: CommandParser) -> None:
        data_dir = planner_settings().data_dir
        parser.add_argument("--csv", type=Path, default=data_dir / "fuel_prices.csv")
        parser.add_argument("--gazetteer-dir", type=Path, default=data_dir / "gazetteer")
        parser.add_argument("--geocode-cache", type=Path, default=data_dir / "geocode_cache.json")
        parser.add_argument(
            "--offline",
            action="store_true",
            help="Use only the gazetteer and the geocode cache; skip stations that are still unresolved.",
        )

    def handle(self, *args, **options) -> None:
        csv_path: Path = options["csv"]
        if not csv_path.exists():
            raise CommandError(
                f"Fuel price file not found at {csv_path}. Copy the provided "
                "fuel-prices-for-be-assessment.csv there, or pass --csv <path>."
            )
        cache_path: Path = options["geocode_cache"]
        place_index = gazetteer.build_place_index(options["gazetteer_dir"])
        records = read_us_stations(csv_path)
        cache = _read_cache(cache_path)

        unresolved = sorted(
            {
                (record.city, record.state)
                for record in records
                if gazetteer.lookup(place_index, record.city, record.state) is None
                and _cache_key(record.city, record.state) not in cache
            }
        )
        if unresolved and not options["offline"]:
            self._geocode_towns(unresolved, cache, cache_path)

        stations = [
            station for record in records if (station := _build_station(record, place_index, cache)) is not None
        ]
        _save(place_index, stations)
        reset_station_index()

        self.stdout.write(
            self.style.SUCCESS(
                f"Loaded {len(place_index)} place keys and {len(stations)} US fuel stations "
                f"({len(records) - len(stations)} skipped: location unknown)."
            )
        )

    def _geocode_towns(self, towns: list[tuple[str, str]], cache: GeocodeCache, cache_path: Path) -> None:
        self.stdout.write(f"Geocoding {len(towns)} towns via Nominatim (rate limited to 1 request/second)...")
        for position, (city, state) in enumerate(towns, start=1):
            cache[_cache_key(city, state)] = self._geocode_town(city, state)
            if position % CACHE_FLUSH_EVERY == 0:
                _write_cache(cache_path, cache)
                self.stdout.write(f"  {position}/{len(towns)}")
            time.sleep(NOMINATIM_MIN_INTERVAL_SECONDS)
        _write_cache(cache_path, cache)

    def _geocode_town(self, city: str, state: str) -> Coordinates | None:
        try:
            result = nominatim_search({"city": city, "state": STATES[state], "country": "USA"})
        except (requests.RequestException, ValueError) as exc:
            self.stderr.write(f"  {city}, {state}: {exc}")
            return None
        if result is None:
            self.stderr.write(f"  {city}, {state}: not found")
            return None
        lat, lon, _ = result
        return lat, lon


def _build_station(record: StationRecord, place_index: gazetteer.PlaceIndex, cache: GeocodeCache) -> FuelStation | None:
    if place := gazetteer.lookup(place_index, record.city, record.state):
        (lat, lon), source = (place.lat, place.lon), FuelStation.GeocodeSource.GAZETTEER
    elif cached := cache.get(_cache_key(record.city, record.state)):
        (lat, lon), source = cached, FuelStation.GeocodeSource.NOMINATIM
    else:
        return None
    return FuelStation(
        opis_id=record.opis_id,
        name=record.name,
        address=record.address,
        city=record.city,
        state=record.state,
        rack_id=record.rack_id,
        price=record.price,
        lat=lat,
        lon=lon,
        geocode_source=source,
    )


@transaction.atomic
def _save(place_index: gazetteer.PlaceIndex, stations: list[FuelStation]) -> None:
    Place.objects.all().delete()
    Place.objects.bulk_create(
        (
            Place(state=state, key=key, name=entry.name, lat=entry.lat, lon=entry.lon)
            for (state, key), entry in place_index.items()
        ),
        batch_size=5000,
    )
    FuelStation.objects.all().delete()
    FuelStation.objects.bulk_create(stations, batch_size=2000)


def _cache_key(city: str, state: str) -> str:
    return f"{city}|{state}"


def _read_cache(path: Path) -> GeocodeCache:
    if not path.exists():
        return {}
    return {key: (value[0], value[1]) if value else None for key, value in json.loads(path.read_text()).items()}


def _write_cache(path: Path, cache: GeocodeCache) -> None:
    path.write_text(json.dumps(cache, indent=0, sort_keys=True))
