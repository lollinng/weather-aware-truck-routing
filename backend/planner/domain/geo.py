"""Geodesy helpers and :class:`RouteLine`, the polyline model the planner works on.

A ``RouteLine`` carries, for every vertex, the cumulative distance (metres) and cumulative
*driving* time (seconds) from the origin. Everything that needs "where is the truck after N
miles / N hours of driving" goes through it, so ETA maths lives in exactly one place.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Sequence
from dataclasses import dataclass

EARTH_RADIUS_M = 6_371_008.8
METERS_PER_MILE = 1609.344

LatLon = tuple[float, float]


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def initial_bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def destination_point(lat: float, lon: float, bearing_deg: float, distance_m: float) -> LatLon:
    """Point reached by travelling ``distance_m`` from (lat, lon) on the given bearing."""
    delta = distance_m / EARTH_RADIUS_M
    theta = math.radians(bearing_deg)
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(
        math.sin(p1) * math.cos(delta) + math.cos(p1) * math.sin(delta) * math.cos(theta)
    )
    l2 = l1 + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(p1),
        math.cos(delta) - math.sin(p1) * math.sin(p2),
    )
    return math.degrees(p2), (math.degrees(l2) + 540) % 360 - 180


def decode_polyline(encoded: str, precision: int = 6) -> list[LatLon]:
    """Decode a Google-style encoded polyline (Valhalla uses precision 6)."""
    coords: list[LatLon] = []
    index = lat = lon = 0
    factor = 10**precision
    length = len(encoded)
    while index < length:
        deltas = []
        for _ in range(2):
            shift = result = 0
            while True:
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            deltas.append(~(result >> 1) if result & 1 else result >> 1)
        lat += deltas[0]
        lon += deltas[1]
        coords.append((lat / factor, lon / factor))
    return coords


@dataclass(frozen=True, slots=True)
class PointOnRoute:
    lat: float
    lon: float
    distance_m: float
    drive_s: float


class RouteLine:
    """An immutable route polyline with cumulative distance and driving time per vertex."""

    __slots__ = ("cum_m", "cum_s", "lats", "lons")

    def __init__(self, coords: Sequence[LatLon], cum_s: Sequence[float]):
        if len(coords) < 2:
            raise ValueError("A route needs at least two coordinates.")
        if len(cum_s) != len(coords):
            raise ValueError("cum_s must have one entry per coordinate.")
        self.lats = [c[0] for c in coords]
        self.lons = [c[1] for c in coords]
        cum_m = [0.0]
        for i in range(1, len(coords)):
            cum_m.append(
                cum_m[-1]
                + haversine_m(self.lats[i - 1], self.lons[i - 1], self.lats[i], self.lons[i])
            )
        self.cum_m = cum_m
        # Guard against tiny negative steps from upstream rounding: time never runs backwards.
        fixed = [0.0]
        for value in list(cum_s)[1:]:
            fixed.append(max(fixed[-1], float(value)))
        self.cum_s = fixed

    # -- construction ---------------------------------------------------------------------
    @classmethod
    def from_timed_spans(
        cls, coords: Sequence[LatLon], spans: Sequence[tuple[int, int, float]]
    ) -> RouteLine:
        """Build from coordinates plus ``(begin_index, end_index, seconds)`` spans.

        Routing engines report travel time per maneuver/step, not per vertex. Within a span the
        time is distributed proportionally to distance, i.e. constant speed inside a maneuver.
        Spans must be contiguous and cover the whole line.
        """
        cum_m = [0.0]
        for i in range(1, len(coords)):
            cum_m.append(cum_m[-1] + haversine_m(*coords[i - 1], *coords[i]))
        cum_s = [0.0] * len(coords)
        for begin, end, seconds in spans:
            span_m = cum_m[end] - cum_m[begin]
            for k in range(begin + 1, end + 1):
                if span_m > 0:
                    share = (cum_m[k] - cum_m[begin]) / span_m
                else:
                    share = (k - begin) / max(1, end - begin)
                cum_s[k] = cum_s[begin] + seconds * share
        return cls(coords, cum_s)

    @classmethod
    def from_segment_durations(
        cls, coords: Sequence[LatLon], durations: Sequence[float]
    ) -> RouteLine:
        """Build from per-segment durations (``len(coords) - 1`` values, as OSRM returns)."""
        cum_s = [0.0]
        for value in durations:
            cum_s.append(cum_s[-1] + float(value))
        return cls(coords, cum_s)

    # -- basic properties -----------------------------------------------------------------
    @property
    def total_m(self) -> float:
        return self.cum_m[-1]

    @property
    def total_s(self) -> float:
        return self.cum_s[-1]

    def __len__(self) -> int:
        return len(self.lats)

    def coords(self) -> list[LatLon]:
        return list(zip(self.lats, self.lons, strict=True))

    # -- interpolation --------------------------------------------------------------------
    def _interpolate(self, i: int, frac: float) -> tuple[float, float, float, float]:
        j = min(i + 1, len(self.lats) - 1)
        lat = self.lats[i] + (self.lats[j] - self.lats[i]) * frac
        lon = self.lons[i] + (self.lons[j] - self.lons[i]) * frac
        dist = self.cum_m[i] + (self.cum_m[j] - self.cum_m[i]) * frac
        drive = self.cum_s[i] + (self.cum_s[j] - self.cum_s[i]) * frac
        return lat, lon, dist, drive

    def at_distance(self, distance_m: float) -> PointOnRoute:
        """Position and driving time after ``distance_m`` metres along the route."""
        d = min(max(distance_m, 0.0), self.total_m)
        i = max(0, bisect.bisect_right(self.cum_m, d) - 1)
        i = min(i, len(self.cum_m) - 2)
        seg = self.cum_m[i + 1] - self.cum_m[i]
        frac = 0.0 if seg <= 0 else (d - self.cum_m[i]) / seg
        return PointOnRoute(*self._interpolate(i, frac))

    def at_drive_time(self, drive_s: float) -> PointOnRoute:
        """Position after ``drive_s`` seconds of driving (breaks are handled by the caller)."""
        t = min(max(drive_s, 0.0), self.total_s)
        i = max(0, bisect.bisect_right(self.cum_s, t) - 1)
        i = min(i, len(self.cum_s) - 2)
        seg = self.cum_s[i + 1] - self.cum_s[i]
        frac = 0.0 if seg <= 0 else (t - self.cum_s[i]) / seg
        return PointOnRoute(*self._interpolate(i, frac))

    # -- geometry reduction ---------------------------------------------------------------
    def simplified_indices(self, tolerance_m: float) -> list[int]:
        """Vertex indices kept by Douglas-Peucker at ``tolerance_m`` (endpoints always kept)."""
        n = len(self.lats)
        if n <= 2:
            return list(range(n))
        lat0 = math.radians(sum(self.lats) / n)
        kx = EARTH_RADIUS_M * math.cos(lat0) * math.pi / 180
        ky = EARTH_RADIUS_M * math.pi / 180
        xs = [lon * kx for lon in self.lons]
        ys = [lat * ky for lat in self.lats]
        keep = bytearray(n)
        keep[0] = keep[n - 1] = 1
        tol2 = tolerance_m * tolerance_m
        stack = [(0, n - 1)]
        while stack:
            first, last = stack.pop()
            ax, ay, bx, by = xs[first], ys[first], xs[last], ys[last]
            dx, dy = bx - ax, by - ay
            seg2 = dx * dx + dy * dy
            max_d2, index = -1.0, -1
            for k in range(first + 1, last):
                px, py = xs[k] - ax, ys[k] - ay
                if seg2 == 0:
                    d2 = px * px + py * py
                else:
                    t = max(0.0, min(1.0, (px * dx + py * dy) / seg2))
                    ex, ey = px - t * dx, py - t * dy
                    d2 = ex * ex + ey * ey
                if d2 > max_d2:
                    max_d2, index = d2, k
            if max_d2 > tol2:
                keep[index] = 1
                stack.append((first, index))
                stack.append((index, last))
        return [i for i in range(n) if keep[i]]

    def resample(self, step_m: float) -> list[PointOnRoute]:
        """Evenly spaced points (plus the destination) every ``step_m`` metres."""
        points = []
        d = 0.0
        while d < self.total_m:
            points.append(self.at_distance(d))
            d += step_m
        points.append(self.at_distance(self.total_m))
        return points

    def slice_coords(
        self, start_m: float, end_m: float, indices: Sequence[int] | None = None
    ) -> list[LatLon]:
        """Coordinates of the stretch between two distances (endpoints interpolated).

        ``indices`` restricts interior vertices to a simplified subset, so slices of a
        simplified line stay consistent with the simplified geometry shown on the map.
        """
        start = self.at_distance(start_m)
        end = self.at_distance(end_m)
        interior = indices if indices is not None else range(len(self.lats))
        out: list[LatLon] = [(start.lat, start.lon)]
        for i in interior:
            if start.distance_m < self.cum_m[i] < end.distance_m:
                out.append((self.lats[i], self.lons[i]))
        out.append((end.lat, end.lon))
        return out
