import hashlib
import json
from collections.abc import Mapping
from dataclasses import astuple, replace
from typing import Any
from urllib.parse import urlencode

from django.core.cache import cache
from django.urls import reverse
from django.views.generic import TemplateView
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from fuelplanner.conf import planner_settings
from fuelplanner.serializers import TripPlanSerializer, TripRequestSerializer
from fuelplanner.services.geocoding import GeocodingError
from fuelplanner.services.optimizer import NoFeasiblePlan
from fuelplanner.services.planner import TripRequest, plan_trip
from fuelplanner.services.routing import RoutingError


class TripPlanView(APIView):
    """Route between two US locations with the cheapest fuel stops and total fuel cost."""

    def get(self, request: Request) -> Response:
        return self._plan(request, request.query_params)

    def post(self, request: Request) -> Response:
        return self._plan(request, request.data)

    def _plan(self, request: Request, data: Mapping[str, Any]) -> Response:
        serializer = TripRequestSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        trip_request = serializer.to_trip_request()

        cache_key = _cache_key(trip_request)
        payload = cache.get(cache_key)
        if payload is None:
            try:
                plan = plan_trip(trip_request)
            except GeocodingError as exc:
                return _error_response(exc, status.HTTP_400_BAD_REQUEST)
            except NoFeasiblePlan as exc:
                return _error_response(exc, status.HTTP_422_UNPROCESSABLE_ENTITY)
            except RoutingError as exc:
                return _error_response(exc, status.HTTP_502_BAD_GATEWAY)
            payload = TripPlanSerializer(plan).data
            cache.set(cache_key, payload, planner_settings().cache_seconds)

        return Response({**payload, "map_url": _map_url(request, trip_request)})


class TripMapView(TemplateView):
    template_name = "fuelplanner/map.html"


def _error_response(exc: Exception, status_code: int) -> Response:
    return Response({"error": str(exc)}, status=status_code)


def _cache_key(trip_request: TripRequest) -> str:
    normalized = replace(trip_request, start=trip_request.start.lower(), finish=trip_request.finish.lower())
    fingerprint = json.dumps(astuple(normalized))
    return f"fuelplanner:plan:{hashlib.sha256(fingerprint.encode()).hexdigest()}"


def _map_url(request: Request, trip_request: TripRequest) -> str:
    query = urlencode(
        {
            "start": trip_request.start,
            "finish": trip_request.finish,
            "corridor_miles": trip_request.corridor_miles,
            "stop_penalty": trip_request.stop_penalty,
        }
    )
    return request.build_absolute_uri(f"{reverse('route-map')}?{query}")
