import pytest

from planner.domain.risk import (
    RiskLevel,
    assess,
    rain_level,
    snow_level,
    wind_base_level,
    wind_level,
)
from planner.domain.weather import WeatherSample

L, M, H, S, N = (
    RiskLevel.LOW,
    RiskLevel.MODERATE,
    RiskLevel.HIGH,
    RiskLevel.SEVERE,
    RiskLevel.NO_TRAVEL,
)


@pytest.mark.parametrize(
    ("mph", "expected"),
    [
        (0, L),
        (24.9, L),
        (25, M),
        (34.9, M),
        (35, H),
        (44.9, H),
        (45, S),
        (54.9, S),
        (55, N),
        (80, N),
    ],
)
def test_wind_bands(mph, expected):
    assert wind_base_level(mph) == expected


@pytest.mark.parametrize(
    ("inches", "expected"),
    [
        (0, L),
        (0.099, L),
        (0.10, M),
        (0.249, M),
        (0.25, H),
        (0.499, H),
        (0.50, S),
        (1.00, S),  # spec: No Travel is strictly "> 1.00"
        (1.001, N),
    ],
)
def test_rain_bands(inches, expected):
    assert rain_level(inches) == expected


@pytest.mark.parametrize(
    ("inches", "expected"),
    [(0, L), (0.49, L), (0.5, M), (0.99, M), (1.0, H), (1.99, H), (2.0, S), (3.0, S), (3.01, N)],
)
def test_snow_bands(inches, expected):
    assert snow_level(inches) == expected


@pytest.mark.parametrize(
    ("mph", "load", "expected", "adjusted"),
    [
        # >= 55 mph is No Travel for any load.
        (55, 0, N, False),
        (60, 50_000, N, False),
        # 45–54 mph + > 30,000 lb -> No Travel.
        (45, 30_000, S, False),
        (45, 30_001, N, True),
        (54.9, 45_000, N, True),
        # 35–44 mph + > 40,000 lb -> Severe.
        (35, 40_000, H, False),
        (35, 40_001, S, True),
        (44.9, 79_000, S, True),
        # Below 35 mph the load doesn't matter.
        (34.9, 79_000, M, False),
    ],
)
def test_load_rules(mph, load, expected, adjusted):
    assert wind_level(mph, load) == (expected, adjusted)


def sample(wind=5.0, rain=0.0, snow=0.0):
    return WeatherSample(
        wind_mph=wind, gust_mph=None, rain_in_hr=rain, snow_in_hr=snow, temp_f=None, weather_code=0
    )


def test_overall_level_is_worst_factor():
    result = assess(sample(wind=30, rain=0.3, snow=0.0), load_lb=10_000)
    assert (result.level, result.wind, result.rain, result.snow) == (H, M, H, L)
    assert result.drivers == ["rain"]


def test_drivers_lists_every_factor_at_the_top_level():
    result = assess(sample(wind=36, rain=0.3), load_lb=10_000)
    assert result.level == H
    assert result.drivers == ["wind", "rain"]


def test_heavy_load_escalation_is_reported():
    result = assess(sample(wind=40), load_lb=42_000)
    assert result.level == S
    assert result.load_adjusted


def test_calm_weather_has_no_drivers():
    assert assess(sample(), load_lb=42_000).drivers == []
