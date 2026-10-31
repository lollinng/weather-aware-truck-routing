import pytest

from planner.domain.hos import ContinuousDriving, DutyStatus, HoursOfService

H = 3600.0
hos = HoursOfService()


@pytest.mark.parametrize(
    ("drive_h", "elapsed_h"),
    [
        (0, 0),
        (5, 5),
        (8, 8),  # reaching 8 h doesn't require the break yet
        (8.5, 9),  # 30-min break after 8 h of driving
        (11, 11.5),  # end of first shift
        (12, 22.5),  # + 10 h rest
        (19, 29.5),  # 8 h into shift 2
        (20, 31),  # + second break
        (22, 33),  # end of shift 2
        (23, 44),  # + second rest
    ],
)
def test_elapsed_for_drive(drive_h, elapsed_h):
    assert hos.elapsed_for_drive(drive_h * H) == pytest.approx(elapsed_h * H)


@pytest.mark.parametrize(
    ("elapsed_h", "drive_h", "status"),
    [
        (4, 4, DutyStatus.DRIVING),
        (8.25, 8, DutyStatus.BREAK),
        (10, 9.5, DutyStatus.DRIVING),
        (15, 11, DutyStatus.REST),
        (22.5, 12, DutyStatus.DRIVING),
    ],
)
def test_status_at(elapsed_h, drive_h, status):
    drive_s, got = hos.status_at(elapsed_h * H, total_drive_s=100 * H)
    assert drive_s == pytest.approx(drive_h * H)
    assert got == status


def test_status_after_arrival():
    assert hos.status_at(30 * H, total_drive_s=10 * H) == (10 * H, DutyStatus.ARRIVED)


@pytest.mark.parametrize("drive_h", [0.5, 7.9, 8, 9, 11, 11.01, 19.3, 30, 47.2])
def test_status_at_inverts_elapsed_for_drive(drive_h):
    elapsed = hos.elapsed_for_drive(drive_h * H)
    drive_s, _ = hos.status_at(elapsed, total_drive_s=100 * H)
    assert drive_s == pytest.approx(drive_h * H)


def test_stops_for_a_two_day_trip():
    stops = hos.stops(20 * H)
    assert [(s.kind, s.drive_s / H, s.elapsed_s / H) for s in stops] == [
        (DutyStatus.BREAK, 8, 8),
        (DutyStatus.REST, 11, 11.5),
        (DutyStatus.BREAK, 19, 29.5),
    ]


def test_no_stops_when_arriving_exactly_at_a_limit():
    assert hos.stops(8 * H) == []
    assert [s.kind for s in hos.stops(11 * H)] == [DutyStatus.BREAK]


def test_continuous_driving_is_identity():
    schedule = ContinuousDriving()
    assert schedule.elapsed_for_drive(12 * H) == 12 * H
    assert schedule.status_at(5 * H, 10 * H) == (5 * H, DutyStatus.DRIVING)
    assert schedule.status_at(11 * H, 10 * H) == (10 * H, DutyStatus.ARRIVED)
    assert schedule.stops(40 * H) == []
