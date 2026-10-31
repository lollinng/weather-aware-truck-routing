import itertools
from datetime import timedelta

import pytest

from planner.domain.checkpoints import checkpoint_distances, sample_checkpoints
from planner.domain.geo import METERS_PER_MILE
from planner.domain.hos import ContinuousDriving, HoursOfService

from .conftest import T0, straight_route

MI = METERS_PER_MILE


@pytest.mark.parametrize(
    ("total_mi", "interval_mi", "expected_mi"),
    [
        (100, 25, [0, 25, 50, 75, 100]),
        (103, 25, [0, 25, 50, 75, 100, 103]),
        (100.3, 25, [0, 25, 50, 75, 100.3]),  # destination merges with a mark < 0.5 mi away
        (8, 10, [0, 8]),  # shorter than one interval: origin and destination only
    ],
)
def test_checkpoint_distances(total_mi, interval_mi, expected_mi):
    marks = checkpoint_distances(total_mi * MI, interval_mi * MI)
    assert [m / MI for m in marks] == pytest.approx(expected_mi)


def test_spans_tile_the_route():
    line = straight_route(103)
    cps = sample_checkpoints(line, 10 * MI, T0, ContinuousDriving())
    assert cps[0].span_start_m == 0
    assert cps[-1].span_end_m == pytest.approx(line.total_m)
    for a, b in itertools.pairwise(cps):
        assert a.span_end_m == pytest.approx(b.span_start_m)
    assert sum(cp.span_m for cp in cps) == pytest.approx(line.total_m)


def test_eta_follows_drive_time_without_hos():
    line = straight_route(200, mph=50)
    cps = sample_checkpoints(line, 50 * MI, T0, ContinuousDriving())
    assert [cp.eta - T0 for cp in cps] == [timedelta(hours=h) for h in (0, 1, 2, 3, 4)]


def test_eta_includes_hos_stops():
    line = straight_route(1000, mph=50)  # 20 h of driving
    cps = sample_checkpoints(line, 50 * MI, T0, HoursOfService())
    by_mile = {round(cp.distance_m / MI): cp for cp in cps}
    assert by_mile[400].eta - T0 == timedelta(hours=8)  # right at the break
    assert by_mile[450].eta - T0 == timedelta(hours=9.5)  # 9 h driving + 30 min break
    assert by_mile[600].eta - T0 == timedelta(hours=22.5)  # 12 h driving + break + 10 h rest
