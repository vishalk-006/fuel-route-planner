from fuelplanner.services.stations import Candidate, Station


def make_candidate(mile: float, price: float, station_id: int | None = None) -> Candidate:
    station_id = int(mile * 100) if station_id is None else station_id
    station = Station(
        id=station_id,
        opis_id=station_id,
        name=f"Station {station_id}",
        address="",
        city="Austin",
        state="TX",
        price=price,
        lat=30.0,
        lon=-97.0,
    )
    return Candidate(station=station, mile=mile, off_route_miles=0.0)
