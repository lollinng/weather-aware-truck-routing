"""Weather risk classification — a direct encoding of the assessment's risk and load rules.

Band boundaries
---------------
The spec's tables use inclusive integer ranges (wind "25–34") and shared endpoints for
precipitation ("0.10–0.25", "0.25–0.50"). Forecast values are continuous, so each band is
interpreted as *lower bound inclusive, upper bound exclusive*:

    wind  Moderate [25, 35)   High [35, 45)   Severe [45, 55)   No Travel >= 55
    rain  Moderate [0.10, 0.25)  High [0.25, 0.50)  Severe [0.50, 1.00]  No Travel > 1.00
    snow  Moderate [0.5, 1.0)    High [1.0, 2.0)    Severe [2.0, 3.0]    No Travel > 3.0

The only exception is the top of the precipitation scale, where the spec says ">1.00" / ">3.0"
for No Travel, so exactly 1.00 in/hr (3.0 in/hr) stays Severe.

Load rules escalate *wind* risk for heavy loads:

    >= 55 mph                    -> No Travel (any load)
    45–54 mph and load > 30,000 lb -> No Travel
    35–44 mph and load > 40,000 lb -> Severe

A checkpoint's overall level is the worst of its wind (load-adjusted), rain and snow levels.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from .weather import WeatherSample


class RiskLevel(IntEnum):
    LOW = 0
    MODERATE = 1
    HIGH = 2
    SEVERE = 3
    NO_TRAVEL = 4

    @property
    def label(self) -> str:
        return _LABELS[self]

    @property
    def key(self) -> str:
        return self.name.lower()


_LABELS = {
    RiskLevel.LOW: "Low",
    RiskLevel.MODERATE: "Moderate",
    RiskLevel.HIGH: "High",
    RiskLevel.SEVERE: "Severe",
    RiskLevel.NO_TRAVEL: "No Travel",
}

# (threshold, level) pairs from worst to best; first match wins.
WIND_MPH = (
    (55.0, RiskLevel.NO_TRAVEL),
    (45.0, RiskLevel.SEVERE),
    (35.0, RiskLevel.HIGH),
    (25.0, RiskLevel.MODERATE),
)
RAIN_IN_HR = ((0.50, RiskLevel.SEVERE), (0.25, RiskLevel.HIGH), (0.10, RiskLevel.MODERATE))
RAIN_NO_TRAVEL_ABOVE = 1.00
SNOW_IN_HR = ((2.0, RiskLevel.SEVERE), (1.0, RiskLevel.HIGH), (0.5, RiskLevel.MODERATE))
SNOW_NO_TRAVEL_ABOVE = 3.0

HEAVY_LOAD_NO_TRAVEL_LB = 30_000  # 45–54 mph + load above this -> No Travel
HEAVY_LOAD_SEVERE_LB = 40_000  # 35–44 mph + load above this -> Severe


def _first_band(value: float, bands: tuple[tuple[float, RiskLevel], ...]) -> RiskLevel:
    for threshold, level in bands:
        if value >= threshold:
            return level
    return RiskLevel.LOW


def wind_base_level(wind_mph: float) -> RiskLevel:
    return _first_band(wind_mph, WIND_MPH)


def wind_level(wind_mph: float, load_lb: float) -> tuple[RiskLevel, bool]:
    """Wind level after load rules, and whether the load rule raised it."""
    base = wind_base_level(wind_mph)
    if base == RiskLevel.SEVERE and load_lb > HEAVY_LOAD_NO_TRAVEL_LB:
        return RiskLevel.NO_TRAVEL, True
    if base == RiskLevel.HIGH and load_lb > HEAVY_LOAD_SEVERE_LB:
        return RiskLevel.SEVERE, True
    return base, False


def rain_level(rain_in_hr: float) -> RiskLevel:
    if rain_in_hr > RAIN_NO_TRAVEL_ABOVE:
        return RiskLevel.NO_TRAVEL
    return _first_band(rain_in_hr, RAIN_IN_HR)


def snow_level(snow_in_hr: float) -> RiskLevel:
    if snow_in_hr > SNOW_NO_TRAVEL_ABOVE:
        return RiskLevel.NO_TRAVEL
    return _first_band(snow_in_hr, SNOW_IN_HR)


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    level: RiskLevel
    wind: RiskLevel
    rain: RiskLevel
    snow: RiskLevel
    load_adjusted: bool

    @property
    def drivers(self) -> list[str]:
        """Factors responsible for the overall level (empty when everything is Low)."""
        if self.level == RiskLevel.LOW:
            return []
        return [
            name
            for name, level in (("wind", self.wind), ("rain", self.rain), ("snow", self.snow))
            if level == self.level
        ]


def assess(sample: WeatherSample, load_lb: float) -> RiskAssessment:
    wind, adjusted = wind_level(sample.wind_mph, load_lb)
    rain = rain_level(sample.rain_in_hr)
    snow = snow_level(sample.snow_in_hr)
    return RiskAssessment(
        level=max(wind, rain, snow), wind=wind, rain=rain, snow=snow, load_adjusted=adjusted
    )
