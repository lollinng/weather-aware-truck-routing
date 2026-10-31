"""Hourly forecasts from Open-Meteo, batched and cached per location.

* Many locations go in one request (comma-separated coordinates), ``BATCH_SIZE`` at a time.
  Open-Meteo rejects more than a handful of *concurrent* requests per client, so a
  process-wide semaphore caps requests in flight and that specific 429 is retried briefly.
* Each location's series is cached for ``CACHE_TTL_S``. A cached series is reused whenever it
  covers the requested time window, so re-planning a trip (or a nearby one) is nearly free.
* Coordinates are rounded to 0.01° (~1 km), well below forecast model resolution, so tiny
  float differences don't defeat the cache.

The free endpoint is for non-commercial use; set ``OPEN_METEO_API_KEY`` to use the
commercial endpoint with higher limits.
"""

from __future__ import annotations

import contextlib
import logging
import random
import threading
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import requests
from django.conf import settings
from django.core.cache import cache

from ..domain.geo import LatLon
from ..domain.weather import HOUR, HourlySeries, ceil_hour, floor_hour
from .http import UpstreamError, UpstreamRateLimited, session, timeout

log = logging.getLogger(__name__)

HOURLY_VARIABLES = (
    "wind_speed_10m",
    "wind_gusts_10m",
    "rain",
    "showers",
    "snowfall",
    "temperature_2m",
    "weather_code",
)
BATCH_SIZE = 100
MAX_IN_FLIGHT = 3  # shared by all threads in the process
CONCURRENCY_RETRIES = 4
CACHE_TTL_S = 30 * 60
COORD_DECIMALS = 2
# Fetch a little beyond what is needed so slightly later re-plans still hit the cache.
WINDOW_PADDING = timedelta(hours=6)


_in_flight = threading.BoundedSemaphore(MAX_IN_FLIGHT)


def snap(point: LatLon) -> LatLon:
    return round(point[0], COORD_DECIMALS), round(point[1], COORD_DECIMALS)


def _cache_key(point: LatLon) -> str:
    return f"wx:v1:{point[0]:.{COORD_DECIMALS}f}:{point[1]:.{COORD_DECIMALS}f}"


def _hour_param(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M")


def parse_location(payload: dict) -> HourlySeries:
    hourly = payload["hourly"]
    times = hourly["time"]
    if not times:
        raise UpstreamError("weather", "empty forecast")
    start = datetime.fromisoformat(times[0]).replace(tzinfo=UTC)
    rain = [
        None if r is None and s is None else (r or 0.0) + (s or 0.0)
        for r, s in zip(hourly["rain"], hourly["showers"], strict=True)
    ]
    return HourlySeries(
        start,
        wind=hourly["wind_speed_10m"],
        gust=hourly["wind_gusts_10m"],
        rain=rain,
        snow=hourly["snowfall"],
        temp=hourly["temperature_2m"],
        code=hourly["weather_code"],
    )


class OpenMeteoClient:
    def forecasts(
        self, points: Sequence[LatLon], first: datetime, last: datetime
    ) -> list[HourlySeries | None]:
        """Series covering [first, last] for each point (``None`` if a point has no data).

        The result is aligned with ``points``; duplicates are fetched once.
        """
        if not points:
            return []
        start = floor_hour(first) - HOUR
        end = ceil_hour(last) + HOUR
        snapped = [snap(p) for p in points]
        unique = list(dict.fromkeys(snapped))

        found: dict[LatLon, HourlySeries] = {}
        cached = cache.get_many([_cache_key(p) for p in unique])
        for p in unique:
            series = cached.get(_cache_key(p))
            if series is not None and series.covers(start, end):
                found[p] = series
        missing = [p for p in unique if p not in found]
        if missing:
            fetched = self._fetch(missing, start, end + WINDOW_PADDING)
            found.update(fetched)
            cache.set_many({_cache_key(p): s for p, s in fetched.items()}, CACHE_TTL_S)
            log.info(
                "weather: %d locations (%d cached, %d fetched)",
                len(unique),
                len(unique) - len(missing),
                len(fetched),
            )
        return [found.get(p) for p in snapped]

    def _fetch(
        self, points: Sequence[LatLon], start: datetime, end: datetime
    ) -> dict[LatLon, HourlySeries]:
        batches = [points[i : i + BATCH_SIZE] for i in range(0, len(points), BATCH_SIZE)]
        workers = min(MAX_IN_FLIGHT, len(batches))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(lambda b: self._fetch_batch(b, start, end), batches))
        merged: dict[LatLon, HourlySeries] = {}
        for result in results:
            merged.update(result)
        return merged

    def _fetch_batch(
        self, points: Sequence[LatLon], start: datetime, end: datetime
    ) -> dict[LatLon, HourlySeries]:
        params = {
            "latitude": ",".join(f"{lat:.{COORD_DECIMALS}f}" for lat, _ in points),
            "longitude": ",".join(f"{lon:.{COORD_DECIMALS}f}" for _, lon in points),
            "hourly": ",".join(HOURLY_VARIABLES),
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "temperature_unit": "fahrenheit",
            "timezone": "GMT",
            "start_hour": _hour_param(start),
            "end_hour": _hour_param(end),
        }
        base = settings.PLANNER["OPEN_METEO_URL"].rstrip("/")
        if key := settings.PLANNER["OPEN_METEO_API_KEY"]:
            params["apikey"] = key
            base = base.replace("://api.", "://customer-api.")
        for attempt in range(CONCURRENCY_RETRIES + 1):
            try:
                with _in_flight:
                    response = session().get(
                        f"{base}/v1/forecast", params=params, timeout=timeout()
                    )
            except requests.RequestException as exc:
                raise UpstreamError("weather", "forecast service is unreachable") from exc
            reason = _reason(response)
            too_many_in_flight = response.status_code == 429 and "concurrent" in reason.lower()
            if too_many_in_flight and attempt < CONCURRENCY_RETRIES:
                time.sleep(0.4 * (attempt + 1) + random.random() * 0.3)
                continue
            break
        if response.status_code == 429:
            log.warning("open-meteo rate limit: %s", reason)
            raise UpstreamRateLimited(
                "weather", "forecast provider rate limit reached; try again in a minute"
            )
        if not response.ok:
            raise UpstreamError(
                "weather", reason or f"forecast failed (HTTP {response.status_code})"
            )
        payload = response.json()
        locations = payload if isinstance(payload, list) else [payload]
        if len(locations) != len(points):
            raise UpstreamError("weather", "forecast response did not match the request")
        return {point: parse_location(loc) for point, loc in zip(points, locations, strict=True)}


def _reason(response: requests.Response) -> str:
    if response.ok:
        return ""
    with contextlib.suppress(ValueError, AttributeError):
        return str(response.json().get("reason", ""))
    return ""
