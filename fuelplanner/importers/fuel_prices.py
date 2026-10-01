import csv
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from fuelplanner.services.geocoding import STATES

PRICE_PRECISION = Decimal("0.0001")


@dataclass(frozen=True, slots=True)
class StationRecord:
    opis_id: int
    name: str
    address: str
    city: str
    state: str
    rack_id: int | None
    price: Decimal


def read_us_stations(csv_path: Path) -> list[StationRecord]:
    """US stations from the OPIS price file, keeping the lowest price per station."""
    cheapest: dict[int, StationRecord] = {}
    with csv_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            record = _parse_row(row)
            if record.state not in STATES:
                continue
            current = cheapest.get(record.opis_id)
            if current is None or record.price < current.price:
                cheapest[record.opis_id] = record
    return list(cheapest.values())


def _parse_row(row: dict[str, str]) -> StationRecord:
    rack_id = row["Rack ID"].strip()
    return StationRecord(
        opis_id=int(row["OPIS Truckstop ID"]),
        name=row["Truckstop Name"].strip(),
        address=row["Address"].strip(),
        city=row["City"].strip(),
        state=row["State"].strip(),
        rack_id=int(rack_id) if rack_id else None,
        price=Decimal(row["Retail Price"]).quantize(PRICE_PRECISION),
    )
