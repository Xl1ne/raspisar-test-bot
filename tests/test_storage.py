import sqlite3
from datetime import date, datetime, timezone

import pytest

from app import storage
from app.adapter import CollectError
from app.scheduler import collect_group


def _occ(subject, day=date(2026, 9, 3), hh=13, source="auto"):
    start = datetime(2026, 9, 3, hh, 0, tzinfo=timezone.utc)
    return {
        "date": day,
        "time_start": start,
        "time_end": start.replace(hour=hh + 1),
        "subject": subject,
        "kind": "Лек",
        "room": "421/6к",
        "teacher": "Иванов И.И.",
        "source": source,
        "cancelled": False,
    }


@pytest.fixture
def group(conn):
    return storage.register_group(conn, 1, "ОБ-09.03.03.02-41", "http://source/")["id"]


def test_save_collection_stores_schedule(conn, group):
    storage.save_collection(conn, group, [_occ("Матан"), _occ("Физика")])
    subjects = {row["subject"] for row in storage.get_schedule(conn, group)}
    assert subjects == {"Матан", "Физика"}


def test_failed_collect_keeps_previous_schedule(conn, group):
    storage.save_collection(conn, group, [_occ("Матан")])

    def broken(url, code):
        raise CollectError("источник недоступен")

    collect_group(conn, storage.get_group(conn, group), collector=broken)
    subjects = {row["subject"] for row in storage.get_schedule(conn, group)}
    assert subjects == {"Матан"}


def test_successful_collect_replaces_auto_schedule(conn, group):
    storage.save_collection(conn, group, [_occ("Старое")])

    def ok(url, code):
        return [_occ("Новое")]

    collect_group(conn, storage.get_group(conn, group), collector=ok)
    subjects = {row["subject"] for row in storage.get_schedule(conn, group)}
    assert subjects == {"Новое"}


def test_collection_does_not_touch_manual_rows(conn, group):
    storage.save_collection(conn, group, [_occ("Авто")])
    conn.execute(
        "INSERT INTO lessons (group_id, date, time_start, time_end, subject, kind, room, teacher, source, cancelled)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (group, "2026-09-03", "2026-09-03T10:00:00+00:00", "2026-09-03T11:00:00+00:00",
         "Правка старосты", "Лек", "100", "Петров П.П.", "manual", 0),
    )
    conn.commit()
    storage.save_collection(conn, group, [_occ("Авто2")])
    subjects = {row["subject"] for row in storage.get_schedule(conn, group)}
    assert "Правка старосты" in subjects
    assert "Авто2" in subjects
    assert "Авто" not in subjects


def test_find_group_by_wrong_calendar_code_returns_none(conn, group):
    code = storage.get_group(conn, group)["calendar_code"]
    assert storage.find_group_by_calendar_code(conn, code) is not None
    assert storage.find_group_by_calendar_code(conn, "неверный-код") is None


def test_collect_all_visits_every_group(conn):
    g1 = storage.register_group(conn, 1, "ГР-1", "http://source/1")["id"]
    g2 = storage.register_group(conn, 2, "ГР-2", "http://source/2")["id"]

    from app.scheduler import collect_all

    def collector(url, code):
        return [_occ(f"пара-{code}")]

    assert collect_all(conn, collector=collector) == 2
    assert {r["subject"] for r in storage.get_schedule(conn, g1)} == {"пара-ГР-1"}
    assert {r["subject"] for r in storage.get_schedule(conn, g2)} == {"пара-ГР-2"}


def test_user_cannot_be_in_two_groups(conn):
    g1 = storage.register_group(conn, 1, "ГР-1", "http://source/1")["id"]
    g2 = storage.register_group(conn, 2, "ГР-2", "http://source/2")["id"]
    conn.execute("INSERT INTO subscribers (tg_user_id, group_id) VALUES (?, ?)", (777, g1))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO subscribers (tg_user_id, group_id) VALUES (?, ?)", (777, g2))
