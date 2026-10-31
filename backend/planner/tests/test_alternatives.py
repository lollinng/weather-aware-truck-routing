import pytest

from planner.domain.alternatives import (
    has_backtrack,
    is_distinct,
    overlap_ratio,
    pick_distinct,
    via_candidates,
)
from planner.domain.geo import RouteLine, haversine_m

from .conftest import straight_route


def test_identical_routes_fully_overlap():
    line = straight_route(50)
    assert overlap_ratio(line, line) == pytest.approx(1.0)
    assert not is_distinct(line, [line])


def test_parallel_routes_far_apart_are_distinct():
    a = straight_route(50)
    b = straight_route(50, start=(35.0, -99.5))  # ~28 miles east
    assert overlap_ratio(a, b) == 0
    assert is_distinct(a, [b])


def test_via_candidates_are_offset_from_the_route():
    line = straight_route(300)
    origin, destination = (line.lats[0], line.lons[0]), (line.lats[-1], line.lons[-1])
    vias = via_candidates(line, origin, destination)
    assert len(vias) == 8
    mid = line.at_distance(line.total_m / 2)
    # First pair: either side of the midpoint, 15% of the 300 mi chord away.
    for lat, lon in vias[:2]:
        assert haversine_m(mid.lat, mid.lon, lat, lon) == pytest.approx(
            0.15 * line.total_m, rel=0.01
        )
    assert (vias[0][1] - mid.lon) * (vias[1][1] - mid.lon) < 0  # opposite sides


def out_and_back(miles: float) -> RouteLine:
    go = straight_route(miles)
    coords = go.coords() + list(reversed(go.coords()))[1:]
    tail = [(35.0, -100.0 + i * 0.02) for i in range(1, 60)]
    coords += tail
    return RouteLine(coords, [float(i) for i in range(len(coords))])


def test_backtrack_detection():
    assert has_backtrack(out_and_back(20))
    assert not has_backtrack(straight_route(200))


def test_pick_distinct_filters_duplicates_and_slow_routes():
    base = straight_route(100, mph=60)
    duplicate = straight_route(100, mph=59)
    slow = straight_route(100, mph=30, start=(35.0, -99.0))  # 2x slower
    good = straight_route(100, mph=55, start=(35.0, -99.5))
    assert pick_distinct([base], [duplicate, slow, good], want=3) == [2]
