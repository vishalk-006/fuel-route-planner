from django.urls import path

from fuelplanner.views import TripMapView, TripPlanView

urlpatterns = [
    path("api/route/", TripPlanView.as_view(), name="route-plan"),
    path("map/", TripMapView.as_view(), name="route-map"),
]
