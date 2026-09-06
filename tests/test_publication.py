from datetime import date, datetime, timezone

import pytest

from app import storage
from app.publication import render_calendar


def _occ(subject):
    start = datetime(2026, 9, 3, 16, 30, tzinfo=timezone.utc)
    return {
        "date": date(2026, 9, 3), "time_start": start,
        "time_end": start.replace(hour=17, minute=50),
        "subject": subject, "kind": "Лек", "room": "412/6к",
        "teacher": "Фёдоров Д.Л.", "source": "auto", "cancelled": False,
    }


def test_render_returns_ics_for_known_code(conn):
    group = storage.register_group(conn, 1, "ОБ-09.03.03.02-41", "http://source/")
    storage.save_collection(conn, group["id"], [_occ("ЦМЗАД")])
    body = render_calendar(conn, group["calendar_code"])
    assert b"BEGIN:VCALENDAR" in body
    assert "ЦМЗАД".encode("utf-8") in body


def test_wrong_code_raises_not_found(conn):
    storage.register_group(conn, 1, "ОБ-09.03.03.02-41", "http://source/")
    with pytest.raises(LookupError):
        render_calendar(conn, "guessed-code")
