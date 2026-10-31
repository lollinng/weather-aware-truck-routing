import itertools

import pytest

from planner.domain.geo import (
    METERS_PER_MILE,
    RouteLine,
    decode_polyline,
    destination_point,
    haversine_m,
)

from .conftest import straight_route


def test_haversine_known_distance():
    # Chicago -> Denver is ~920 miles as the crow flies.
    miles = haversine_m(41.8781, -87.6298, 39.7392, -104.9903) / METERS_PER_MILE
    assert miles == pytest.approx(920, abs=5)


def test_destination_point_round_trip():
    lat, lon = destination_point(40.0, -100.0, 90.0, 50_000)
    assert haversine_m(40.0, -100.0, lat, lon) == pytest.approx(50_000, rel=1e-6)


def test_decode_polyline_precision_5_reference():
    # Reference example from Google's polyline algorithm documentation.
    coords = decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@", precision=5)
    flat = [value for point in coords for value in point]
    assert flat == pytest.approx([38.5, -120.2, 40.7, -120.95, 43.252, -126.453])


def test_route_line_interpolates_distance_and_time():
    line = straight_route(100, mph=50)
    assert line.total_m / METERS_PER_MILE == pytest.approx(100, rel=1e-6)
    assert line.total_s == pytest.approx(2 * 3600, rel=1e-6)
    p = line.at_distance(25.5 * METERS_PER_MILE)
    assert p.drive_s == pytest.approx(25.5 / 50 * 3600, rel=1e-6)
    q = line.at_drive_time(p.drive_s)
    assert (q.lat, q.lon) == pytest.approx((p.lat, p.lon))


def test_at_distance_clamps_to_route():
    line = straight_route(10)
    assert line.at_distance(-5).distance_m == 0
    assert line.at_distance(1e9).distance_m == pytest.approx(line.total_m)


def test_from_timed_spans_distributes_time_by_distance():
    coords = [(35.0, -100.0), (35.01, -100.0), (35.03, -100.0), (35.04, -100.0)]
    line = RouteLine.from_timed_spans(coords, [(0, 2, 300.0), (2, 3, 100.0)])
    assert line.cum_s[1] == pytest.approx(100, rel=1e-3)  # 1/3 of the first span's distance
    assert line.cum_s[2] == pytest.approx(300)
    assert line.total_s == pytest.approx(400)


def test_simplify_drops_collinear_points_and_keeps_corners():
    coords = [(35.0, -100.0 + i * 0.01) for i in range(50)] + [
        (35.0 + i * 0.01, -99.51) for i in range(1, 50)
    ]
    line = RouteLine(coords, list(range(len(coords))))
    kept = line.simplified_indices(10)
    assert kept[0] == 0 and kept[-1] == len(coords) - 1
    assert 49 in kept  # the corner
    assert len(kept) <= 4


def test_slice_coords_spans_requested_stretch():
    line = straight_route(10)
    stretch = line.slice_coords(2.5 * METERS_PER_MILE, 4.5 * METERS_PER_MILE)
    length = sum(haversine_m(*a, *b) for a, b in itertools.pairwise(stretch))
    assert length == pytest.approx(2 * METERS_PER_MILE, rel=1e-6)
