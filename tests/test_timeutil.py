from datetime import date, datetime, timezone

from app.adapter import TemplateRow
from app.timeutil import is_odd_week, expand, to_display

STUDY_START = date(2026, 9, 1)
SEMESTER_END = date(2026, 12, 27)


def test_first_study_week_is_odd_week():
    assert is_odd_week(date(2026, 9, 1), STUDY_START) is True
    assert is_odd_week(date(2026, 9, 6), STUDY_START) is True


def test_second_week_is_even():
    assert is_odd_week(date(2026, 9, 7), STUDY_START) is False
    assert is_odd_week(date(2026, 9, 13), STUDY_START) is False


def test_third_week_is_odd_again():
    assert is_odd_week(date(2026, 9, 14), STUDY_START) is True


def test_both_weeks_lesson_lands_every_matching_weekday():
    thursday_bd = TemplateRow(3, 6, "both", "БД", "Клочков М.А.", "321/6к", "Лаб")
    occ = expand([thursday_bd], STUDY_START, SEMESTER_END)
    assert all(o["date"].weekday() == 3 for o in occ)
    assert date(2026, 9, 3) in [o["date"] for o in occ]
    assert date(2026, 9, 10) in [o["date"] for o in occ]


def test_odd_week_lesson_only_on_odd_weeks():
    nin = TemplateRow(1, 4, "odd", "НиН", "Щербакова И.Г.", "", "Лек")
    dates = [o["date"] for o in expand([nin], STUDY_START, SEMESTER_END)]
    assert date(2026, 9, 1) in dates
    assert date(2026, 9, 8) not in dates
    assert date(2026, 9, 15) in dates


def test_late_evening_lesson_stored_in_utc():
    late = TemplateRow(3, 8, "both", "X", "Y", "", "Лек")
    occ = expand([late], date(2026, 9, 3), date(2026, 9, 3))
    assert len(occ) == 1
    start = occ[0]["time_start"]
    assert start.tzinfo == timezone.utc
    assert start == datetime(2026, 9, 3, 16, 30, tzinfo=timezone.utc)
    assert occ[0]["time_end"] == datetime(2026, 9, 3, 17, 50, tzinfo=timezone.utc)


def test_display_converts_utc_to_moscow():
    utc = datetime(2026, 9, 3, 16, 30, tzinfo=timezone.utc)
    assert to_display(utc).strftime("%H:%M") == "19:30"


def test_display_crosses_midnight_correctly():
    late_utc = datetime(2026, 9, 3, 22, 30, tzinfo=timezone.utc)
    shown = to_display(late_utc)
    assert shown.date() == date(2026, 9, 4)
    assert shown.strftime("%H:%M") == "01:30"


def test_expansion_never_exceeds_semester_end():
    row = TemplateRow(0, 1, "both", "X", "Y", "", "Лек")
    dates = [o["date"] for o in expand([row], STUDY_START, SEMESTER_END)]
    assert dates
    assert max(dates) <= SEMESTER_END
    assert min(dates) >= STUDY_START


def test_week_bounds_are_monday_to_sunday():
    from app.timeutil import week_bounds

    for probe in (date(2026, 11, 4), date(2026, 11, 9), date(2026, 11, 15)):
        monday, sunday = week_bounds(probe)
        assert monday.weekday() == 0
        assert sunday.weekday() == 6
        assert monday <= probe <= sunday
        assert (sunday - monday).days == 6
