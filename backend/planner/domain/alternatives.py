"""Turning "whatever the routing engine returned" into three genuinely different options.

Routing engines return 0–2 alternatives depending on the road network. When they return
fewer than we need, we ask for routes forced through *via points* offset to either side of
the fastest route's midpoint, then keep only candidates that are meaningfully different
(low overlap with routes we already have) and not absurdly long.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

from .geo import (
    METERS_PER_MILE,
    LatLon,
    RouteLine,
    destination_point,
    haversine_m,
    initial_bearing_deg,
)

# Two routes sharing more than this fraction of their length count as the same option.
MAX_OVERLAP = 0.85
# Alternatives slower than this multiple of the fastest route are not worth showing.
MAX_DURATION_RATIO = 1.6
_PROXIMITY_M = 250.0
_HASH_DEG = 0.005  # ~500 m buckets for the proximity index


def via_candidates(primary: RouteLine, origin: LatLon, destination: LatLon) -> list[LatLon]:
    """Via points either side of the route, ordered from most to least promising.

    Offsets scale with trip length (15% / 30% of the straight-line distance, 15–200 km) and
    are measured perpendicular to the origin→destination chord, from the route itself.
    """
    chord_m = haversine_m(*origin, *destination)
    bearing = initial_bearing_deg(*origin, *destination)
    candidates: list[LatLon] = []
    for fraction, scale in ((0.5, 0.15), (0.5, 0.30), (0.35, 0.2), (0.65, 0.2)):
        anchor = primary.at_distance(primary.total_m * fraction)
        offset = min(200_000.0, max(15_000.0, chord_m * scale))
        for side in (90.0, -90.0):
            candidates.append(destination_point(anchor.lat, anchor.lon, bearing + side, offset))
    return candidates


class _ProximityIndex:
    """Grid hash of points along a route for fast "is this point on that route" checks.

    The route is resampled densely first: highway shapes can have vertices a mile apart, so
    indexing raw vertices would miss points in the middle of long straight segments.
    """

    def __init__(self, line: RouteLine):
        self._buckets: dict[tuple[int, int], list[LatLon]] = {}
        for p in line.resample(_PROXIMITY_M / 2):
            key = (math.floor(p.lat / _HASH_DEG), math.floor(p.lon / _HASH_DEG))
            self._buckets.setdefault(key, []).append((p.lat, p.lon))

    def near(self, lat: float, lon: float) -> bool:
        kr, kc = math.floor(lat / _HASH_DEG), math.floor(lon / _HASH_DEG)
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                for plat, plon in self._buckets.get((kr + dr, kc + dc), ()):
                    if haversine_m(lat, lon, plat, plon) <= _PROXIMITY_M:
                        return True
        return False


def overlap_ratio(candidate: RouteLine, existing: RouteLine) -> float:
    """Share of ``candidate``'s length that runs along ``existing``."""
    index = _ProximityIndex(existing)
    samples = candidate.resample(max(500.0, candidate.total_m / 400))
    hits = sum(1 for p in samples if index.near(p.lat, p.lon))
    return hits / len(samples)


def is_distinct(candidate: RouteLine, existing: Iterable[RouteLine]) -> bool:
    return all(
        overlap_ratio(candidate, other) <= MAX_OVERLAP
        and overlap_ratio(other, candidate) <= MAX_OVERLAP
        for other in existing
    )


def has_backtrack(line: RouteLine) -> bool:
    """Detects the out-and-back spur a badly placed via point produces.

    A spur shows up as the route passing the same place twice, far apart in route distance.
    """
    step = max(1_000.0, line.total_m / 300)
    cell_deg = step / 111_000  # hash cells about one sample step wide
    seen: dict[tuple[int, int], float] = {}
    for p in line.resample(step):
        key = (math.floor(p.lat / cell_deg), math.floor(p.lon / cell_deg))
        first = seen.setdefault(key, p.distance_m)
        if p.distance_m - first > max(5 * step, 3 * METERS_PER_MILE):
            return True
    return False


def acceptable(candidate_s: float, fastest_s: float) -> bool:
    return candidate_s <= fastest_s * MAX_DURATION_RATIO


def pick_distinct(
    base: Sequence[RouteLine], candidates: Sequence[RouteLine], want: int
) -> list[int]:
    """Indices of ``candidates`` to add so ``base`` grows to ``want`` distinct routes.

    Greedy, fastest first: a candidate is taken if it isn't much slower than the fastest
    route, has no out-and-back spur, and differs from everything already chosen.
    """
    if not base:
        return []
    chosen = list(base)
    fastest_s = min(line.total_s for line in chosen)
    picked: list[int] = []
    for i in sorted(range(len(candidates)), key=lambda k: candidates[k].total_s):
        if len(chosen) >= want:
            break
        line = candidates[i]
        if (
            acceptable(line.total_s, fastest_s)
            and not has_backtrack(line)
            and is_distinct(line, chosen)
        ):
            chosen.append(line)
            picked.append(i)
    return picked
