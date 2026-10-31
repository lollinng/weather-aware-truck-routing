"""Checkpoint sampling: where along a route weather is evaluated, and when the truck is there."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .geo import RouteLine
from .hos import DrivingSchedule

# A destination this close to the last regular checkpoint replaces it instead of adding a
# near-duplicate sample.
MERGE_DESTINATION_WITHIN_M = 800.0


@dataclass(frozen=True, slots=True)
class Checkpoint:
    index: int
    lat: float
    lon: float
    distance_m: float
    drive_s: float
    elapsed_s: float  # wall clock since departure, including HOS stops
    eta: datetime
    # Stretch of road this checkpoint stands for: half-way to its neighbours. The stretches
    # tile the route exactly, so "miles at risk level X" sums to the route length.
    span_start_m: float
    span_end_m: float

    @property
    def span_m(self) -> float:
        return self.span_end_m - self.span_start_m


def checkpoint_distances(total_m: float, interval_m: float) -> list[float]:
    """0, interval, 2·interval, … plus the destination."""
    if interval_m <= 0:
        raise ValueError("interval must be positive")
    marks = [0.0]
    d = interval_m
    while d < total_m:
        marks.append(d)
        d += interval_m
    if len(marks) > 1 and total_m - marks[-1] < MERGE_DESTINATION_WITHIN_M:
        marks[-1] = total_m
    else:
        marks.append(total_m)
    return marks


def sample_checkpoints(
    line: RouteLine,
    interval_m: float,
    departure: datetime,
    schedule: DrivingSchedule,
) -> list[Checkpoint]:
    marks = checkpoint_distances(line.total_m, interval_m)
    checkpoints = []
    for i, mark in enumerate(marks):
        point = line.at_distance(mark)
        elapsed = schedule.elapsed_for_drive(point.drive_s)
        span_start = 0.0 if i == 0 else (marks[i - 1] + mark) / 2
        span_end = line.total_m if i == len(marks) - 1 else (mark + marks[i + 1]) / 2
        checkpoints.append(
            Checkpoint(
                index=i,
                lat=point.lat,
                lon=point.lon,
                distance_m=point.distance_m,
                drive_s=point.drive_s,
                elapsed_s=elapsed,
                eta=departure + timedelta(seconds=elapsed),
                span_start_m=span_start,
                span_end_m=span_end,
            )
        )
    return checkpoints
