"""Driving schedules: how wall-clock time relates to time spent behind the wheel.

Weather must be sampled at the time the truck *actually* reaches a checkpoint. On a long
haul that is not ``departure + drive_time``: a property-carrying driver in the US must follow
FMCSA hours-of-service (HOS) rules. We model the parts that move the clock:

* 30-minute break after 8 cumulative hours of driving,
* at most 11 hours of driving per shift, then 10 consecutive hours off duty.

Pickup/drop-off on-duty time and the 70-hour/8-day cycle are out of scope (they don't apply to
a single trip of a few days). The schedule can also be disabled (``ContinuousDriving``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

HOUR = 3600.0


class DutyStatus(StrEnum):
    DRIVING = "D"
    BREAK = "B"
    REST = "R"
    ARRIVED = "A"


@dataclass(frozen=True, slots=True)
class Stop:
    kind: DutyStatus  # BREAK or REST
    drive_s: float  # driving time accumulated when the stop starts
    elapsed_s: float  # wall-clock offset from departure when the stop starts
    duration_s: float


class DrivingSchedule(Protocol):
    def elapsed_for_drive(self, drive_s: float) -> float:
        """Wall-clock seconds since departure when ``drive_s`` of driving is reached."""

    def status_at(self, elapsed_s: float, total_drive_s: float) -> tuple[float, DutyStatus]:
        """(driving seconds completed, duty status) at a wall-clock offset."""

    def stops(self, total_drive_s: float) -> list[Stop]:
        """Mandatory stops taken before arrival."""


class ContinuousDriving:
    """No breaks: wall-clock time equals driving time."""

    def elapsed_for_drive(self, drive_s: float) -> float:
        return max(0.0, drive_s)

    def status_at(self, elapsed_s: float, total_drive_s: float) -> tuple[float, DutyStatus]:
        if elapsed_s >= total_drive_s:
            return total_drive_s, DutyStatus.ARRIVED
        return max(0.0, elapsed_s), DutyStatus.DRIVING

    def stops(self, total_drive_s: float) -> list[Stop]:
        return []


@dataclass(frozen=True, slots=True)
class HoursOfService:
    """FMCSA property-carrying limits (49 CFR 395.3), simplified to driving time only."""

    shift_drive_s: float = 11 * HOUR
    break_after_s: float = 8 * HOUR
    break_s: float = 0.5 * HOUR
    rest_s: float = 10 * HOUR

    @property
    def _cycle_s(self) -> float:
        """Wall-clock length of one full shift + rest."""
        return self.shift_drive_s + self.break_s + self.rest_s

    def elapsed_for_drive(self, drive_s: float) -> float:
        if drive_s <= 0:
            return 0.0
        # Rests already completed before this point. Reaching exactly 11 h ends the shift
        # without needing the rest yet (the truck may have arrived).
        rests = math.ceil(drive_s / self.shift_drive_s) - 1
        in_shift = drive_s - rests * self.shift_drive_s
        breaks = rests + (1 if in_shift > self.break_after_s else 0)
        return drive_s + rests * self.rest_s + breaks * self.break_s

    def status_at(self, elapsed_s: float, total_drive_s: float) -> tuple[float, DutyStatus]:
        if elapsed_s <= 0:
            return 0.0, DutyStatus.DRIVING
        cycles = math.floor(elapsed_s / self._cycle_s)
        r = elapsed_s - cycles * self._cycle_s
        drive = cycles * self.shift_drive_s
        if r <= self.break_after_s:
            drive, status = drive + r, DutyStatus.DRIVING
        elif r <= self.break_after_s + self.break_s:
            drive, status = drive + self.break_after_s, DutyStatus.BREAK
        elif r <= self.break_s + self.shift_drive_s:
            drive, status = drive + r - self.break_s, DutyStatus.DRIVING
        else:
            drive, status = drive + self.shift_drive_s, DutyStatus.REST
        if drive >= total_drive_s:
            return total_drive_s, DutyStatus.ARRIVED
        return drive, status

    def stops(self, total_drive_s: float) -> list[Stop]:
        stops: list[Stop] = []
        shift = 0
        while True:
            base = shift * self.shift_drive_s
            break_at = base + self.break_after_s
            rest_at = base + self.shift_drive_s
            if break_at >= total_drive_s:
                break
            stops.append(
                Stop(DutyStatus.BREAK, break_at, self.elapsed_for_drive(break_at), self.break_s)
            )
            if rest_at >= total_drive_s:
                break
            stops.append(
                Stop(DutyStatus.REST, rest_at, self.elapsed_for_drive(rest_at), self.rest_s)
            )
            shift += 1
        return stops
