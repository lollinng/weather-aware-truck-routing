from datetime import timedelta

import pytest

from planner.domain.weather import HourlySeries, ceil_hour, floor_hour

from .conftest import T0


def series(**overrides):
    n = 4
    data = {
        "wind": [10.0, 20.0, 30.0, 40.0],
        "gust": [15.0, 25.0, 35.0, 45.0],
        "rain": [0.0, 0.1, 0.3, 0.0],
        "snow": [0.0] * n,
        "temp": [50.0, 52.0, 54.0, 56.0],
        "code": [0, 61, 63, 0],
    }
    data.update(overrides)
    return HourlySeries(T0, **data)


def test_wind_is_interpolated_between_hours():
    s = series().sample(T0 + timedelta(minutes=90))
    assert s.wind_mph == pytest.approx(25.0)
    assert s.gust_mph == pytest.approx(30.0)
    assert s.temp_f == pytest.approx(53.0)


def test_precipitation_uses_the_bucket_containing_the_instant():
    # Values are totals for the preceding hour: 01:00→02:00 is stamped 02:00 (0.3 in).
    s = series().sample(T0 + timedelta(minutes=90))
    assert s.rain_in_hr == pytest.approx(0.3)
    assert s.weather_code == 63


def test_exact_hour_uses_bucket_ending_then():
    s = series().sample(T0 + timedelta(hours=1))
    assert s.rain_in_hr == pytest.approx(0.1)
    assert s.wind_mph == pytest.approx(20.0)


def test_outside_series_returns_none():
    assert series().sample(T0 - timedelta(minutes=1)) is None
    assert series().sample(T0 + timedelta(hours=3, minutes=1)) is None


def test_missing_values_return_none():
    assert series(rain=[None, None, None, None]).sample(T0 + timedelta(minutes=30)) is None


def test_covers():
    s = series()
    assert s.covers(T0, T0 + timedelta(hours=3))
    assert not s.covers(T0, T0 + timedelta(hours=4))


def test_hour_rounding():
    moment = T0 + timedelta(minutes=17)
    assert floor_hour(moment) == T0
    assert ceil_hour(moment) == T0 + timedelta(hours=1)
    assert ceil_hour(T0) == T0
