import pytest

from planner.domain.geo import METERS_PER_MILE
from planner.domain.risk import RiskLevel
from planner.domain.scoring import Candidate, RiskProfile, build_profile, explain, rank

L, M, H, S, N = (
    RiskLevel.LOW,
    RiskLevel.MODERATE,
    RiskLevel.HIGH,
    RiskLevel.SEVERE,
    RiskLevel.NO_TRAVEL,
)
HOUR = 3600


def profile(no_travel=0.0, severe=0.0, high=0.0, average=0.0, total=500.0) -> RiskProfile:
    miles = dict.fromkeys(RiskLevel, 0.0)
    miles[N], miles[S], miles[H] = no_travel, severe, high
    miles[L] = total - no_travel - severe - high
    return RiskProfile(miles=miles, unknown_miles=0.0, average_risk=average, max_level=L)


def ids(candidates):
    return [c.route_id for c in rank(candidates)]


def test_build_profile_weights_levels_by_distance():
    spans = [m * METERS_PER_MILE for m in (5, 10, 10, 5)]
    p = build_profile(spans, [L, H, H, S])
    assert p.miles[H] == pytest.approx(20)
    assert p.miles[S] == pytest.approx(5)
    assert p.average_risk == pytest.approx((0 * 5 + 2 * 20 + 3 * 5) / 30)
    assert p.max_level == S


def test_unknown_stretches_are_excluded_from_average():
    p = build_profile([10 * METERS_PER_MILE, 10 * METERS_PER_MILE], [H, None])
    assert p.unknown_miles == pytest.approx(10)
    assert p.average_risk == pytest.approx(2)


def test_fewest_severe_miles_wins_over_travel_time():
    fast = Candidate("A", profile(severe=20), 10 * HOUR)
    safe = Candidate("B", profile(high=200, average=1.5), 14 * HOUR)
    assert ids([fast, safe]) == ["B", "A"]


def test_high_miles_break_severe_ties():
    a = Candidate("A", profile(severe=10, high=50), 10 * HOUR)
    b = Candidate("B", profile(severe=10, high=5), 12 * HOUR)
    assert ids([a, b]) == ["B", "A"]


def test_average_risk_breaks_high_ties():
    a = Candidate("A", profile(average=0.8), 10 * HOUR)
    b = Candidate("B", profile(average=0.3), 12 * HOUR)
    assert ids([a, b]) == ["B", "A"]


def test_travel_time_is_last_resort():
    a = Candidate("A", profile(average=0.3), 12 * HOUR)
    b = Candidate("B", profile(average=0.3), 10 * HOUR)
    assert ids([a, b]) == ["B", "A"]


def test_no_travel_miles_are_a_gate_before_severe():
    blocked = Candidate("A", profile(no_travel=5), 10 * HOUR)
    severe = Candidate("B", profile(severe=60), 11 * HOUR)
    assert ids([blocked, severe]) == ["B", "A"]


def test_float_noise_does_not_override_travel_time():
    a = Candidate("A", profile(high=10.0004, average=0.2001), 12 * HOUR)
    b = Candidate("B", profile(high=10.0, average=0.2), 10 * HOUR)
    assert ids([a, b]) == ["B", "A"]


def test_explanations_name_the_decisive_criterion():
    names = {"A": "Route A", "B": "Route B", "C": "Route C"}
    ranked = rank(
        [
            Candidate("A", profile(severe=30), 10 * HOUR),
            Candidate("B", profile(high=12), 11 * HOUR),
            Candidate("C", profile(high=12), 11.5 * HOUR),
        ]
    )
    reasons, warnings = explain(ranked, names)
    assert ranked[0].route_id == "B"
    assert reasons[0] == "Same weather risk as Route C, but 30 min faster."
    assert reasons[1].startswith("30 mi fewer Severe-risk miles than Route A")
    assert "1 h more travel time than Route A" in reasons[2]
    assert warnings == []


def test_warns_when_every_route_is_blocked():
    names = {"A": "Route A", "B": "Route B"}
    ranked = rank(
        [
            Candidate("A", profile(no_travel=15), 10 * HOUR),
            Candidate("B", profile(no_travel=40), 9 * HOUR),
        ]
    )
    _, warnings = explain(ranked, names)
    assert "No-Travel" in warnings[0]
