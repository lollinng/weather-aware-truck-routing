"""Domain objects -> JSON-ready dicts. Rounding for the wire happens here and only here."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from ..domain.checkpoints import Checkpoint
from ..domain.geo import METERS_PER_MILE, LatLon, RouteLine
from ..domain.risk import RiskAssessment, RiskLevel
from ..domain.scoring import RiskProfile
from ..domain.weather import WeatherSample


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def miles(meters: float, digits: int = 1) -> float:
    return round(meters / METERS_PER_MILE, digits)


def lonlat(coords: Sequence[LatLon]) -> list[list[float]]:
    return [[round(lon, 5), round(lat, 5)] for lat, lon in coords]


def weather(sample: WeatherSample | None) -> dict | None:
    if sample is None:
        return None
    return {
        "wind_mph": round(sample.wind_mph, 1),
        "gust_mph": None if sample.gust_mph is None else round(sample.gust_mph, 1),
        "rain_in_hr": round(sample.rain_in_hr, 3),
        "snow_in_hr": round(sample.snow_in_hr, 2),
        "temp_f": None if sample.temp_f is None else round(sample.temp_f),
        "weather_code": sample.weather_code,
    }


def risk(assessment: RiskAssessment | None) -> dict | None:
    if assessment is None:
        return None
    return {
        "level": assessment.level.key,
        "wind": assessment.wind.key,
        "rain": assessment.rain.key,
        "snow": assessment.snow.key,
        "load_adjusted": assessment.load_adjusted,
        "drivers": assessment.drivers,
    }


def checkpoint(
    cp: Checkpoint, sample: WeatherSample | None, assessment: RiskAssessment | None
) -> dict:
    return {
        "index": cp.index,
        "mile": miles(cp.distance_m),
        "lat": round(cp.lat, 5),
        "lon": round(cp.lon, 5),
        "eta": iso(cp.eta),
        "hours_from_departure": round(cp.elapsed_s / 3600, 2),
        "span_mi": miles(cp.span_m, 2),
        "weather": weather(sample),
        "risk": risk(assessment),
    }


def profile(p: RiskProfile) -> dict:
    return {
        "miles": {level.key: round(mi, 1) for level, mi in p.miles.items()},
        "unknown_miles": round(p.unknown_miles, 1),
        "average_risk": round(p.average_risk, 3),
        "max_level": p.max_level.key,
    }


def risk_segments(
    line: RouteLine,
    indices: Sequence[int],
    checkpoints: Sequence[Checkpoint],
    levels: Sequence[RiskLevel | None],
) -> list[dict]:
    """Consecutive checkpoints with the same level merged into colourable line segments."""
    segments: list[dict] = []
    for cp, level in zip(checkpoints, levels, strict=True):
        key = level.key if level is not None else "unknown"
        if segments and segments[-1]["level"] == key:
            segments[-1]["_end"] = cp.span_end_m
        else:
            segments.append({"level": key, "_start": cp.span_start_m, "_end": cp.span_end_m})
    out = []
    for seg in segments:
        out.append(
            {
                "level": seg["level"],
                "start_mi": miles(seg["_start"]),
                "end_mi": miles(seg["_end"]),
                "coordinates": lonlat(line.slice_coords(seg["_start"], seg["_end"], indices)),
            }
        )
    return out
