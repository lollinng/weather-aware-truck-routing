"""In-memory stand-ins for the routing and weather providers."""

from __future__ import annotations

from datetime import datetime

from planner.domain.geo import LatLon
from planner.domain.weather import HOUR, HourlySeries, floor_hour
from planner.providers.routing import RouteOption, RouteSet

from .conftest import straight_route


def encode_polyline(coords: list[LatLon], precision: int = 6) -> str:
    factor = 10**precision
    out, prev_lat, prev_lon = [], 0, 0
    for lat, lon in coords:
        ilat, ilon = round(lat * factor), round(lon * factor)
        for delta in (ilat - prev_lat, ilon - prev_lon):
            value = ~(delta << 1) if delta < 0 else delta << 1
            while value >= 0x20:
                out.append(chr((0x20 | (value & 0x1F)) + 63))
                value >>= 5
            out.append(chr(value + 63))
        prev_lat, prev_lon = ilat, ilon
    return "".join(out)


class FakeRoutePlanner:
    """Three parallel north-bound routes; the fastest one runs through FakeWeather's wind."""

    def __init__(self, miles: float = 300):
        self.lines = {
            "fast_windy": straight_route(miles, mph=60, start=(35.0, -100.0)),
            "calm": straight_route(miles, mph=58, start=(35.0, -99.0)),
            "slow_calm": straight_route(miles, mph=50, start=(35.0, -98.0)),
        }

    def options(self, origin, destination, *, load_lb, want=3) -> RouteSet:
        options = [
            RouteOption(line=line, roads=(f"I-{i}0",), provider="fake")
            for i, line in enumerate(self.lines.values(), start=1)
        ]
        ordered = sorted(options, key=lambda o: o.line.total_s)[:want]
        return RouteSet(ordered, provider="fake", profile="truck")


class FakeWeather:
    """Calm everywhere except strong wind west of 99.5°W (the fastest route's corridor)."""

    def __init__(self, windy_west_of: float = -99.5, wind: float = 40.0):
        self.windy_west_of = windy_west_of
        self.wind = wind
        self.calls: list[int] = []

    def forecasts(self, points, first: datetime, last: datetime) -> list[HourlySeries]:
        self.calls.append(len(points))
        start = floor_hour(first) - HOUR
        hours = int((last - start) / HOUR) + 3
        out = []
        for _lat, lon in points:
            wind = self.wind if lon < self.windy_west_of else 8.0
            out.append(
                HourlySeries(
                    start,
                    wind=[wind] * hours,
                    gust=[wind + 10] * hours,
                    rain=[0.0] * hours,
                    snow=[0.0] * hours,
                    temp=[45.0] * hours,
                    code=[3] * hours,
                )
            )
        return out
