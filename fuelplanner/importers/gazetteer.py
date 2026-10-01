"""US Census Gazetteer (places and county subdivisions) as a city-name index."""

import csv
import io
import re
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

from fuelplanner.services.geocoding import STATES, place_keys

GAZETTEER_SOURCES = (
    ("2024_Gaz_place_national.zip", 0),
    ("2024_Gaz_cousubs_national.zip", 1),
)
ALIAS_PENALTY = 2

_AREA_DESCRIPTION_SUFFIX = re.compile(
    r"\s+(city and borough|consolidated government|unified government|metro government|"
    r"metropolitan government|urban county|charter township|unorganized territory|"
    r"city|town|village|borough|cdp|municipality|township|ccd|plantation|"
    r"precinct|district|reservation|gore|grant|location|purchase)(\s*\(.*\))?$",
    re.IGNORECASE,
)


class PlaceEntry(NamedTuple):
    priority: tuple[int, float]
    name: str
    lat: float
    lon: float


type PlaceIndex = dict[tuple[str, str], PlaceEntry]


def build_place_index(gazetteer_dir: Path) -> PlaceIndex:
    """Best entry per ``(state, key)``: incorporated places beat county subdivisions,
    real names beat aliases, and larger land area breaks ties."""
    index: PlaceIndex = {}
    for filename, source_rank in GAZETTEER_SOURCES:
        for row in _read_rows(gazetteer_dir / filename):
            state = row["USPS"]
            if state not in STATES:
                continue
            display_name = _AREA_DESCRIPTION_SUFFIX.sub("", row["NAME"])
            for variant, is_alias in _name_variants(row["NAME"]):
                entry = PlaceEntry(
                    priority=(source_rank + (ALIAS_PENALTY if is_alias else 0), -float(row["ALAND"])),
                    name=display_name,
                    lat=float(row["INTPTLAT"]),
                    lon=float(row["INTPTLONG"]),
                )
                for key in place_keys(variant):
                    current = index.get((state, key))
                    if current is None or entry.priority < current.priority:
                        index[(state, key)] = entry
    return index


def lookup(index: PlaceIndex, city: str, state: str) -> PlaceEntry | None:
    return next((index[(state, key)] for key in place_keys(city) if (state, key) in index), None)


def _read_rows(path: Path) -> Iterator[dict[str, str]]:
    with zipfile.ZipFile(path) as archive:
        member = next(name for name in archive.namelist() if name.endswith(".txt"))
        with archive.open(member) as raw:
            reader = csv.reader(io.TextIOWrapper(raw, encoding="latin-1"), delimiter="\t")
            header = [column.strip() for column in next(reader)]
            for row in reader:
                yield dict(zip(header, (value.strip() for value in row), strict=False))


def _name_variants(full_name: str) -> list[tuple[str, bool]]:
    base = _AREA_DESCRIPTION_SUFFIX.sub("", full_name)
    variants = [(base, False), (full_name, False)]
    if "-" in base:
        variants.append((base.split("-")[0], True))
    if base.endswith(" City"):
        variants.append((base.removesuffix(" City"), True))
    return variants
