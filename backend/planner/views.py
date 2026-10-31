from __future__ import annotations

import logging
from dataclasses import asdict

from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .providers.geocoding import search_places
from .providers.http import UpstreamError
from .serializers import GeocodeQuerySerializer, PlanRequestSerializer
from .services.trip_planner import TripPlanner

log = logging.getLogger(__name__)


def upstream_error_response(exc: UpstreamError) -> Response:
    log.warning("upstream failure: %s", exc)
    return Response({"detail": exc.message, "service": exc.service}, status=exc.status_code)


class HealthView(APIView):
    def get(self, request: Request) -> Response:
        return Response({"status": "ok"})


class GeocodeView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "geocode"

    def get(self, request: Request) -> Response:
        query = GeocodeQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        try:
            places = search_places(query.validated_data["q"])
        except UpstreamError as exc:
            return upstream_error_response(exc)
        return Response({"results": [asdict(place) for place in places]})


class PlanView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "plan"

    def get_planner(self) -> TripPlanner:
        return TripPlanner()

    def post(self, request: Request) -> Response:
        payload = PlanRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            plan = self.get_planner().plan(payload.to_request())
        except UpstreamError as exc:
            return upstream_error_response(exc)
        return Response(plan)
