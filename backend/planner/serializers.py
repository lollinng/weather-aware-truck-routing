from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers

from .domain.geo import haversine_m
from .providers.geocoding import Place
from .services.trip_planner import TripRequest

SAMPLING_INTERVALS_MI = (10, 25, 50)
MAX_LOAD_LB = 80_000
# Forecasts run ~16 days out; a departure within a week leaves room for multi-day trips.
MAX_DEPARTURE_AHEAD = timedelta(days=7)
DEPARTURE_GRACE = timedelta(hours=1)
MIN_TRIP_M = 1_000


class PlaceSerializer(serializers.Serializer):
    label = serializers.CharField(max_length=200)
    lat = serializers.FloatField(min_value=-90, max_value=90)
    lon = serializers.FloatField(min_value=-180, max_value=180)


class PlanRequestSerializer(serializers.Serializer):
    origin = PlaceSerializer()
    destination = PlaceSerializer()
    departure = serializers.DateTimeField()
    load_weight_lb = serializers.IntegerField(min_value=0, max_value=MAX_LOAD_LB)
    interval_miles = serializers.ChoiceField(choices=SAMPLING_INTERVALS_MI)
    hos = serializers.BooleanField(default=True)

    def validate_departure(self, value):
        now = timezone.now()
        if value < now - DEPARTURE_GRACE:
            raise serializers.ValidationError("Departure can't be in the past.")
        if value > now + MAX_DEPARTURE_AHEAD:
            raise serializers.ValidationError("Departure must be within the next 7 days.")
        return value

    def validate(self, attrs):
        o, d = attrs["origin"], attrs["destination"]
        if haversine_m(o["lat"], o["lon"], d["lat"], d["lon"]) < MIN_TRIP_M:
            raise serializers.ValidationError(
                {"destination": "Origin and destination are the same place."}
            )
        return attrs

    def to_request(self) -> TripRequest:
        data = self.validated_data
        return TripRequest(
            origin=Place(**data["origin"]),
            destination=Place(**data["destination"]),
            departure=data["departure"],
            load_lb=data["load_weight_lb"],
            interval_mi=int(data["interval_miles"]),
            hos=data["hos"],
        )


class GeocodeQuerySerializer(serializers.Serializer):
    q = serializers.CharField(min_length=2, max_length=200, trim_whitespace=True)
