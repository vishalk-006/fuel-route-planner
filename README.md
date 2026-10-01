# Fuel Route Planner API

A Django 6.1 + DRF API. Give it a start and finish anywhere in the USA and it returns:

- the driving route (GeoJSON, plus an interactive map page),
- the most cost-effective fuel stops along it, for a vehicle with a **500 mile range** at **10 mpg**,
- the gallons and cost for each stop, and the **total fuel cost** of the trip.

## Quick start

The fuel price CSV provided with the assessment is not committed, because it is third-party pricing data. Copy it into `data/` as shown below. See [`data/README.md`](data/README.md) for the sources of every data file.

```bash
python3 -m venv .venv && source .venv/bin/activate   # Python 3.12+
pip install -r requirements-dev.txt
export DJANGO_DEBUG=1                   # or set DJANGO_SECRET_KEY for a non-debug run
cp /path/to/fuel-prices-for-be-assessment.csv data/fuel_prices.csv
python manage.py migrate
python manage.py load_data --offline    # ~3 s, no network needed
python manage.py runserver
```

- API: <http://127.0.0.1:8000/api/route/?start=Chicago,%20IL&finish=Houston,%20TX>
- Map: <http://127.0.0.1:8000/map/?start=New%20York,%20NY&finish=Los%20Angeles,%20CA>
- Tests: `python manage.py test fuelplanner`
- Lint/format: `ruff check . && ruff format --check .`

## API

`GET /api/route/?start=…&finish=…` or `POST /api/route/` with a JSON body.

| param | required | description |
|---|---|---|
| `start`, `finish` | yes | `"City, ST"` (or a full state name), a street address, or `"lat,lon"`. Must be in the USA. |
| `corridor_miles` | no | How far a station may be from the route (1–25, default 10). |
| `stop_penalty` | no | Dollar cost assigned to each stop (0–100, default 5). `0` gives the cheapest possible fuel no matter how many stops. |

```bash
curl -s "http://127.0.0.1:8000/api/route/?start=Chicago,%20IL&finish=Houston,%20TX"
```

Response (trimmed):

```json
{
  "start":  {"query": "Chicago, IL", "label": "Chicago, IL", "lat": 41.837045, "lon": -87.684939, "source": "gazetteer"},
  "finish": {"query": "Houston, TX", "label": "Houston, TX", "lat": 29.785743, "lon": -95.388806, "source": "gazetteer"},
  "distance_miles": 1083.1,
  "duration_hours": 19.89,
  "vehicle": {"range_miles": 500, "mpg": 10, "tank_gallons": 50.0},
  "parameters": {"corridor_miles": 10, "stop_penalty": 5.0},
  "fuel_stops": [
    {"mile": 15.0, "off_route_miles": 7.8,
     "station": {"opis_id": 72577, "name": "QUIKTRIP #7205", "address": "I-80, EXIT 161", "city": "Lansing", "state": "IL", "lat": 41.565004, "lon": -87.546004},
     "price_per_gallon": 3.079, "fuel_on_arrival_gallons": 0.0, "gallons": 31.28, "cost": 96.3},
    {"mile": 312.8, "station": {"name": "HUCKS FOOD & FUEL #379", "city": "Marion", "state": "IL"}, "gallons": 47.57, "cost": 139.32},
    {"mile": 788.4, "station": {"name": "Quiktrip #7900", "city": "Texarkana", "state": "TX"}, "gallons": 29.47, "cost": 84.2}
  ],
  "total_gallons": 108.31,
  "total_fuel_cost": 319.82,
  "stations_in_corridor": 179,
  "route": {"type": "LineString", "coordinates": [[-87.68494, 41.83705], "…"]},
  "map_url": "http://127.0.0.1:8000/map/?start=Chicago%2C+IL&finish=Houston%2C+TX&corridor_miles=10&stop_penalty=5.0"
}
```

Fuel stops are listed in route order. Errors: `400` for invalid or non-US input, `422` if no feasible fuel plan exists (a gap longer than 500 miles with no stations), `502` if the routing service fails, `429` if a client exceeds the rate limit (60 requests/min by default).

## How it works

```
request ─► geocode start/finish ─► OSRM route (1 call) ─► stations near route ─► optimizer ─► JSON
           (local gazetteer)                              (in-memory grid)        (exact DP)
```

**External calls: one per request.** The only routing API call is OSRM's public server (`router.project-osrm.org`), which is free and needs no key. A single `/route` call returns the geometry, distance and duration. Geocoding `"City, ST"` inputs and every fuel station happens locally, so a typical request makes exactly one external HTTP call. Only free-form addresses fall back to Nominatim (OpenStreetMap), which adds a second call. Results are cached (route + plan, 24 h), so repeated requests return in about 2 ms. Outbound HTTP uses one pooled session with retries and timeouts, and per-client throttling protects the free upstream services.

**Station coordinates.** The CSV has no coordinates, only truck-stop addresses like "I-44, EXIT 283" plus city and state. `load_data` matches each city/state to the US Census Gazetteer (places + county subdivisions, bundled in `data/gazetteer/`). That covers about 97% of stations. The remaining small towns were geocoded once with Nominatim, and the results are committed in `data/geocode_cache.json`, so setup needs no network. Canadian stations are skipped, since trips are US-only. Duplicate OPIS IDs keep their lowest price. The result is 6,621 US stations; 5 towns couldn't be located.

**Finding stations near the route.** The route is resampled every mile. Stations live in an in-memory 0.25° lat/lon grid that is built once per process. Each station within `corridor_miles` gets the route mile it's closest to. A station that has a cheaper one within 5 route miles is dropped, because nobody would pick it and dropping it makes the optimizer about 35× faster.

**Optimizer.** This is the "gas station problem". For a given sequence of stops, the cheapest strategy at each stop is fixed: *fill up* if the next stop is more expensive, otherwise *buy just enough* to reach it (Khuller, Malekian & Mestre, *To fill or not to fill*). So the fuel level on arrival can only take a few values, and a dynamic program over `(station, where we last filled up)` finds the exact cheapest plan. That includes the optional per-stop penalty. With `stop_penalty=0` it matches the classic optimal greedy algorithm, which the tests check on 200 random instances. The default $5 per stop avoids pulling over for 1–2 gallons just to save a few cents. For example, NY→LA goes from 17 stops to 7 for about $7 more fuel.

**Speed.** The app's own work (geocoding, corridor search, optimizer) takes about 10–20 ms on a cross-country route. The rest of an uncached request (0.3–2 s) is the public OSRM server. Pointing `OSRM_URL` at a self-hosted OSRM would cut that to tens of milliseconds.

## Assumptions

- **Empty tank at the start.** All fuel for the trip is bought on the route, so `total_gallons = distance / 10` exactly. The first stop is within the first 30 miles of the route (or is the first station on it), and the fuel used to get there is bought at that stop.
- **The tank ends near empty.** At the last stop you only buy what's needed to reach the destination.
- The provided price file has only 16 California stations, so long routes inside California can return `422` (no station within range).
- Station locations are city-level, which is why `corridor_miles` defaults to 10 and `off_route_miles` is approximate. Detours aren't counted against range.
- Each station's price is the CSV's `Retail Price`.

## Configuration

Planner settings live in the `FUEL_PLANNER` dict in `config/settings.py` (vehicle range and mpg, corridor width, origin search window, stop penalty, pruning window, cache TTL, upstream URLs).

| environment variable | default |
|---|---|
| `DJANGO_DEBUG` | off; when off, `DJANGO_SECRET_KEY` is required |
| `DJANGO_SECRET_KEY` | none |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` |
| `DJANGO_DB_PATH` | `db.sqlite3` |
| `API_THROTTLE_RATE` | `60/min` |
| `LOG_LEVEL` | `INFO` |
| `OSRM_URL`, `NOMINATIM_URL` | the public OSRM and Nominatim servers |

To reload from a new price file: `python manage.py load_data --csv path/to/prices.csv`. Without `--offline`, it geocodes any new towns through Nominatim at 1 request per second and caches the results. The station index is built once per process, so restart the app servers after a reload. For a multi-process deployment, switch `CACHES` to Redis or Memcached so workers share the route cache.

## Layout

```
config/                           Django project settings and URLs
fuelplanner/
  conf.py                         typed access to the FUEL_PLANNER settings
  models.py                       Place (gazetteer), FuelStation
  views.py, serializers.py        /api/route/ and /map/, request and response serializers
  services/
    planner.py                    orchestrates one trip plan
    geocoding.py                  input parsing, local gazetteer lookup, Nominatim fallback
    routing.py                    OSRM client (one call, cached)
    stations.py                   in-memory grid index and corridor search
    optimizer.py                  candidate pruning and the exact DP optimizer
    geo.py                        haversine, resampling, US bounds
    http.py                       pooled HTTP session with retries
  importers/
    gazetteer.py                  Census gazetteer -> city name index
    fuel_prices.py                OPIS price CSV reader
  management/commands/load_data.py
  templates/fuelplanner/map.html  Leaflet map
  tests/
data/                             Census gazetteer, geocode cache (fuel CSV is copied in locally)
```
