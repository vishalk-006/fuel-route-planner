import random

from django.test import SimpleTestCase

from fuelplanner.services.optimizer import NoFeasiblePlan, Vehicle, plan_fuel_stops, prune_candidates
from fuelplanner.services.stations import Candidate
from fuelplanner.tests.factories import make_candidate

TRUCK = Vehicle(range_miles=500, mpg=10)
ORIGIN_SEARCH_MILES = 30


def greedy_reference_cost(candidates: list[Candidate], total_miles: float, vehicle: Vehicle) -> float:
    """Textbook greedy for the gas station problem; optimal when stops are free."""
    stations = [c for c in candidates if c.mile < total_miles]
    window = max(ORIGIN_SEARCH_MILES, stations[0].mile)
    index = min(
        (i for i, c in enumerate(stations) if c.mile <= window),
        key=lambda i: (stations[i].station.price, stations[i].mile),
    )
    fuel = 0.0
    cost = stations[index].mile * stations[index].station.price / vehicle.mpg
    while True:
        here = stations[index]
        in_range = [j for j in range(index + 1, len(stations)) if stations[j].mile - here.mile <= vehicle.range_miles]
        cheaper = next((j for j in in_range if stations[j].station.price < here.station.price), None)
        remaining = total_miles - here.mile
        if cheaper is None and remaining <= vehicle.range_miles:
            return cost + max(0.0, remaining - fuel) * here.station.price / vehicle.mpg
        if cheaper is not None:
            next_index = cheaper
            purchase = max(0.0, stations[next_index].mile - here.mile - fuel)
        else:
            next_index = min(in_range, key=lambda j: (stations[j].station.price, stations[j].mile))
            purchase = vehicle.range_miles - fuel
        cost += purchase * here.station.price / vehicle.mpg
        fuel = max(0.0, fuel + purchase - (stations[next_index].mile - here.mile))
        index = next_index


def random_route(rng: random.Random) -> tuple[list[Candidate], float]:
    total_miles = rng.uniform(200, 2500)
    miles = [rng.uniform(0, 20)] + [rng.uniform(0, total_miles) for _ in range(rng.randint(5, 40))]
    candidates = [make_candidate(mile, round(rng.uniform(2.5, 4.5), 3), station_id=i) for i, mile in enumerate(miles)]
    return sorted(candidates, key=lambda c: c.mile), total_miles


def plan(candidates: list[Candidate], total_miles: float, stop_penalty: float = 0.0):
    return plan_fuel_stops(
        candidates, total_miles, TRUCK, origin_search_miles=ORIGIN_SEARCH_MILES, stop_penalty=stop_penalty
    )


class PlanFuelStopsTests(SimpleTestCase):
    def test_buys_only_enough_to_reach_a_cheaper_station(self):
        result = plan([make_candidate(5, 3.0), make_candidate(50, 2.0)], total_miles=100)

        self.assertEqual([round(stop.gallons, 6) for stop in result.stops], [5.0, 5.0])
        self.assertAlmostEqual(result.total_cost, 5 * 3.0 + 5 * 2.0)

    def test_fills_up_before_a_more_expensive_station(self):
        candidates = [make_candidate(0, 2.0), make_candidate(400, 4.0), make_candidate(800, 3.0)]

        result = plan(candidates, total_miles=1000)

        purchases = [(stop.candidate.mile, round(stop.gallons, 6)) for stop in result.stops]
        self.assertEqual(purchases, [(0, 50.0), (400, 30.0), (800, 20.0)])
        self.assertAlmostEqual(result.stops[1].fuel_on_arrival_gallons, 10.0)

    def test_total_gallons_cover_the_whole_trip(self):
        rng = random.Random(1)
        for _ in range(50):
            candidates, total_miles = random_route(rng)
            try:
                result = plan(candidates, total_miles, stop_penalty=rng.choice([0, 2, 5]))
            except NoFeasiblePlan:
                continue
            self.assertAlmostEqual(result.total_gallons, total_miles / TRUCK.mpg, places=6)

    def test_matches_optimal_greedy_when_stops_are_free(self):
        rng = random.Random(42)
        compared = 0
        for _ in range(200):
            candidates, total_miles = random_route(rng)
            try:
                result = plan(candidates, total_miles)
            except NoFeasiblePlan:
                continue
            self.assertAlmostEqual(result.total_cost, greedy_reference_cost(candidates, total_miles, TRUCK), places=6)
            compared += 1
        self.assertGreater(compared, 100)

    def test_stop_penalty_trades_cents_for_fewer_stops(self):
        candidates = [make_candidate(mile, 3.0 - mile / 100_000) for mile in range(0, 1000, 20)]

        cheapest = plan(candidates, 1000, stop_penalty=0)
        fewer_stops = plan(candidates, 1000, stop_penalty=5)

        self.assertLess(len(fewer_stops.stops), len(cheapest.stops))
        self.assertLessEqual(cheapest.total_cost, fewer_stops.total_cost)

    def test_gap_longer_than_range_is_infeasible(self):
        with self.assertRaisesMessage(NoFeasiblePlan, "between mile 0 and mile 600"):
            plan([make_candidate(0, 3.0), make_candidate(600, 3.0)], 900)

    def test_no_station_within_range_of_start_is_infeasible(self):
        with self.assertRaises(NoFeasiblePlan):
            plan([make_candidate(550, 3.0)], 900)

    def test_empty_trip_needs_no_fuel(self):
        self.assertEqual(plan([], 0).stops, ())


class PruneCandidatesTests(SimpleTestCase):
    def test_keeps_only_locally_cheapest_stations(self):
        candidates = [make_candidate(0, 3.0), make_candidate(2, 2.9), make_candidate(4, 3.1), make_candidate(20, 3.5)]

        kept = prune_candidates(candidates, window_miles=5)

        self.assertEqual([c.mile for c in kept], [2, 20])
