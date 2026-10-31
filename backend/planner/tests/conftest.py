from __future__ import annotations

from datetime import UTC, datetime

import pytest
from django.core.cache import cache

from planner.domain.geo import EARTH_RADIUS_M, METERS_PER_MILE, RouteLine

DEG_LAT_PER_MILE = METERS_PER_MILE / (EARTH_RADIUS_M * 3.141592653589793 / 180)


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def straight_route(
    miles: float, *, mph: float = 60.0, start: tuple[float, float] = (35.0, -100.0)
) -> RouteLine:
    """A due-north route with one vertex per mile, driven at constant speed."""
    n = int(miles)
    coords = [(start[0] + i * DEG_LAT_PER_MILE, start[1]) for i in range(n + 1)]
    if miles > n:
        coords.append((start[0] + miles * DEG_LAT_PER_MILE, start[1]))
    line = RouteLine(coords, [0.0] * len(coords))
    seconds_per_meter = 3600 / (mph * METERS_PER_MILE)
    return RouteLine(coords, [d * seconds_per_meter for d in line.cum_m])


T0 = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
