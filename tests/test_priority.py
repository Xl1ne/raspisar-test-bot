from datetime import date, datetime, timezone

import pytest

from app import storage
from app.scheduler import collect_group

HEADMAN, STUDENT = 100, 200
NAME, URL = "ОБ-09.03.03.02-41", "http://source/"

NOV5 = date(2026, 11, 5)
NOV12 = date(2026, 11, 12)


@pytest.fixture
def gid(conn):
    return storage.register_group(conn, HEADMAN, NAME, URL)["id"]


def _occ(day, subject, kind="Лек", hh=13, room="421/6к", teacher="Иванов И.И."):
    start = datetime(day.year, day.month, day.day, hh, 0, tzinfo=timezone.utc)
    end = start.replace(hour=hh + 1)
    return {
        "date": day, "time_start": start, "time_end": end,
        "subject": subject, "kind": kind, "room": room, "teacher": teacher,
    }


def _find(sched, day, subject, kind="Лек"):
    for r in sched:
        if r["date"] == day and r["subject"] == subject and r["kind"] == kind:
            return r
    return None


def _resync(conn, gid, occ_list):
    """Имитирует ночной сбор: источник отдаёт occ_list, планировщик сохраняет."""
    group = storage.get_group(conn, gid)
    collect_group(conn, group, collector=lambda url, code: list(occ_list))



def test_collect_does_not_erase_manual_edit(conn, gid):
    source = [_occ(NOV5, "БД", room="421/6к")]
    storage.save_collection(conn, gid, source)
    storage.change_room(conn, HEADMAN, NOV5, "БД", "Лек", "100/1к")

    _resync(conn, gid, source)

    row = _find(storage.get_schedule(conn, gid), NOV5, "БД")
    assert row["source"] == "manual"
    assert row["room"] == "100/1к"



def test_edit_does_not_leak_into_next_week(conn, gid):
    source = [_occ(NOV5, "БД", room="A"), _occ(NOV12, "БД", room="A")]
    storage.save_collection(conn, gid, source)
    storage.change_room(conn, HEADMAN, NOV5, "БД", "Лек", "ПРАВКА")

    _resync(conn, gid, source)
    sched = storage.get_schedule(conn, gid)

    assert _find(sched, NOV5, "БД")["room"] == "ПРАВКА"
    assert _find(sched, NOV12, "БД")["room"] == "A"
    assert _find(sched, NOV12, "БД")["source"] == "auto"



def test_cancelled_lesson_not_resurrected_by_collect(conn, gid):
    source = [_occ(NOV5, "БД")]
    storage.save_collection(conn, gid, source)
    storage.cancel_lesson(conn, HEADMAN, NOV5, "БД", "Лек")

    _resync(conn, gid, source)

    row = _find(storage.get_schedule(conn, gid), NOV5, "БД")
    assert row["source"] == "manual"
    assert row["cancelled"] is True



def test_reschedule_wins_even_when_source_shifts_time(conn, gid):
    storage.save_collection(conn, gid, [_occ(NOV5, "БД", hh=13)])
    new_start = datetime(2026, 11, 5, 9, 50, tzinfo=timezone.utc)
    new_end = datetime(2026, 11, 5, 11, 10, tzinfo=timezone.utc)
    storage.reschedule_lesson(conn, HEADMAN, NOV5, "БД", "Лек", new_start, new_end)

    _resync(conn, gid, [_occ(NOV5, "БД", hh=16)])

    row = _find(storage.get_schedule(conn, gid), NOV5, "БД")
    assert row["source"] == "manual"
    assert row["time_start"] == new_start



def test_reschedule_survives_source_removal(conn, gid):
    storage.save_collection(conn, gid, [_occ(NOV5, "БД", hh=13)])
    new_start = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
    new_end = datetime(2026, 11, 5, 13, 20, tzinfo=timezone.utc)
    storage.reschedule_lesson(conn, HEADMAN, NOV5, "БД", "Лек", new_start, new_end)

    _resync(conn, gid, [])

    storage.save_collection(conn, gid, [_occ(NOV5, "Матан")])
    row = _find(storage.get_schedule(conn, gid), NOV5, "БД")
    assert row is not None
    assert row["time_start"] == new_start


def test_cancel_survives_source_removal(conn, gid):
    storage.save_collection(conn, gid, [_occ(NOV5, "БД")])
    storage.cancel_lesson(conn, HEADMAN, NOV5, "БД", "Лек")

    storage.save_collection(conn, gid, [_occ(NOV5, "Матан")])

    row = _find(storage.get_schedule(conn, gid), NOV5, "БД")
    assert row is not None
    assert row["cancelled"] is True



def test_student_cannot_edit(conn, gid):
    storage.save_collection(conn, gid, [_occ(NOV5, "БД", room="A")])
    storage.subscribe(conn, STUDENT, storage.get_group(conn, gid)["invite_code"])

    for op in (
        lambda: storage.cancel_lesson(conn, STUDENT, NOV5, "БД", "Лек"),
        lambda: storage.change_room(conn, STUDENT, NOV5, "БД", "Лек", "ВЗЛОМ"),
        lambda: storage.reschedule_lesson(
            conn, STUDENT, NOV5, "БД", "Лек",
            datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc),
            datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc),
        ),
    ):
        with pytest.raises(storage.PermissionDenied):
            op()

    row = _find(storage.get_schedule(conn, gid), NOV5, "БД")
    assert row["source"] == "auto"
    assert row["room"] == "A"
    assert row["cancelled"] is False



def test_edit_identity_distinguishes_kind(conn, gid):
    storage.save_collection(conn, gid, [
        _occ(NOV5, "УИ", kind="Лаб", room="325/6к", hh=13),
        _occ(NOV5, "УИ", kind="Лек", room="421/6к", hh=15),
    ])
    storage.change_room(conn, HEADMAN, NOV5, "УИ", "Лаб", "ДРУГАЯ")
    sched = storage.get_schedule(conn, gid)

    assert _find(sched, NOV5, "УИ", "Лаб")["room"] == "ДРУГАЯ"
    assert _find(sched, NOV5, "УИ", "Лек")["room"] == "421/6к"
    assert _find(sched, NOV5, "УИ", "Лек")["source"] == "auto"



def test_edit_made_ahead_holds_through_repeated_collects(conn, gid):
    source = [_occ(NOV5, "БД", room="A")]
    storage.save_collection(conn, gid, source)
    storage.change_room(conn, HEADMAN, NOV5, "БД", "Лек", "ЗАРАНЕЕ")

    for _ in range(30):
        _resync(conn, gid, source)

    assert _find(storage.get_schedule(conn, gid), NOV5, "БД")["room"] == "ЗАРАНЕЕ"



def test_re_editing_replaces_manual_row(conn, gid):
    storage.save_collection(conn, gid, [_occ(NOV5, "БД", room="A")])
    storage.change_room(conn, HEADMAN, NOV5, "БД", "Лек", "ПЕРВАЯ")
    storage.change_room(conn, HEADMAN, NOV5, "БД", "Лек", "ВТОРАЯ")

    sched = [r for r in storage.get_schedule(conn, gid) if r["subject"] == "БД"]
    assert len(sched) == 1
    assert sched[0]["room"] == "ВТОРАЯ"



def test_edit_missing_lesson_rejected(conn, gid):
    with pytest.raises(storage.LessonNotFound):
        storage.cancel_lesson(conn, HEADMAN, NOV5, "НЕТ ТАКОЙ", "Лек")


def test_editing_cancelled_lesson_keeps_it_cancelled(conn, gid):
    storage.save_collection(conn, gid, [_occ(NOV5, "БД", room="A")])
    storage.cancel_lesson(conn, HEADMAN, NOV5, "БД", "Лек")
    storage.change_room(conn, HEADMAN, NOV5, "БД", "Лек", "B")

    row = _find(storage.get_schedule(conn, gid), NOV5, "БД")
    assert row["cancelled"] is True
    assert row["room"] == "B"
