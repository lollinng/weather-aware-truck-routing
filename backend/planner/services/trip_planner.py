"""Orchestrates a plan: routes -> checkpoints & ETAs -> forecasts -> risk -> recommendation.

All I/O goes through the injected route planner and weather client; everything else is the
pure domain code in ``planner.domain``.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings

from ..domain.checkpoints import Checkpoint, sample_checkpoints
from ..domain.corridor import CorridorGrid, build_corridor
from ..domain.geo import METERS_PER_MILE, RouteLine
from ..domain.hos import ContinuousDriving, DrivingSchedule, DutyStatus, HoursOfService
from ..domain.risk import RiskAssessment, assess
from ..domain.scoring import Candidate, RiskProfile, build_profile, explain, rank
from ..domain.weather import HOUR, HourlySeries, WeatherSample, floor_hour
from ..providers.geocoding import Place
from ..providers.open_meteo import OpenMeteoClient
from ..providers.routing import RouteOption, RoutePlanner
from . import presenters as present

HEATMAP_HOURS = 48
TRACK_STEP_S = 15 * 60  # truck-position samples for the time slider
ROUTE_SIMPLIFY_M = 25.0
ROUTE_IDS = "ABC"
SAMPLING_INTERVALS_MI = (10, 25, 50)
HEATMAP_MAX_CELLS = 260
HEATMAP_MIN_CELLS = 100


@dataclass(frozen=True, slots=True)
class SamplingPlan:
    interval_mi: int
    checkpoints: list[list[Checkpoint]]
    heatmap_cells: int
    notice: str | None


def plan_sampling(
    lines: list[RouteLine],
    requested_mi: int,
    departure: datetime,
    schedule: DrivingSchedule,
    budget: int,
) -> SamplingPlan:
    """Fit checkpoints + heatmap into the per-plan forecast-location budget.

    Every checkpoint and heatmap point is one forecast location, and the free weather tier
    allows ~600 per minute. The heatmap shrinks first (down to ``HEATMAP_MIN_CELLS``); only
    if that is not enough does checkpoint spacing coarsen, and the user is told.
    """
    coarser = [mi for mi in SAMPLING_INTERVALS_MI if mi >= requested_mi] or [requested_mi]
    for interval_mi in coarser:
        sampled = [
            sample_checkpoints(line, interval_mi * METERS_PER_MILE, departure, schedule)
            for line in lines
        ]
        needed = sum(len(cps) for cps in sampled)
        if needed + HEATMAP_MIN_CELLS <= budget or interval_mi == coarser[-1]:
            break
    notice = None
    if interval_mi != requested_mi:
        notice = (
            f"Sampling every {requested_mi} mi would need more forecasts than the weather "
            f"provider allows per minute on this long trip, so checkpoints are every "
            f"{interval_mi} mi instead."
        )
    cells = max(HEATMAP_MIN_CELLS, min(HEATMAP_MAX_CELLS, budget - needed))
    return SamplingPlan(interval_mi, sampled, cells, notice)


@dataclass(frozen=True, slots=True)
class TripRequest:
    origin: Place
    destination: Place
    departure: datetime  # timezone-aware
    load_lb: int
    interval_mi: int
    hos: bool = True


@dataclass(slots=True)
class _AssessedRoute:
    route_id: str
    option: RouteOption
    checkpoints: list[Checkpoint]
    samples: list[WeatherSample | None]
    risks: list[RiskAssessment | None]
    trip_s: float


class TripPlanner:
    def __init__(
        self,
        routes: RoutePlanner | None = None,
        weather: OpenMeteoClient | None = None,
        location_budget: int | None = None,
    ):
        self.routes = routes or RoutePlanner()
        self.weather = weather or OpenMeteoClient()
        self.location_budget = location_budget or settings.PLANNER["WEATHER_MAX_LOCATIONS"]

    def plan(self, req: TripRequest) -> dict:
        route_set = self.routes.options(
            (req.origin.lat, req.origin.lon),
            (req.destination.lat, req.destination.lon),
            load_lb=req.load_lb,
            want=len(ROUTE_IDS),
        )
        options = route_set.options
        schedule: DrivingSchedule = HoursOfService() if req.hos else ContinuousDriving()
        sampling = plan_sampling(
            [o.line for o in options],
            req.interval_mi,
            req.departure,
            schedule,
            self.location_budget,
        )
        sampled = sampling.checkpoints
        grid = build_corridor([o.line for o in options], max_cells=sampling.heatmap_cells)
        frames = [floor_hour(req.departure) + k * HOUR for k in range(HEATMAP_HOURS + 2)]

        cp_points = [(cp.lat, cp.lon) for cps in sampled for cp in cps]
        last_eta = max(cp.eta for cps in sampled for cp in cps)
        with ThreadPoolExecutor(max_workers=2) as pool:
            cp_future = pool.submit(self.weather.forecasts, cp_points, req.departure, last_eta)
            grid_future = pool.submit(self.weather.forecasts, grid.points(), frames[0], frames[-1])
            cp_series, grid_series = cp_future.result(), grid_future.result()

        series_iter = iter(cp_series)
        assessed: list[_AssessedRoute] = []
        for route_id, option, cps in zip(ROUTE_IDS, options, sampled, strict=False):
            samples, risks = [], []
            for cp in cps:
                series = next(series_iter)
                sample = series.sample(cp.eta) if series else None
                samples.append(sample)
                risks.append(assess(sample, req.load_lb) if sample else None)
            assessed.append(
                _AssessedRoute(
                    route_id=route_id,
                    option=option,
                    checkpoints=cps,
                    samples=samples,
                    risks=risks,
                    trip_s=schedule.elapsed_for_drive(option.line.total_s),
                )
            )

        profiles = {
            r.route_id: build_profile(
                [cp.span_m for cp in r.checkpoints],
                [risk.level if risk else None for risk in r.risks],
            )
            for r in assessed
        }
        candidates = [Candidate(r.route_id, profiles[r.route_id], r.trip_s) for r in assessed]
        ranked = rank(candidates)
        names = {r.route_id: f"Route {r.route_id}" for r in assessed}
        reasons, warnings = explain(ranked, names)
        order = {c.route_id: i + 1 for i, c in enumerate(ranked)}

        return {
            "request": {
                "origin": {"label": req.origin.label, "lat": req.origin.lat, "lon": req.origin.lon},
                "destination": {
                    "label": req.destination.label,
                    "lat": req.destination.lat,
                    "lon": req.destination.lon,
                },
                "departure": present.iso(req.departure),
                "load_weight_lb": req.load_lb,
                "interval_miles": req.interval_mi,
                "hos": req.hos,
            },
            "interval_miles": sampling.interval_mi,  # effective spacing (may be coarser)
            "notices": [sampling.notice] if sampling.notice else [],
            "routes": [
                self._route_payload(r, profiles[r.route_id], order[r.route_id], req, schedule)
                for r in assessed
            ],
            "recommendation": {
                "route_id": ranked[0].route_id,
                "reasons": reasons,
                "warnings": warnings,
            },
            "routing": {
                "provider": route_set.provider,
                "profile": route_set.profile,
                "fallback_reason": route_set.fallback_reason,
            },
            "heatmap": self._heatmap_payload(grid, grid_series, frames, req.load_lb),
        }

    # -- payload builders ---------------------------------------------------------------------
    def _route_payload(
        self,
        r: _AssessedRoute,
        risk_profile: RiskProfile,
        rank_position: int,
        req: TripRequest,
        schedule: DrivingSchedule,
    ) -> dict:
        line = r.option.line
        indices = line.simplified_indices(ROUTE_SIMPLIFY_M)
        coords = line.coords()
        levels = [risk.level if risk else None for risk in r.risks]
        return {
            "id": r.route_id,
            "name": f"Route {r.route_id}",
            "roads": list(r.option.roads),
            "provider": r.option.provider,
            "distance_mi": present.miles(line.total_m),
            "drive_time_s": round(line.total_s),
            "trip_time_s": round(r.trip_s),
            "arrival": present.iso(req.departure + timedelta(seconds=r.trip_s)),
            "rank": rank_position,
            "recommended": rank_position == 1,
            "summary": present.profile(risk_profile),
            "geometry": present.lonlat([coords[i] for i in indices]),
            "risk_segments": present.risk_segments(line, indices, r.checkpoints, levels),
            "checkpoints": [
                present.checkpoint(cp, sample, risk)
                for cp, sample, risk in zip(r.checkpoints, r.samples, r.risks, strict=True)
            ],
            "stops": self._stops(line, req.departure, schedule),
            "track": self._track(r, schedule),
        }

    def _stops(self, line: RouteLine, departure: datetime, schedule: DrivingSchedule) -> list:
        out = []
        for stop in schedule.stops(line.total_s):
            point = line.at_drive_time(stop.drive_s)
            out.append(
                {
                    "kind": "break" if stop.kind is DutyStatus.BREAK else "rest",
                    "mile": present.miles(point.distance_m),
                    "lat": round(point.lat, 5),
                    "lon": round(point.lon, 5),
                    "start": present.iso(departure + timedelta(seconds=stop.elapsed_s)),
                    "duration_s": round(stop.duration_s),
                }
            )
        return out

    def _track(self, r: _AssessedRoute, schedule: DrivingSchedule) -> dict:
        """Truck position every 15 min of wall-clock time across the slider's 0–48 h."""
        line = r.option.line
        coords, mile_marks, states = [], [], []
        for k in range(HEATMAP_HOURS * 3600 // TRACK_STEP_S + 1):
            drive_s, status = schedule.status_at(k * TRACK_STEP_S, line.total_s)
            point = line.at_drive_time(drive_s)
            coords.append((point.lat, point.lon))
            mile_marks.append(present.miles(point.distance_m))
            states.append(status.value)
        return {
            "step_s": TRACK_STEP_S,
            "coordinates": present.lonlat(coords),
            "miles": mile_marks,
            "states": "".join(states),
        }

    def _heatmap_payload(
        self,
        grid: CorridorGrid,
        series: list[HourlySeries | None],
        frames: list[datetime],
        load_lb: int,
    ) -> dict:
        metrics: dict[str, list] = {"risk": [], "wind": [], "rain": [], "snow": []}
        for moment in frames:
            for s in series:
                sample = s.sample(moment) if s else None
                if sample is None:
                    for values in metrics.values():
                        values.append(None)
                    continue
                metrics["risk"].append(int(assess(sample, load_lb).level))
                metrics["wind"].append(round(sample.wind_mph, 1))
                metrics["rain"].append(round(sample.rain_in_hr, 3))
                metrics["snow"].append(round(sample.snow_in_hr, 2))
        return {
            "lattice": {
                "south": grid.south,
                "west": grid.west,
                "step": grid.step_deg,
                "rows": grid.rows,
                "cols": grid.cols,
            },
            "cells": [list(cell) for cell in grid.cells],
            "frame0": present.iso(frames[0]),
            "frame_count": len(frames),
            "metrics": metrics,
        }
