from datetime import date, datetime, timezone

from icalendar import Calendar

from app.ical import build_ics


def _lesson(hh_utc=16, mm=30, subject="ЦМЗАД", cancelled=False):
    start = datetime(2026, 9, 3, hh_utc, mm, tzinfo=timezone.utc)
    return {
        "date": date(2026, 9, 3),
        "time_start": start,
        "time_end": datetime(2026, 9, 3, 17, 50, tzinfo=timezone.utc),
        "subject": subject,
        "kind": "Лек",
        "room": "412/6к",
        "teacher": "Фёдоров Д.Л.",
        "source": "auto",
        "cancelled": cancelled,
    }


GROUP = {"id": 1, "name": "ОБ-09.03.03.02-41", "calendar_code": "cal-xyz"}


def test_calendar_is_rfc5545_conformant():
    ics = build_ics(GROUP, [_lesson()])
    assert b"\r\n" in ics
    cal = Calendar.from_ical(ics)
    assert cal.get("version") == "2.0"
    assert cal.get("prodid")
    events = [c for c in cal.walk("VEVENT")]
    assert len(events) == 1
    ev = events[0]
    assert ev.get("uid")
    assert ev.get("dtstamp")
    assert ev.get("dtstart")
    assert ev.get("dtend")


def test_late_evening_lesson_serialized_in_utc():
    ics = build_ics(GROUP, [_lesson(hh_utc=16, mm=30)])
    assert b"DTSTART:20260903T163000Z" in ics


def test_teacher_present_in_event():
    ics = build_ics(GROUP, [_lesson()]).decode("utf-8")
    assert "Фёдоров Д.Л." in ics


def test_cancelled_lesson_marked_not_dropped():
    ics = build_ics(GROUP, [_lesson(cancelled=True)])
    events = Calendar.from_ical(ics).walk("VEVENT")
    assert len(events) == 1
    assert str(events[0].get("status")) == "CANCELLED"
    assert str(events[0].get("summary")).startswith("Отменено")


def test_dtstamp_is_real_generation_time():
    before = datetime.now(tz=timezone.utc).replace(microsecond=0)
    ics = build_ics(GROUP, [_lesson()])
    stamp = Calendar.from_ical(ics).walk("VEVENT")[0].get("dtstamp").dt
    assert stamp >= before


def test_uid_ignores_time_shift_by_source():
    a = build_ics(GROUP, [_lesson(hh_utc=16, mm=30)])
    b = build_ics(GROUP, [_lesson(hh_utc=17, mm=0)])
    uid_a = Calendar.from_ical(a).walk("VEVENT")[0].get("uid")
    uid_b = Calendar.from_ical(b).walk("VEVENT")[0].get("uid")
    assert uid_a == uid_b


def test_event_uid_is_stable_across_builds():
    a = build_ics(GROUP, [_lesson()])
    b = build_ics(GROUP, [_lesson()])
    uid_a = Calendar.from_ical(a).walk("VEVENT")[0].get("uid")
    uid_b = Calendar.from_ical(b).walk("VEVENT")[0].get("uid")
    assert uid_a == uid_b
