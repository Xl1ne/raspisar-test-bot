from datetime import date, datetime, timezone

import pytest
from fastapi import HTTPException

from app import api, config, storage


def _occ(subject):
    start = datetime(2026, 9, 3, 16, 30, tzinfo=timezone.utc)
    return {"date": date(2026, 9, 3), "time_start": start, "time_end": start.replace(hour=17, minute=50),
            "subject": subject, "kind": "Лек", "room": "412/6к", "teacher": "Фёдоров Д.Л."}


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "test.db")
    monkeypatch.setattr(config, "DB_PATH", path)
    storage.ensure_schema()
    conn = storage.connect()
    group = storage.register_group(conn, 1, "ОБ-09.03.03.02-41", "http://source/")
    storage.save_collection(conn, group["id"], [_occ("ЦМЗАД")])
    conn.close()
    return group["calendar_code"]


def test_endpoint_returns_calendar_for_known_code(db):
    response = api.calendar(db)
    assert response.status_code == 200
    assert response.media_type.startswith("text/calendar")
    assert b"BEGIN:VCALENDAR" in response.body


def test_endpoint_rejects_unknown_code(db):
    with pytest.raises(HTTPException) as err:
        api.calendar("guessed-code")
    assert err.value.status_code == 404
