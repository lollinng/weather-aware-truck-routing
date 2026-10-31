import pytest

from planner.domain.corridor import build_corridor
from planner.domain.geo import METERS_PER_MILE, haversine_m

from .conftest import straight_route


def test_corridor_respects_cell_budget_and_buffer():
    line = straight_route(400)
    buffer_m = 30 * METERS_PER_MILE
    grid = build_corridor([line], max_cells=150, buffer_m=buffer_m)
    assert 0 < len(grid.cells) <= 150
    samples = line.resample(2_000)
    for lat, lon in grid.points():
        nearest = min(haversine_m(lat, lon, p.lat, p.lon) for p in samples)
        assert nearest <= buffer_m + 2_000


def test_corridor_points_sit_on_a_global_lattice():
    grid = build_corridor([straight_route(150)], max_cells=200)
    for lat, lon in grid.points():
        assert lat / grid.step_deg == pytest.approx(round(lat / grid.step_deg), abs=1e-6)
        assert lon / grid.step_deg == pytest.approx(round(lon / grid.step_deg), abs=1e-6)


def test_cells_are_within_the_reported_bounds():
    grid = build_corridor([straight_route(300)], max_cells=200)
    assert all(0 <= r < grid.rows and 0 <= c < grid.cols for r, c in grid.cells)
    assert list(grid.cells) == sorted(grid.cells)


def test_longer_trips_use_coarser_lattice():
    short = build_corridor([straight_route(100)], max_cells=200)
    long = build_corridor([straight_route(1500)], max_cells=200)
    assert long.step_deg > short.step_deg
