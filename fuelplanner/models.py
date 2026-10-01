from django.db import models


class Place(models.Model):
    """A US city or town centroid from the Census Gazetteer, keyed by normalized name."""

    state = models.CharField(max_length=2)
    key = models.CharField(max_length=128)
    name = models.CharField(max_length=128)
    lat = models.FloatField()
    lon = models.FloatField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["state", "key"], name="unique_place_state_key")]

    def __str__(self) -> str:
        return f"{self.name}, {self.state}"


class FuelStation(models.Model):
    class GeocodeSource(models.TextChoices):
        GAZETTEER = "gazetteer"
        NOMINATIM = "nominatim"

    opis_id = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=128)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=128)
    state = models.CharField(max_length=2)
    rack_id = models.PositiveIntegerField(null=True, blank=True)
    price = models.DecimalField(max_digits=7, decimal_places=4)
    lat = models.FloatField()
    lon = models.FloatField()
    geocode_source = models.CharField(max_length=16, choices=GeocodeSource)

    def __str__(self) -> str:
        return f"{self.name} ({self.city}, {self.state})"
