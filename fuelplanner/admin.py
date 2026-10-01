from django.contrib import admin

from fuelplanner.models import FuelStation, Place


@admin.register(FuelStation)
class FuelStationAdmin(admin.ModelAdmin):
    list_display = ("opis_id", "name", "city", "state", "price", "lat", "lon", "geocode_source")
    list_filter = ("state", "geocode_source")
    search_fields = ("name", "city", "address")


@admin.register(Place)
class PlaceAdmin(admin.ModelAdmin):
    list_display = ("name", "state", "key", "lat", "lon")
    list_filter = ("state",)
    search_fields = ("name", "key")
