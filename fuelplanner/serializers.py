from rest_framework import serializers

from fuelplanner.conf import planner_settings
from fuelplanner.services.planner import TripPlan, TripRequest


class RoundedFloatField(serializers.FloatField):
    def __init__(self, decimals: int, **kwargs) -> None:
        self.decimals = decimals
        super().__init__(read_only=True, **kwargs)

    def to_representation(self, value: float) -> float:
        return round(float(value), self.decimals)


class TripRequestSerializer(serializers.Serializer):
    start = serializers.CharField(max_length=200, help_text='"City, ST", a street address, or "lat,lon".')
    finish = serializers.CharField(max_length=200, help_text='"City, ST", a street address, or "lat,lon".')
    corridor_miles = serializers.FloatField(
        required=False,
        min_value=1,
        max_value=25,
        help_text="Maximum distance between the route and a usable station.",
    )
    stop_penalty = serializers.FloatField(
        required=False,
        min_value=0,
        max_value=100,
        help_text="Dollar cost assigned to each stop; 0 gives the cheapest fuel regardless of stops.",
    )

    def to_trip_request(self) -> TripRequest:
        config = planner_settings()
        data = self.validated_data
        return TripRequest(
            start=data["start"].strip(),
            finish=data["finish"].strip(),
            corridor_miles=data.get("corridor_miles", config.corridor_miles),
            stop_penalty=data.get("stop_penalty", config.stop_penalty),
        )


class LocationSerializer(serializers.Serializer):
    label = serializers.CharField()
    lat = RoundedFloatField(6)
    lon = RoundedFloatField(6)
    source = serializers.CharField()


class StationSerializer(serializers.Serializer):
    opis_id = serializers.IntegerField()
    name = serializers.CharField()
    address = serializers.CharField()
    city = serializers.CharField()
    state = serializers.CharField()
    lat = RoundedFloatField(6)
    lon = RoundedFloatField(6)


class FuelStopSerializer(serializers.Serializer):
    mile = RoundedFloatField(1, source="candidate.mile")
    off_route_miles = RoundedFloatField(1, source="candidate.off_route_miles")
    station = StationSerializer(source="candidate.station")
    price_per_gallon = RoundedFloatField(4, source="candidate.station.price")
    fuel_on_arrival_gallons = RoundedFloatField(2)
    gallons = RoundedFloatField(2)
    cost = RoundedFloatField(2)


class TripPlanSerializer(serializers.Serializer):
    start = serializers.SerializerMethodField()
    finish = serializers.SerializerMethodField()
    distance_miles = RoundedFloatField(1)
    duration_hours = RoundedFloatField(2)
    vehicle = serializers.SerializerMethodField()
    parameters = serializers.SerializerMethodField()
    fuel_stops = FuelStopSerializer(source="fuel_plan.stops", many=True)
    total_gallons = RoundedFloatField(2, source="fuel_plan.total_gallons")
    total_fuel_cost = RoundedFloatField(2, source="fuel_plan.total_cost")
    stations_in_corridor = serializers.IntegerField()
    route = serializers.SerializerMethodField()

    def get_start(self, plan: TripPlan) -> dict:
        return {"query": plan.request.start, **LocationSerializer(plan.start).data}

    def get_finish(self, plan: TripPlan) -> dict:
        return {"query": plan.request.finish, **LocationSerializer(plan.finish).data}

    def get_vehicle(self, plan: TripPlan) -> dict:
        vehicle = plan.vehicle
        return {
            "range_miles": vehicle.range_miles,
            "mpg": vehicle.mpg,
            "tank_gallons": vehicle.range_miles / vehicle.mpg,
        }

    def get_parameters(self, plan: TripPlan) -> dict:
        return {"corridor_miles": plan.request.corridor_miles, "stop_penalty": plan.request.stop_penalty}

    def get_route(self, plan: TripPlan) -> dict:
        return {
            "type": "LineString",
            "coordinates": [[round(point.lon, 5), round(point.lat, 5)] for point in plan.route],
        }
