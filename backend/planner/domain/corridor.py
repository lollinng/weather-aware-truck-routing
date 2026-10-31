"""The weather-heatmap corridor: a lattice of forecast points around the candidate routes.

Points sit on a *global* lattice (multiples of ``step`` degrees) rather than a grid fitted to
each trip, so overlapping trips share forecast points and therefore cache entries. The step
is the finest one that keeps the corridor within ``max_cells`` points, which bounds the
number of weather API calls per plan regardless of trip length.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from .geo import EARTH_RADIUS_M, METERS_PER_MILE, RouteLine, haversine_m

LATTICE_STEPS_DEG = (0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.75, 1.0, 1.5)
METERS_PER_DEG_LAT = EARTH_RADIUS_M * math.pi / 180


@dataclass(frozen=True, slots=True)
class CorridorGrid:
    step_deg: float
    row0: int  # lattice index of the southernmost row: lat = (row0 + row) * step
    col0: int  # lattice index of the westernmost column: lon = (col0 + col) * step
    rows: int
    cols: int
    cells: tuple[tuple[int, int], ...]  # (row, col) of corridor points, row-major

    @property
    def south(self) -> float:
        return round(self.row0 * self.step_deg, 6)

    @property
    def west(self) -> float:
        return round(self.col0 * self.step_deg, 6)

    def point(self, row: int, col: int) -> tuple[float, float]:
        return (
            round((self.row0 + row) * self.step_deg, 6),
            round((self.col0 + col) * self.step_deg, 6),
        )

    def points(self) -> list[tuple[float, float]]:
        return [self.point(r, c) for r, c in self.cells]


def corridor_buffer_m(lines: Sequence[RouteLine]) -> float:
    """Half-width of the corridor: ~5% of the longest route, between 20 and 60 miles."""
    longest_mi = max(line.total_m for line in lines) / METERS_PER_MILE
    return min(60.0, max(20.0, 0.05 * longest_mi)) * METERS_PER_MILE


def _cells_for_step(
    lines: Sequence[RouteLine], step: float, buffer_m: float
) -> set[tuple[int, int]]:
    """Global lattice indices within ``buffer_m`` of any route."""
    sample_m = min(buffer_m / 2, step * METERS_PER_DEG_LAT / 2)
    cells: set[tuple[int, int]] = set()
    reach_rows = math.ceil(buffer_m / (step * METERS_PER_DEG_LAT)) + 1
    for line in lines:
        for p in line.resample(sample_m):
            reach_cols = (
                math.ceil(
                    buffer_m
                    / (step * METERS_PER_DEG_LAT * max(0.05, math.cos(math.radians(p.lat))))
                )
                + 1
            )
            r_mid, c_mid = round(p.lat / step), round(p.lon / step)
            for r in range(r_mid - reach_rows, r_mid + reach_rows + 1):
                for c in range(c_mid - reach_cols, c_mid + reach_cols + 1):
                    if (r, c) in cells:
                        continue
                    if haversine_m(p.lat, p.lon, r * step, c * step) <= buffer_m:
                        cells.add((r, c))
    return cells


def build_corridor(
    lines: Sequence[RouteLine], *, max_cells: int = 260, buffer_m: float | None = None
) -> CorridorGrid:
    if not lines:
        raise ValueError("at least one route is required")
    buffer_m = buffer_m if buffer_m is not None else corridor_buffer_m(lines)
    # Rough corridor area -> skip steps that are obviously too fine before doing real work.
    area_m2 = sum(line.total_m for line in lines) * 2 * buffer_m
    cells: set[tuple[int, int]] = set()
    step = LATTICE_STEPS_DEG[-1]
    for candidate in LATTICE_STEPS_DEG:
        cell_m = candidate * METERS_PER_DEG_LAT
        if area_m2 / (cell_m * cell_m) > 3 * max_cells and candidate != LATTICE_STEPS_DEG[-1]:
            continue
        cells = _cells_for_step(lines, candidate, buffer_m)
        step = candidate
        if len(cells) <= max_cells:
            break
    rows_idx = [r for r, _ in cells]
    cols_idx = [c for _, c in cells]
    row0, col0 = min(rows_idx), min(cols_idx)
    ordered = tuple(sorted((r - row0, c - col0) for r, c in cells))
    return CorridorGrid(
        step_deg=step,
        row0=row0,
        col0=col0,
        rows=max(rows_idx) - row0 + 1,
        cols=max(cols_idx) - col0 + 1,
        cells=ordered,
    )
