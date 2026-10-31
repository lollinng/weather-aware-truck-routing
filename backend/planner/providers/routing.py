"""Route options from Valhalla (truck costing), falling back to OSRM.

Valhalla's ``truck`` costing honours vehicle weight (weight-restricted bridges/roads) and
truck-specific speeds, which is why it's the primary engine. The public FOSSGIS instance
needs no key but rejects requests whose locations span more than 1,500 km in a straight
line; ``VALHALLA_URL``/``VALHALLA_API_KEY``/``VALHALLA_MAX_KM`` point it at an unrestricted
instance (self-hosted, Stadia Maps…) instead.

One engine serves a whole plan, so travel times stay comparable between options: Valhalla
when the trip is in range and it yields enough distinct routes, otherwise OSRM (car profile,
no distance cap) for every option.
"""

from __future__ import annotations

import itertools
import logging
import re
from collections import Counter
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import requests
from django.conf import settings
from django.core.cache import cache

from ..domain.alternatives import pick_distinct, via_candidates
from ..domain.geo import METERS_PER_MILE, LatLon, RouteLine, decode_polyline, haversine_m
from .http import NoRouteFound, UpstreamError, UpstreamRateLimited, session, timeout

log = logging.getLogger(__name__)

TRUCK_TARE_LB = 35_000  # typical empty tractor + 53 ft dry van; routing uses gross weight
LB_PER_METRIC_TON = 2204.62
CACHE_TTL_S = 30 * 60
VIA_BATCH = 4

_ROAD_REF = re.compile(r"^(I|US|[A-Z]{2})[\s-]?(\d{1,4}[A-Z]?)\b")
# Valhalla error codes meaning "the request is fine, there is just no route".
_VALHALLA_NO_ROUTE = {170, 171, 442, 443}


@dataclass(frozen=True, slots=True)
class RouteOption:
    line: RouteLine
    roads: tuple[str, ...]  # main roads by distance driven on them, highway refs first
    provider: str

    @property
    def distance_mi(self) -> float:
        return self.line.total_m / METERS_PER_MILE


def normalize_road(name: str) -> str:
    """'I 80 West' -> 'I-80', 'US 6' -> 'US-6'; other names are returned unchanged."""
    match = _ROAD_REF.match(name.strip())
    return f"{match.group(1)}-{match.group(2)}" if match else name.strip()


def main_roads(miles_by_road: Counter[str], limit: int = 3) -> tuple[str, ...]:
    refs = [(r, m) for r, m in miles_by_road.most_common() if _ROAD_REF.match(r)]
    named = refs or miles_by_road.most_common()
    return tuple(road for road, _ in named[:limit])


def straight_line_km(points: Sequence[LatLon]) -> float:
    return sum(haversine_m(*a, *b) for a, b in itertools.pairwise(points)) / 1000


@dataclass(frozen=True, slots=True)
class RouteSet:
    options: list[RouteOption]  # fastest first
    provider: str
    profile: str  # "truck" or "car"
    fallback_reason: str | None = None  # why the truck router wasn't used, if it wasn't


class ValhallaRouter:
    name = "valhalla"
    profile = "truck"

    def accepts(self, points: Sequence[LatLon]) -> bool:
        limit = settings.PLANNER["VALHALLA_MAX_KM"]
        return not limit or straight_line_km(points) <= limit

    def route(
        self,
        origin: LatLon,
        destination: LatLon,
        *,
        gross_weight_lb: float,
        via: LatLon | None = None,
        alternates: int = 0,
    ) -> list[RouteOption]:
        locations = [{"lat": origin[0], "lon": origin[1]}]
        if via is not None:
            locations.append(
                {
                    "lat": via[0],
                    "lon": via[1],
                    "type": "through",
                    # Snap to a major road so the detour doesn't produce a residential spur.
                    "search_filter": {"min_road_class": "primary"},
                }
            )
        locations.append({"lat": destination[0], "lon": destination[1]})
        body = {
            "locations": locations,
            "costing": "truck",
            "costing_options": {"truck": {"weight": round(gross_weight_lb / LB_PER_METRIC_TON, 2)}},
            "units": "miles",
            "directions_type": "maneuvers",
            "narrative": False,
        }
        if alternates:
            body["alternates"] = alternates
        params = {}
        if key := settings.PLANNER["VALHALLA_API_KEY"]:
            params["api_key"] = key
        try:
            response = session().post(
                f"{settings.PLANNER['VALHALLA_URL'].rstrip('/')}/route",
                json=body,
                params=params,
                timeout=timeout(),
            )
        except requests.RequestException as exc:
            raise UpstreamError("routing", "routing service is unreachable") from exc
        if response.status_code == 429:
            raise UpstreamRateLimited("routing", "routing service rate limit reached")
        if response.status_code == 400:
            payload = _json_or_empty(response)
            if payload.get("error_code") in _VALHALLA_NO_ROUTE:
                raise NoRouteFound("routing", "no truck route found between these places")
            raise UpstreamError("routing", payload.get("error", "routing request rejected"))
        if not response.ok:
            raise UpstreamError("routing", f"routing failed (HTTP {response.status_code})")
        data = response.json()
        trips = [data["trip"], *(alt["trip"] for alt in data.get("alternates", []))]
        return [self._parse_trip(trip) for trip in trips]

    def _parse_trip(self, trip: dict) -> RouteOption:
        coords: list[LatLon] = []
        spans: list[tuple[int, int, float]] = []
        road_miles: Counter[str] = Counter()
        for leg in trip["legs"]:
            shape = decode_polyline(leg["shape"], precision=6)
            # Consecutive legs share their joining vertex; keep it once.
            offset = len(coords) - 1 if coords else 0
            coords.extend(shape[1:] if coords else shape)
            for m in leg["maneuvers"]:
                begin, end = m["begin_shape_index"], m["end_shape_index"]
                if end > begin:
                    spans.append((offset + begin, offset + end, float(m["time"])))
                # Concurrent highways list several names; credit the primary one only.
                if names := m.get("street_names"):
                    road_miles[normalize_road(names[0])] += float(m.get("length", 0.0))
        line = RouteLine.from_timed_spans(coords, spans)
        return RouteOption(line=line, roads=main_roads(road_miles), provider=self.name)


class OsrmRouter:
    """Fallback only: car profile, so routes ignore truck restrictions."""

    name = "osrm"
    profile = "car"

    def accepts(self, points: Sequence[LatLon]) -> bool:
        return True

    def route(
        self,
        origin: LatLon,
        destination: LatLon,
        *,
        gross_weight_lb: float,
        via: LatLon | None = None,
        alternates: int = 0,
    ) -> list[RouteOption]:
        points = [origin, *([via] if via else []), destination]
        path = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in points)
        params = {
            "alternatives": str(alternates) if alternates else "false",
            "overview": "full",
            "geometries": "polyline6",
            "annotations": "duration",
            "steps": "true",  # for road names/refs; geometry comes from the overview
        }
        try:
            response = session().get(
                f"{settings.PLANNER['OSRM_URL'].rstrip('/')}/route/v1/driving/{path}",
                params=params,
                timeout=timeout(),
            )
        except requests.RequestException as exc:
            raise UpstreamError("routing", "fallback routing service is unreachable") from exc
        if response.status_code == 429:
            raise UpstreamRateLimited("routing", "routing service rate limit reached")
        payload = _json_or_empty(response)
        if payload.get("code") in {"NoRoute", "NoSegment"}:
            raise NoRouteFound("routing", "no route found between these places")
        if not response.ok or payload.get("code") != "Ok":
            raise UpstreamError("routing", f"fallback routing failed (HTTP {response.status_code})")
        return [self._parse_route(route) for route in payload["routes"]]

    def _parse_route(self, route: dict) -> RouteOption:
        coords = decode_polyline(route["geometry"], precision=6)
        durations = [
            d for leg in route["legs"] for d in leg.get("annotation", {}).get("duration", [])
        ]
        if len(durations) == len(coords) - 1:
            line = RouteLine.from_segment_durations(coords, durations)
        else:
            line = RouteLine.from_timed_spans(coords, [(0, len(coords) - 1, route["duration"])])
        roads: Counter[str] = Counter()
        for leg in route["legs"]:
            for step in leg.get("steps", []):
                name = (step.get("ref") or step.get("name") or "").split(";")[0]
                if name:
                    roads[normalize_road(name)] += step.get("distance", 0.0) / METERS_PER_MILE
        return RouteOption(line=line, roads=main_roads(roads), provider=self.name)


def _json_or_empty(response: requests.Response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


Router = ValhallaRouter | OsrmRouter


class RoutePlanner:
    """Finds up to ``want`` distinct route options from a single engine."""

    def __init__(self, primary: Router | None = None, fallback: Router | None = None):
        self.primary = primary or ValhallaRouter()
        self.fallback = fallback or OsrmRouter()

    def options(
        self, origin: LatLon, destination: LatLon, *, load_lb: float, want: int = 3
    ) -> RouteSet:
        gross = TRUCK_TARE_LB + load_lb
        key = "routes:v2:{:.4f},{:.4f}:{:.4f},{:.4f}:{}:{}".format(
            *origin, *destination, round(gross, -3), want
        )
        if (hit := cache.get(key)) is not None:
            return hit

        best: RouteSet | None = None
        reason: str | None = None
        for router in (self.primary, self.fallback):
            if not router.accepts([origin, destination]):
                reason = "distance"
                continue
            try:
                found = self._collect(router, origin, destination, gross, want)
            except NoRouteFound:
                raise
            except UpstreamError as exc:
                log.warning("%s routing failed: %s", router.name, exc)
                reason = "unavailable"
                continue
            if best is None or len(found) > len(best.options):
                best = RouteSet(found, router.name, router.profile, reason)
            if len(best.options) >= want:
                break
            reason = "alternatives"
        if best is None:
            raise UpstreamError("routing", "routing services are unavailable, please retry")
        cache.set(key, best, CACHE_TTL_S)
        return best

    def _collect(
        self, router: Router, origin: LatLon, destination: LatLon, gross: float, want: int
    ) -> list[RouteOption]:
        found = router.route(origin, destination, gross_weight_lb=gross, alternates=want - 1)
        fastest = min(found, key=lambda o: o.line.total_s)
        rest = [o for o in found if o is not fastest]
        distinct = pick_distinct([fastest.line], [o.line for o in rest], want)
        chosen = [fastest, *(rest[i] for i in distinct)]
        if len(chosen) < want:
            chosen += self._via_alternatives(router, origin, destination, gross, chosen, want)
        return sorted(chosen, key=lambda o: o.line.total_s)

    def _via_alternatives(
        self,
        router: Router,
        origin: LatLon,
        destination: LatLon,
        gross: float,
        chosen: Sequence[RouteOption],
        want: int,
    ) -> list[RouteOption]:
        def attempt(via: LatLon) -> RouteOption | None:
            try:
                return router.route(origin, destination, gross_weight_lb=gross, via=via)[0]
            except UpstreamError as exc:
                log.info("via candidate %s rejected: %s", via, exc)
                return None

        vias = [
            via
            for via in via_candidates(chosen[0].line, origin, destination)
            if router.accepts([origin, via, destination])
        ]
        extra: list[RouteOption] = []
        for start in range(0, len(vias), VIA_BATCH):
            results = _parallel(attempt, vias[start : start + VIA_BATCH])
            candidates = [r for r in results if r is not None]
            base = [o.line for o in (*chosen, *extra)]
            picked = pick_distinct(base, [c.line for c in candidates], want)
            extra += [candidates[i] for i in picked]
            if len(chosen) + len(extra) >= want:
                break
        return extra


def _parallel[T, R](fn: Callable[[T], R], items: Sequence[T]) -> list[R]:
    with ThreadPoolExecutor(max_workers=max(1, len(items))) as pool:
        return list(pool.map(fn, items))
