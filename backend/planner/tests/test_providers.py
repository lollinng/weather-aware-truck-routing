from datetime import timedelta

import pytest
import responses
from django.conf import settings

from planner.domain.geo import METERS_PER_MILE
from planner.providers.http import NoRouteFound, UpstreamError, UpstreamRateLimited
from planner.providers.open_meteo import OpenMeteoClient
from planner.providers.routing import (
    RouteOption,
    RoutePlanner,
    ValhallaRouter,
    main_roads,
    normalize_road,
    straight_line_km,
)

from .conftest import T0, straight_route
from .fakes import encode_polyline

FORECAST_URL = f"{settings.PLANNER['OPEN_METEO_URL']}/v1/forecast"
VALHALLA_URL = f"{settings.PLANNER['VALHALLA_URL']}/route"


def open_meteo_location(hours: int = 6, rain: float = 0.2, showers: float = 0.05) -> dict:
    times = [
        (T0 - timedelta(hours=1) + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M")
        for h in range(hours)
    ]
    return {
        "hourly": {
            "time": times,
            "wind_speed_10m": [12.0] * hours,
            "wind_gusts_10m": [20.0] * hours,
            "rain": [rain] * hours,
            "showers": [showers] * hours,
            "snowfall": [0.0] * hours,
            "temperature_2m": [40.0] * hours,
            "weather_code": [61] * hours,
        }
    }


# -- Open-Meteo ----------------------------------------------------------------------------------


@responses.activate
def test_forecasts_parse_batch_and_sum_rain_with_showers():
    responses.get(FORECAST_URL, json=[open_meteo_location(), open_meteo_location(rain=0.0)])
    client = OpenMeteoClient()
    series = client.forecasts([(40.0, -100.0), (41.0, -101.0)], T0, T0 + timedelta(hours=2))
    first = series[0].sample(T0 + timedelta(minutes=30))
    assert first.rain_in_hr == pytest.approx(0.25)
    assert series[1].sample(T0).rain_in_hr == pytest.approx(0.05)
    params = responses.calls[0].request.params
    assert params["wind_speed_unit"] == "mph"
    assert params["precipitation_unit"] == "inch"
    assert params["latitude"] == "40.00,41.00"


@responses.activate
def test_forecasts_are_cached_and_deduplicated():
    responses.get(FORECAST_URL, json=open_meteo_location())
    client = OpenMeteoClient()
    window = (T0, T0 + timedelta(hours=2))
    a = client.forecasts([(40.001, -100.0), (40.0, -100.002)], *window)  # same 0.01° cell
    b = client.forecasts([(40.0, -100.0)], *window)
    assert len(responses.calls) == 1
    assert a[0] is a[1] and b[0] is not None


@responses.activate
def test_concurrency_rejections_are_retried(monkeypatch):
    monkeypatch.setattr("planner.providers.open_meteo.time.sleep", lambda s: None)
    responses.get(
        FORECAST_URL, status=429, json={"error": True, "reason": "Too many concurrent requests"}
    )
    responses.get(FORECAST_URL, json=open_meteo_location())
    series = OpenMeteoClient().forecasts([(40.0, -100.0)], T0, T0 + timedelta(hours=1))
    assert series[0] is not None
    assert len(responses.calls) == 2


@responses.activate
def test_quota_exhaustion_is_reported_as_rate_limit():
    responses.get(
        FORECAST_URL, status=429, json={"error": True, "reason": "Minutely API request limit"}
    )
    with pytest.raises(UpstreamRateLimited):
        OpenMeteoClient().forecasts([(40.0, -100.0)], T0, T0 + timedelta(hours=1))
    assert len(responses.calls) == 1


# -- Valhalla ------------------------------------------------------------------------------------


def valhalla_trip(coords, seconds=3600.0, names=("I 80 West",)):
    return {
        "legs": [
            {
                "shape": encode_polyline(coords),
                "maneuvers": [
                    {
                        "begin_shape_index": 0,
                        "end_shape_index": len(coords) - 1,
                        "time": seconds,
                        "length": 60.0,
                        "street_names": list(names),
                    },
                    {
                        "begin_shape_index": len(coords) - 1,
                        "end_shape_index": len(coords) - 1,
                        "time": 0,
                        "length": 0,
                    },
                ],
            }
        ]
    }


@responses.activate
def test_valhalla_parses_trip_and_alternates():
    coords = straight_route(60).coords()
    responses.post(
        VALHALLA_URL,
        json={"trip": valhalla_trip(coords), "alternates": [{"trip": valhalla_trip(coords, 4000)}]},
    )
    options = ValhallaRouter().route(
        (35.0, -100.0), (36.0, -100.0), gross_weight_lb=77_000, alternates=2
    )
    assert len(options) == 2
    assert options[0].line.total_m / METERS_PER_MILE == pytest.approx(60, rel=1e-3)
    assert options[0].line.total_s == pytest.approx(3600)
    assert options[0].roads == ("I-80",)
    body = responses.calls[0].request.body
    assert b'"costing": "truck"' in body
    assert b'"weight": 34.93' in body  # 77,000 lb gross in metric tons


@responses.activate
def test_valhalla_no_route_is_a_client_error():
    responses.post(VALHALLA_URL, status=400, json={"error_code": 442, "error": "No path"})
    with pytest.raises(NoRouteFound):
        ValhallaRouter().route((35.0, -100.0), (36.0, -100.0), gross_weight_lb=50_000)


def test_road_name_normalisation():
    assert normalize_road("I 80 West") == "I-80"
    assert normalize_road("US 6") == "US-6"
    assert normalize_road("Main Street") == "Main Street"
    from collections import Counter

    assert main_roads(Counter({"Main Street": 90, "I-80": 50, "US-6": 60})) == ("US-6", "I-80")


# -- RoutePlanner --------------------------------------------------------------------------------


class StubRouter:
    def __init__(self, direct, via_routes=None, fail=False, name="stub", max_km=None):
        self.direct, self.via_routes, self.fail = direct, list(via_routes or []), fail
        self.name, self.profile, self.max_km = name, "truck", max_km
        self.calls = 0

    def accepts(self, points):
        return self.max_km is None or straight_line_km(points) <= self.max_km

    def route(self, origin, destination, *, gross_weight_lb, via=None, alternates=0):
        self.calls += 1
        if self.fail:
            raise UpstreamError("routing", "down")
        if via is None:
            return [RouteOption(line, ("I-1",), self.name) for line in self.direct]
        if not self.via_routes:
            raise UpstreamError("routing", "no edges near via")
        return [RouteOption(self.via_routes.pop(0), ("I-2",), self.name)]


A, B = (35.0, -100.0), (36.4, -100.0)  # ~97 miles apart


def two_routes():
    return [straight_route(100), straight_route(100, start=(35.0, -99.0))]


def test_planner_tops_up_with_via_routes():
    direct = [straight_route(100, mph=60)]
    vias = [
        straight_route(100, mph=59),  # duplicate of the direct route -> rejected
        straight_route(100, mph=55, start=(35.0, -99.5)),
        straight_route(100, mph=54, start=(35.0, -100.5)),
    ]
    router = StubRouter(direct, vias)
    result = RoutePlanner(primary=router, fallback=StubRouter([], fail=True)).options(
        A, B, load_lb=40_000
    )
    assert [round(o.line.total_s / 60) for o in result.options] == [100, 109, 111]
    assert result.provider == "stub" and result.fallback_reason is None


def test_falls_back_when_primary_is_down():
    fallback = StubRouter(
        [straight_route(100), straight_route(100, start=(35.0, -99.0))], name="osrm"
    )
    planner = RoutePlanner(primary=StubRouter([], fail=True), fallback=fallback)
    result = planner.options(A, B, load_lb=0, want=2)
    assert {o.provider for o in result.options} == {"osrm"}
    assert result.fallback_reason == "unavailable"


def test_trips_beyond_the_primary_range_skip_it():
    primary = StubRouter([straight_route(100)], max_km=50)
    fallback = StubRouter(
        [straight_route(100), straight_route(100, start=(35.0, -99.0))], name="osrm"
    )
    result = RoutePlanner(primary=primary, fallback=fallback).options(A, B, load_lb=0, want=2)
    assert primary.calls == 0
    assert result.provider == "osrm" and result.fallback_reason == "distance"


def test_fallback_used_when_it_finds_more_distinct_routes():
    primary = StubRouter([straight_route(100)])  # one route, no via alternatives
    fallback = StubRouter(
        [straight_route(100), straight_route(100, start=(35.0, -99.0))], name="osrm"
    )
    result = RoutePlanner(primary=primary, fallback=fallback).options(A, B, load_lb=0, want=2)
    assert result.provider == "osrm" and result.fallback_reason == "alternatives"


def test_primary_kept_when_fallback_is_no_better():
    primary = StubRouter([straight_route(100)])
    fallback = StubRouter([straight_route(100)], name="osrm")
    result = RoutePlanner(primary=primary, fallback=fallback).options(A, B, load_lb=0, want=2)
    assert result.provider == "stub"


def test_planner_results_are_cached():
    router = StubRouter([straight_route(50), straight_route(50, start=(35.0, -99.0))])
    planner = RoutePlanner(primary=router, fallback=router)
    first = planner.options((35.0, -100.0), (35.7, -100.0), load_lb=1000, want=2)
    router.direct = []  # a second upstream call would now fail
    again = planner.options((35.0, -100.0), (35.7, -100.0), load_lb=1000, want=2)
    assert [o.line.total_s for o in again.options] == [o.line.total_s for o in first.options]
