from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from planner.providers.geocoding import Place
from planner.providers.http import UpstreamRateLimited
from planner.services.trip_planner import TripPlanner
from planner.views import PlanView

from .fakes import FakeRoutePlanner, FakeWeather


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def fake_planner(monkeypatch):
    weather = FakeWeather()
    monkeypatch.setattr(
        PlanView, "get_planner", lambda self: TripPlanner(FakeRoutePlanner(), weather)
    )
    return weather


def plan_body(**overrides):
    body = {
        "origin": {"label": "Amarillo, TX", "lat": 35.0, "lon": -100.0},
        "destination": {"label": "North Platte, NE", "lat": 39.3, "lon": -100.0},
        "departure": (timezone.now() + timedelta(minutes=5)).isoformat(),
        "load_weight_lb": 42_000,
        "interval_miles": 25,
        "hos": True,
    }
    body.update(overrides)
    return body


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_plan_end_to_end_with_fake_providers(client, fake_planner):
    response = client.post("/api/plan", plan_body(), format="json")
    assert response.status_code == 200, response.content
    plan = response.json()

    routes = {r["id"]: r for r in plan["routes"]}
    assert list(routes) == ["A", "B", "C"]
    # Route A (fastest) runs through 40 mph wind; with a 42,000 lb load that is Severe.
    assert routes["A"]["summary"]["miles"]["severe"] == pytest.approx(300, abs=0.5)
    assert plan["recommendation"]["route_id"] == "B"
    assert routes["B"]["recommended"] and routes["B"]["rank"] == 1
    reasons = plan["recommendation"]["reasons"]
    assert reasons[0] == "Same weather risk as Route C, but 50 min faster."
    assert reasons[1].startswith("300 mi fewer Severe-risk miles than Route A")

    a_checkpoint = routes["A"]["checkpoints"][1]
    assert a_checkpoint["mile"] == 25
    assert a_checkpoint["risk"] == {
        "level": "severe",
        "wind": "severe",
        "rain": "low",
        "snow": "low",
        "load_adjusted": True,
        "drivers": ["wind"],
    }
    assert routes["A"]["checkpoints"][-1]["mile"] == pytest.approx(300)
    assert routes["A"]["trip_time_s"] == routes["A"]["drive_time_s"]  # 5 h, no HOS stop needed

    heatmap = plan["heatmap"]
    cells = len(heatmap["cells"])
    assert heatmap["frame_count"] == 50
    assert all(len(v) == cells * 50 for v in heatmap["metrics"].values())
    assert len(routes["A"]["track"]["coordinates"]) == 48 * 4 + 1


def test_lighter_load_changes_the_risk(client, fake_planner):
    plan = client.post("/api/plan", plan_body(load_weight_lb=20_000), format="json").json()
    route_a = next(r for r in plan["routes"] if r["id"] == "A")
    assert route_a["summary"]["miles"]["high"] == pytest.approx(300, abs=0.5)
    assert route_a["summary"]["miles"]["severe"] == 0


def test_long_trip_gets_hos_stops(client, monkeypatch):
    monkeypatch.setattr(
        PlanView,
        "get_planner",
        lambda self: TripPlanner(FakeRoutePlanner(900), FakeWeather()),
    )
    plan = client.post("/api/plan", plan_body(), format="json").json()
    route = plan["routes"][0]  # 900 mi at 60 mph = 15 h of driving
    assert [s["kind"] for s in route["stops"]] == ["break", "rest"]
    assert route["trip_time_s"] == 15 * 3600 + 30 * 60 + 10 * 3600


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"interval_miles": 15}, "interval_miles"),
        ({"load_weight_lb": -1}, "load_weight_lb"),
        ({"load_weight_lb": 90_000}, "load_weight_lb"),
        ({"departure": "2020-01-01T00:00:00Z"}, "departure"),
        ({"departure": (timezone.now() + timedelta(days=9)).isoformat()}, "departure"),
        ({"destination": {"label": "Same", "lat": 35.0, "lon": -100.0}}, "destination"),
        ({"origin": {"label": "Bad", "lat": 95, "lon": 0}}, "origin"),
    ],
)
def test_plan_validation(client, fake_planner, overrides, field):
    response = client.post("/api/plan", plan_body(**overrides), format="json")
    assert response.status_code == 400
    assert field in response.json()


def test_upstream_rate_limit_maps_to_503(client, monkeypatch):
    class Exploding:
        def plan(self, req):
            raise UpstreamRateLimited("weather", "rate limit reached")

    monkeypatch.setattr(PlanView, "get_planner", lambda self: Exploding())
    response = client.post("/api/plan", plan_body(), format="json")
    assert response.status_code == 503
    assert response.json() == {"detail": "rate limit reached", "service": "weather"}


def test_geocode(client, monkeypatch):
    monkeypatch.setattr(
        "planner.views.search_places", lambda q: [Place("Denver, Colorado", 39.74, -104.99)]
    )
    response = client.get("/api/geocode", {"q": "denver"})
    assert response.json() == {
        "results": [{"label": "Denver, Colorado", "lat": 39.74, "lon": -104.99}]
    }


def test_geocode_requires_a_query(client):
    assert client.get("/api/geocode", {"q": "d"}).status_code == 400


def test_cors_allows_the_static_frontend(client):
    response = client.get("/api/health", HTTP_ORIGIN="https://lollinng.github.io")
    assert response["Access-Control-Allow-Origin"] == "https://lollinng.github.io"
    other = client.get("/api/health", HTTP_ORIGIN="https://evil.example")
    assert "Access-Control-Allow-Origin" not in other


def test_long_trips_coarsen_sampling_to_fit_the_forecast_budget(client, monkeypatch):
    weather = FakeWeather()
    monkeypatch.setattr(
        PlanView,
        "get_planner",
        lambda self: TripPlanner(FakeRoutePlanner(2000), weather, location_budget=560),
    )
    plan = client.post("/api/plan", plan_body(interval_miles=10), format="json").json()
    assert plan["request"]["interval_miles"] == 10
    assert plan["interval_miles"] == 25  # 3 x 201 checkpoints at 10 mi would not fit
    assert "every 25 mi instead" in plan["notices"][0]
    assert sum(weather.calls) <= 560


def test_heatmap_shrinks_before_sampling_does(client, monkeypatch):
    weather = FakeWeather()
    monkeypatch.setattr(
        PlanView,
        "get_planner",
        lambda self: TripPlanner(FakeRoutePlanner(1000), weather, location_budget=560),
    )
    plan = client.post("/api/plan", plan_body(interval_miles=10), format="json").json()
    assert plan["interval_miles"] == 10 and plan["notices"] == []
    assert len(plan["heatmap"]["cells"]) <= 560 - 3 * 101
