"""Cheapest refuelling plan along a fixed route (the "gas station problem").

The vehicle starts with an empty tank, so every gallon of the trip is bought on
the route. The first stop lies within ``origin_search_miles`` of the start (or is
the first station on the route) and the fuel used to reach it is bought there.

For a fixed sequence of stops the optimal policy is known: fill up if the next
stop is more expensive, otherwise buy just enough to reach it (Khuller, Malekian
& Mestre, "To fill or not to fill"). Arrival fuel is therefore either zero or
``range - distance since the last fill-up``, which makes the search space a DAG
over ``(station, last fill-up station)`` that is solved exactly by dynamic
programming. ``stop_penalty`` adds a fixed cost per stop to trade a few cents of
fuel for fewer stops.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from fuelplanner.services.stations import Candidate

EMPTY_TANK = -1
EPSILON = 1e-9

type State = tuple[int, int]


class NoFeasiblePlan(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Vehicle:
    range_miles: float
    mpg: float


@dataclass(frozen=True, slots=True)
class FuelStop:
    candidate: Candidate
    gallons: float
    cost: float
    fuel_on_arrival_gallons: float


@dataclass(frozen=True, slots=True)
class FuelPlan:
    stops: tuple[FuelStop, ...]

    @property
    def total_gallons(self) -> float:
        return sum(stop.gallons for stop in self.stops)

    @property
    def total_cost(self) -> float:
        return sum(stop.cost for stop in self.stops)


@dataclass(frozen=True, slots=True)
class _Label:
    cost: float
    stops: int
    parent: State | None
    purchase_miles: float

    def beats(self, other: "_Label") -> bool:
        if abs(self.cost - other.cost) > EPSILON:
            return self.cost < other.cost
        return self.stops < other.stops


def plan_fuel_stops(
    candidates: Sequence[Candidate],
    total_miles: float,
    vehicle: Vehicle,
    *,
    origin_search_miles: float,
    stop_penalty: float = 0.0,
) -> FuelPlan:
    """``candidates`` must be sorted by route mile."""
    if total_miles <= 0:
        return FuelPlan(stops=())
    on_route = [candidate for candidate in candidates if candidate.mile < total_miles]
    _ensure_reachable(on_route, total_miles, vehicle.range_miles)
    return _FuelPlanSolver(on_route, total_miles, vehicle, origin_search_miles, stop_penalty).solve()


def prune_candidates(candidates: Sequence[Candidate], window_miles: float) -> list[Candidate]:
    """Drop stations that have a cheaper one within ``window_miles`` along the route."""
    if window_miles <= 0:
        return list(candidates)

    def rank(candidate: Candidate) -> tuple[float, float, int]:
        return candidate.station.price, candidate.mile, candidate.station.id

    def has_cheaper_neighbour(index: int, step: int) -> bool:
        candidate = candidates[index]
        neighbour = index + step
        while 0 <= neighbour < len(candidates) and abs(candidates[neighbour].mile - candidate.mile) <= window_miles:
            if rank(candidates[neighbour]) < rank(candidate):
                return True
            neighbour += step
        return False

    return [
        candidate
        for index, candidate in enumerate(candidates)
        if not has_cheaper_neighbour(index, -1) and not has_cheaper_neighbour(index, 1)
    ]


def _ensure_reachable(candidates: Sequence[Candidate], total_miles: float, range_miles: float) -> None:
    if not candidates:
        raise NoFeasiblePlan("No fuel stations found along the route.")
    previous_mile = 0.0
    for mile in [*(candidate.mile for candidate in candidates), total_miles]:
        if mile - previous_mile > range_miles + EPSILON:
            raise NoFeasiblePlan(
                f"No fuel station between mile {previous_mile:.0f} and mile {mile:.0f} "
                f"of the route, which exceeds the {range_miles:.0f} mile range."
            )
        previous_mile = mile


class _FuelPlanSolver:
    def __init__(
        self,
        candidates: Sequence[Candidate],
        total_miles: float,
        vehicle: Vehicle,
        origin_search_miles: float,
        stop_penalty: float,
    ) -> None:
        self.candidates = candidates
        self.total_miles = total_miles
        self.vehicle = vehicle
        self.origin_search_miles = origin_search_miles
        self.stop_penalty = stop_penalty
        self.miles = [candidate.mile for candidate in candidates]
        self.price_per_mile = [candidate.station.price / vehicle.mpg for candidate in candidates]
        self.labels: dict[State, _Label] = {}
        self.states_at: list[list[State]] = [[] for _ in candidates]

    def solve(self) -> FuelPlan:
        self._seed_first_stops()
        best_finish: _Label | None = None
        for index in range(len(self.candidates)):
            for state in self.states_at[index]:
                label = self.labels[state]
                fuel = self._fuel_on_arrival(state)
                finish = self._finish_from(state, label, fuel)
                if finish is not None and (best_finish is None or finish.beats(best_finish)):
                    best_finish = finish
                self._expand(state, label, fuel)

        if best_finish is None:
            raise NoFeasiblePlan("No fuel plan can complete this route.")
        return self._build_plan(best_finish)

    def _seed_first_stops(self) -> None:
        window = max(self.origin_search_miles, self.miles[0])
        for index, mile in enumerate(self.miles):
            if mile > window:
                break
            cost_to_reach = mile * self.price_per_mile[index] + self.stop_penalty
            self._offer((index, EMPTY_TANK), _Label(cost_to_reach, 1, None, mile))

    def _fuel_on_arrival(self, state: State) -> float:
        index, last_fill = state
        if last_fill == EMPTY_TANK:
            return 0.0
        return self.vehicle.range_miles - (self.miles[index] - self.miles[last_fill])

    def _finish_from(self, state: State, label: _Label, fuel: float) -> _Label | None:
        index = state[0]
        remaining = self.total_miles - self.miles[index]
        if remaining > self.vehicle.range_miles + EPSILON:
            return None
        purchase = max(0.0, remaining - fuel)
        return _Label(label.cost + purchase * self.price_per_mile[index], label.stops, state, purchase)

    def _expand(self, state: State, label: _Label, fuel: float) -> None:
        index = state[0]
        range_miles = self.vehicle.range_miles
        for next_index in range(index + 1, len(self.candidates)):
            distance = self.miles[next_index] - self.miles[index]
            if distance > range_miles + EPSILON:
                break
            if self.price_per_mile[index] < self.price_per_mile[next_index]:
                purchase = range_miles - fuel
                next_state = (next_index, index) if distance < range_miles - EPSILON else (next_index, EMPTY_TANK)
            elif distance >= fuel - EPSILON:
                purchase = max(0.0, distance - fuel)
                next_state = (next_index, EMPTY_TANK)
            else:
                continue
            cost = label.cost + purchase * self.price_per_mile[index] + self.stop_penalty
            self._offer(next_state, _Label(cost, label.stops + 1, state, purchase))

    def _offer(self, state: State, label: _Label) -> None:
        current = self.labels.get(state)
        if current is None:
            self.states_at[state[0]].append(state)
            self.labels[state] = label
        elif label.beats(current):
            self.labels[state] = label

    def _build_plan(self, finish: _Label) -> FuelPlan:
        purchases: list[tuple[State, float]] = []
        label = finish
        while label.parent is not None:
            purchases.append((label.parent, label.purchase_miles))
            label = self.labels[label.parent]
        first_state, first_purchase = purchases[-1]
        purchases[-1] = (first_state, first_purchase + label.purchase_miles)

        stops = []
        for state, miles in reversed(purchases):
            if miles <= EPSILON:
                continue
            candidate = self.candidates[state[0]]
            gallons = miles / self.vehicle.mpg
            stops.append(
                FuelStop(
                    candidate=candidate,
                    gallons=gallons,
                    cost=gallons * candidate.station.price,
                    fuel_on_arrival_gallons=self._fuel_on_arrival(state) / self.vehicle.mpg,
                )
            )
        return FuelPlan(stops=tuple(stops))
