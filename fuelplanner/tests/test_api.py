from decimal import Decimal
from unittest import mock

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from fuelplanner.models import FuelStation, Place
from fuelplanner.services.stations import reset_station_index

ROUTE_MILES = 530


def fake_osrm_response(*args, **kwargs) -> mock.Mock:
    """A straight road along latitude 40 from longitude -100 to -90."""
    response = mock.Mock(status_code=200)
    response.json.return_value = {
        "code": "Ok",
        "routes": [
            {
                "distance": ROUTE_MILES * 1609.344,
                "duration": 8 * 3600,
                "geometry": {"type": "LineString", "coordinates": [[-100 + i * 0.1, 40.0] for i in range(101)]},
            }
        ],
    }
    return response


@override_settings(FUEL_PLANNER={**settings.FUEL_PLANNER, "STOP_PENALTY": 0.0})
@mock.patch("fuelplanner.services.http.requests.Session.get", side_effect=fake_osrm_response)
class TripPlanApiTests(TestCase):
    url = reverse("route-plan")

    @classmethod
    def setUpTestData(cls):
        Place.objects.create(state="NE", key="west", name="West", lat=40.0, lon=-100.0)
        Place.objects.create(state="IA", key="east", name="East", lat=40.0, lon=-90.0)
        on_route = [(-99.9, "3.50"), (-97.0, "3.00"), (-93.0, "3.20"), (-96.0, "3.90")]
        for opis_id, (lon, price) in enumerate(on_route):
            cls._create_station(opis_id, f"Stop {opis_id}", price, lat=40.01, lon=lon)
        cls._create_station(99, "Far Away", "1.00", lat=38.0, lon=-95.0)

    @staticmethod
    def _create_station(opis_id: int, name: str, price: str, lat: float, lon: float) -> None:
        FuelStation.objects.create(
            opis_id=opis_id,
            name=name,
            address="I-80",
            city="Somewhere",
            state="NE",
            price=Decimal(price),
            lat=lat,
            lon=lon,
            geocode_source=FuelStation.GeocodeSource.GAZETTEER,
        )

    def setUp(self):
        cache.clear()
        reset_station_index()

    def test_returns_route_stops_and_total_cost(self, http_get):
        response = self.client.get(self.url, {"start": "West, NE", "finish": "East, IA"})

        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(http_get.call_count, 1)
        self.assertAlmostEqual(data["distance_miles"], ROUTE_MILES, delta=0.1)
        self.assertAlmostEqual(data["total_gallons"], ROUTE_MILES / 10, delta=0.01)
        self.assertAlmostEqual(sum(stop["cost"] for stop in data["fuel_stops"]), data["total_fuel_cost"], delta=0.05)
        stop_names = {stop["station"]["name"] for stop in data["fuel_stops"]}
        self.assertNotIn("Far Away", stop_names)
        self.assertNotIn("Stop 3", stop_names)
        self.assertEqual(data["route"]["type"], "LineString")
        self.assertIn("/map/?", data["map_url"])

    def test_repeated_request_is_served_from_cache(self, http_get):
        payload = {"start": "West, NE", "finish": "East, IA"}

        self.client.get(self.url, payload)
        response = self.client.post(self.url, payload, content_type="application/json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(http_get.call_count, 1)

    def test_missing_finish_is_rejected(self, http_get):
        response = self.client.get(self.url, {"start": "West, NE"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("finish", response.json())
        http_get.assert_not_called()

    def test_location_outside_usa_is_rejected(self, http_get):
        response = self.client.get(self.url, {"start": "48.85,2.35", "finish": "East, IA"})

        self.assertEqual(response.status_code, 400)
        http_get.assert_not_called()

    def test_map_page_renders(self, http_get):
        response = self.client.get(reverse("route-map"))

        self.assertContains(response, "leaflet")

    def test_map_tiles_send_referrer_required_by_openstreetmap(self, http_get):
        response = self.client.get(reverse("route-map"))

        self.assertContains(response, "referrerPolicy: 'strict-origin-when-cross-origin'")
