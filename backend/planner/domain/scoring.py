"""Route risk profiles and the recommendation ordering.

The spec ranks routes by, in order:

1. fewest Severe miles, 2. fewest High miles, 3. lowest average risk, 4. shortest travel time.

"No Travel" is worse than Severe but the list doesn't mention it, and reading it literally
would let a route with No-Travel conditions win just because it has fewer *Severe* miles. So
No-Travel miles are compared first, as a gate: any route that can be driven beats one that
can't, and the spec's four criteria then apply unchanged.

Comparisons are lexicographic. Miles are rounded to 0.1 mi and average risk to 0.01 so that
float noise can't decide a ranking that should fall through to travel time.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .geo import METERS_PER_MILE
from .risk import RiskLevel


@dataclass(frozen=True, slots=True)
class RiskProfile:
    miles: dict[RiskLevel, float]  # every level present, 0.0 when absent
    unknown_miles: float  # stretches whose forecast was unavailable
    average_risk: float  # distance-weighted mean level (0 = Low … 4 = No Travel)
    max_level: RiskLevel

    @property
    def no_travel_miles(self) -> float:
        return self.miles[RiskLevel.NO_TRAVEL]

    @property
    def severe_miles(self) -> float:
        return self.miles[RiskLevel.SEVERE]

    @property
    def high_miles(self) -> float:
        return self.miles[RiskLevel.HIGH]


def build_profile(spans_m: Sequence[float], levels: Sequence[RiskLevel | None]) -> RiskProfile:
    """Aggregate per-checkpoint levels, weighting each by the road stretch it represents."""
    miles = dict.fromkeys(RiskLevel, 0.0)
    unknown = 0.0
    for span_m, level in zip(spans_m, levels, strict=True):
        span_mi = span_m / METERS_PER_MILE
        if level is None:
            unknown += span_mi
        else:
            miles[level] += span_mi
    known = sum(miles.values())
    average = sum(level.value * mi for level, mi in miles.items()) / known if known else 0.0
    present = [level for level in levels if level is not None]
    return RiskProfile(
        miles=miles,
        unknown_miles=unknown,
        average_risk=average,
        max_level=max(present) if present else RiskLevel.LOW,
    )


@dataclass(frozen=True, slots=True)
class Candidate:
    route_id: str
    profile: RiskProfile
    trip_s: float  # door-to-door wall-clock time, including HOS stops


def ranking_key(c: Candidate) -> tuple[float, float, float, float, float]:
    p = c.profile
    return (
        round(p.no_travel_miles, 1),
        round(p.severe_miles, 1),
        round(p.high_miles, 1),
        round(p.average_risk, 2),
        round(c.trip_s),
    )


def rank(candidates: Sequence[Candidate]) -> list[Candidate]:
    """Best first. ``sorted`` is stable, so exact ties keep the input (fastest-first) order."""
    return sorted(candidates, key=ranking_key)


# -- explanation -------------------------------------------------------------------------------


def _mi(value: float) -> str:
    if value < 0.05:
        return "0 mi"
    return f"{value:,.0f} mi" if value >= 9.5 else f"{value:,.1f} mi"


def format_duration(seconds: float) -> str:
    minutes = round(seconds / 60)
    hours, minutes = divmod(minutes, 60)
    if hours and minutes:
        return f"{hours} h {minutes} min"
    return f"{hours} h" if hours else f"{minutes} min"


def _decisive_reason(best: Candidate, other: Candidate, name: dict[str, str]) -> str:
    """Why ``best`` outranks ``other``: the first criterion that separates them."""
    b, o = best.profile, other.profile
    them = name[other.route_id]
    criteria = (
        ("No-Travel", b.no_travel_miles, o.no_travel_miles),
        ("Severe-risk", b.severe_miles, o.severe_miles),
        ("High-risk", b.high_miles, o.high_miles),
    )
    for label, mine, theirs in criteria:
        if round(mine, 1) != round(theirs, 1):
            return (
                f"{_mi(theirs - mine)} fewer {label} miles than {them} "
                f"({_mi(mine)} vs {_mi(theirs)})."
            )
    if round(b.average_risk, 2) != round(o.average_risk, 2):
        return f"Lower average risk than {them} ({b.average_risk:.2f} vs {o.average_risk:.2f})."
    delta = other.trip_s - best.trip_s
    if round(delta) > 0:
        return f"Same weather risk as {them}, but {format_duration(delta)} faster."
    return f"Equivalent to {them} on risk and travel time."


def explain(ranked: Sequence[Candidate], name: dict[str, str]) -> tuple[list[str], list[str]]:
    """Human-readable (reasons, warnings) for the top-ranked candidate."""
    best = ranked[0]
    reasons = [_decisive_reason(best, other, name) for other in ranked[1:]]
    fastest = min(ranked, key=lambda c: c.trip_s)
    if fastest.route_id != best.route_id:
        extra = best.trip_s - fastest.trip_s
        reasons.append(
            f"Accepts {format_duration(extra)} more travel time than {name[fastest.route_id]} "
            "(the fastest) in exchange for lower weather risk."
        )
    elif len(ranked) > 1:
        reasons.append("It is also the fastest option.")

    warnings = []
    p = best.profile
    if p.no_travel_miles > 0:
        warnings.append(
            f"Every option crosses No-Travel conditions; the recommended route still has "
            f"{_mi(p.no_travel_miles)} of them. Consider delaying departure."
        )
    elif p.severe_miles > 0:
        warnings.append(f"The recommended route still has {_mi(p.severe_miles)} of Severe risk.")
    if p.unknown_miles > 0:
        warnings.append(f"No forecast was available for {_mi(p.unknown_miles)} of this route.")
    return reasons, warnings
