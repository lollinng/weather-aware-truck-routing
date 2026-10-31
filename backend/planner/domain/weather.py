"""Hourly forecast series and how a forecast is read at an arbitrary instant.

Open-Meteo reports two kinds of hourly values:

* instantaneous (wind speed, gusts, temperature) valid *at* the timestamp, and
* accumulations (rain, showers, snowfall) summed over the *preceding* hour.

So at an ETA of 13:40 the truck experiences the 13:00→14:00 precipitation bucket, i.e. the
value stamped 14:00, while wind is interpolated between the 13:00 and 14:00 values. Because the
bucket is an hourly total, it is directly a rate in in/hr, which is what the risk table uses.
"""

from __future__ import annotations

import math
from array import array
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

HOUR = timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class WeatherSample:
    wind_mph: float
    gust_mph: float | None
    rain_in_hr: float  # liquid precipitation: rain + convective showers
    snow_in_hr: float
    temp_f: float | None
    weather_code: int | None


def _finite(value: float) -> float | None:
    return None if math.isnan(value) else value


class HourlySeries:
    """Hourly forecast for one location; index ``k`` is valid at ``start + k hours`` (UTC)."""

    __slots__ = ("code", "gust", "rain", "snow", "start", "temp", "wind")

    def __init__(
        self,
        start: datetime,
        *,
        wind: Sequence[float | None],
        gust: Sequence[float | None],
        rain: Sequence[float | None],
        snow: Sequence[float | None],
        temp: Sequence[float | None],
        code: Sequence[float | None],
    ):
        if start.tzinfo is None:
            raise ValueError("start must be timezone-aware")
        n = len(wind)
        if not all(len(s) == n for s in (gust, rain, snow, temp, code)):
            raise ValueError("all hourly arrays must have the same length")
        self.start = start.astimezone(UTC)
        nan = float("nan")

        def pack(values: Sequence[float | None]) -> array:
            return array("f", (nan if v is None else v for v in values))

        self.wind, self.gust, self.rain = pack(wind), pack(gust), pack(rain)
        self.snow, self.temp, self.code = pack(snow), pack(temp), pack(code)

    def __len__(self) -> int:
        return len(self.wind)

    @property
    def end(self) -> datetime:
        return self.start + (len(self) - 1) * HOUR

    def covers(self, first: datetime, last: datetime) -> bool:
        """True if every instant in [first, last] can be sampled."""
        return self.start <= first and last <= self.end

    def sample(self, when: datetime) -> WeatherSample | None:
        """Forecast experienced at ``when``; ``None`` if outside the series or data missing."""
        offset_h = (when - self.start).total_seconds() / 3600.0
        last = len(self) - 1
        if offset_h < 0 or offset_h > last:
            return None
        i0 = math.floor(offset_h)
        i1 = min(i0 + 1, last)
        frac = offset_h - i0
        bucket = min(math.ceil(offset_h), last)

        def lerp(values: array) -> float:
            a, b = values[i0], values[i1]
            return a + (b - a) * frac

        wind = lerp(self.wind)
        rain = self.rain[bucket]
        snow = self.snow[bucket]
        if math.isnan(wind) or math.isnan(rain) or math.isnan(snow):
            return None
        code = self.code[bucket]
        return WeatherSample(
            wind_mph=wind,
            gust_mph=_finite(lerp(self.gust)),
            rain_in_hr=max(0.0, rain),
            snow_in_hr=max(0.0, snow),
            temp_f=_finite(lerp(self.temp)),
            weather_code=None if math.isnan(code) else int(code),
        )


def floor_hour(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def ceil_hour(moment: datetime) -> datetime:
    floored = floor_hour(moment)
    return floored if floored == moment.astimezone(UTC) else floored + HOUR
