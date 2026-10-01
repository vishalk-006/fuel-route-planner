from itertools import pairwise

from django.test import SimpleTestCase, TestCase

from fuelplanner.models import Place
from fuelplanner.services.geo import LatLon, haversine_miles, resample
from fuelplanner.services.geocoding import GeocodingError, geocode, normalize_place_name, place_keys


class GeometryTests(SimpleTestCase):
    def test_haversine_matches_known_distance(self):
        chicago_to_houston = haversine_miles(41.8781, -87.6298, 29.7604, -95.3698)

        self.assertAlmostEqual(chicago_to_houston, 940, delta=10)

    def test_resample_keeps_endpoints_and_spacing(self):
        points = [LatLon(40.0, -100.0), LatLon(40.0, -99.0)]

        samples = resample(points, step_miles=1.0)

        self.assertEqual((samples[0].lat, samples[0].lon), points[0])
        self.assertEqual((samples[-1].lat, samples[-1].lon), points[-1])
        gaps = [b.mile - a.mile for a, b in pairwise(samples)]
        self.assertTrue(all(gap <= 1.0 + 1e-9 for gap in gaps))


class PlaceNameTests(SimpleTestCase):
    def test_abbreviations_are_normalized(self):
        self.assertEqual(normalize_place_name("Saint Louis"), "st louis")
        self.assertEqual(normalize_place_name("St. Louis"), "st louis")

    def test_compact_key_matches_split_names(self):
        self.assertIn("deforest", place_keys("De Forest"))


class GeocodeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Place.objects.create(state="IL", key="chicago", name="Chicago", lat=41.84, lon=-87.68)

    def test_city_and_state_resolve_locally(self):
        for query in ["Chicago, IL", "chicago, illinois", "Chicago, IL, USA"]:
            with self.subTest(query=query):
                location = geocode(query)
                self.assertEqual(location.source, "gazetteer")
                self.assertAlmostEqual(location.lat, 41.84)

    def test_coordinates_are_accepted(self):
        location = geocode("41.5, -90.1")

        self.assertEqual((location.lat, location.lon, location.source), (41.5, -90.1, "coordinates"))

    def test_locations_outside_usa_are_rejected(self):
        for query in ["48.85, 2.35", "Toronto, ON", ""]:
            with self.subTest(query=query), self.assertRaises(GeocodingError):
                geocode(query)
