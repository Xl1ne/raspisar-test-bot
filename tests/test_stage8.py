from datetime import date, datetime, timezone

import pytest

from app import storage, timeutil

HEADMAN, STUDENT, OTHER = 100, 200, 300
NAME, URL = "ОБ-09.03.03.02-41", "http://source/"
NOV5 = date(2026, 11, 5)


@pytest.fixture
def gid(conn):
    return storage.register_group(conn, HEADMAN, NAME, URL)["id"]


def _occ(day, subject, kind="Лек", hh=10):
    start = datetime(day.year, day.month, day.day, hh, 0, tzinfo=timezone.utc)
    return {
        "date": day, "time_start": start, "time_end": start.replace(hour=hh + 1),
        "subject": subject, "kind": kind, "room": "421", "teacher": "Иванов",
    }


def _set_marker(conn, tg_user_id, reminded=None, announced=None):
    conn.execute(
        "UPDATE subscribers SET reminded_until=?, announced_until=? WHERE tg_user_id=?",
        (reminded, announced, tg_user_id),
    )
    conn.commit()



def test_quiet_hours_same_day_window():
    noon = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)
    assert timeutil.in_quiet_hours(noon, "11:00", "13:00") is True
    assert timeutil.in_quiet_hours(noon, "13:00", "14:00") is False


def test_quiet_hours_wrap_midnight():
    late = datetime(2026, 11, 5, 20, 30, tzinfo=timezone.utc)
    early = datetime(2026, 11, 5, 4, 0, tzinfo=timezone.utc)
    assert timeutil.in_quiet_hours(late, "22:00", "08:00") is True
    assert timeutil.in_quiet_hours(early, "22:00", "08:00") is True
    noon = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)
    assert timeutil.in_quiet_hours(noon, "22:00", "08:00") is False


def test_quiet_hours_none_means_off():
    noon = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)
    assert timeutil.in_quiet_hours(noon, None, None) is False



def test_set_remind_minutes_persists(conn, gid):
    storage.subscribe(conn, STUDENT, storage.get_group(conn, gid)["invite_code"])
    storage.set_remind_minutes(conn, STUDENT, 45)
    row = conn.execute("SELECT remind_minutes FROM subscribers WHERE tg_user_id=?", (STUDENT,)).fetchone()
    assert row["remind_minutes"] == 45


def test_set_remind_minutes_out_of_range_rejected(conn, gid):
    storage.subscribe(conn, STUDENT, storage.get_group(conn, gid)["invite_code"])
    with pytest.raises(ValueError):
        storage.set_remind_minutes(conn, STUDENT, 1)
    with pytest.raises(ValueError):
        storage.set_remind_minutes(conn, STUDENT, 100000)



def test_due_reminder_returned(conn, gid):
    storage.save_collection(conn, gid, [_occ(NOV5, "БД", hh=10)])
    storage.subscribe(conn, STUDENT, storage.get_group(conn, gid)["invite_code"])
    storage.set_remind_minutes(conn, STUDENT, 60)
    _set_marker(conn, STUDENT, reminded="2026-11-05T08:30:00+00:00")

    now = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)
    due = storage.pop_due_reminders(conn, now)
    assert any(d["tg_user_id"] == STUDENT and d["lesson"]["subject"] == "БД" for d in due)


def test_reminder_not_sent_twice(conn, gid):
    storage.save_collection(conn, gid, [_occ(NOV5, "БД", hh=10)])
    storage.subscribe(conn, STUDENT, storage.get_group(conn, gid)["invite_code"])
    storage.set_remind_minutes(conn, STUDENT, 60)
    _set_marker(conn, STUDENT, reminded="2026-11-05T08:30:00+00:00")

    now = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)
    storage.pop_due_reminders(conn, now)
    again = storage.pop_due_reminders(conn, now)
    assert all(d["tg_user_id"] != STUDENT for d in again)


def test_cancelled_lesson_has_no_reminder(conn, gid):
    storage.save_collection(conn, gid, [_occ(NOV5, "БД", hh=10)])
    storage.subscribe(conn, STUDENT, storage.get_group(conn, gid)["invite_code"])
    storage.set_remind_minutes(conn, STUDENT, 60)
    storage.cancel_lesson(conn, HEADMAN, NOV5, "БД", "Лек")
    _set_marker(conn, STUDENT, reminded="2026-11-05T08:30:00+00:00")

    now = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)
    due = storage.pop_due_reminders(conn, now)
    assert all(d["tg_user_id"] != STUDENT for d in due)


def test_rescheduled_lesson_reminds_new_time(conn, gid):
    storage.save_collection(conn, gid, [_occ(NOV5, "БД", hh=10)])
    storage.subscribe(conn, STUDENT, storage.get_group(conn, gid)["invite_code"])
    storage.set_remind_minutes(conn, STUDENT, 60)
    new_start = datetime(2026, 11, 5, 15, 0, tzinfo=timezone.utc)
    new_end = datetime(2026, 11, 5, 16, 0, tzinfo=timezone.utc)
    storage.reschedule_lesson(conn, HEADMAN, NOV5, "БД", "Лек", new_start, new_end)
    _set_marker(conn, STUDENT, reminded="2026-11-05T13:30:00+00:00")

    now = datetime(2026, 11, 5, 14, 0, tzinfo=timezone.utc)
    due = storage.pop_due_reminders(conn, now)
    match = [d for d in due if d["tg_user_id"] == STUDENT and d["lesson"]["subject"] == "БД"]
    assert match and match[0]["lesson"]["time_start"] == new_start


def test_reminder_dropped_in_quiet_hours(conn, gid):
    storage.save_collection(conn, gid, [_occ(NOV5, "БД", hh=10)])
    storage.subscribe(conn, STUDENT, storage.get_group(conn, gid)["invite_code"])
    storage.set_remind_minutes(conn, STUDENT, 60)
    storage.set_quiet_hours(conn, STUDENT, "11:00", "13:00")
    _set_marker(conn, STUDENT, reminded="2026-11-05T08:30:00+00:00")

    now = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)
    due = storage.pop_due_reminders(conn, now)
    assert all(d["tg_user_id"] != STUDENT for d in due)
    later = storage.pop_due_reminders(conn, datetime(2026, 11, 5, 9, 30, tzinfo=timezone.utc))
    assert all(d["tg_user_id"] != STUDENT for d in later)


def test_stale_reminder_after_lesson_start_skipped(conn, gid):
    storage.save_collection(conn, gid, [_occ(NOV5, "БД", hh=10)])
    storage.subscribe(conn, STUDENT, storage.get_group(conn, gid)["invite_code"])
    storage.set_remind_minutes(conn, STUDENT, 60)
    _set_marker(conn, STUDENT, reminded="2026-11-05T08:00:00+00:00")

    now = datetime(2026, 11, 5, 10, 30, tzinfo=timezone.utc)
    due = storage.pop_due_reminders(conn, now)
    assert all(d["tg_user_id"] != STUDENT for d in due)



def test_announcement_limit_five_per_day(conn, gid):
    now = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
    for i in range(5):
        storage.post_announcement(conn, HEADMAN, f"объявление {i}", now=now)
    with pytest.raises(storage.AnnouncementLimit):
        storage.post_announcement(conn, HEADMAN, "шестое", now=now)


def test_announcement_limit_resets_next_day(conn, gid):
    day1 = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
    for i in range(5):
        storage.post_announcement(conn, HEADMAN, f"д1-{i}", now=day1)
    day2 = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
    storage.post_announcement(conn, HEADMAN, "новый день", now=day2)


def test_announcement_only_headman(conn, gid):
    storage.subscribe(conn, STUDENT, storage.get_group(conn, gid)["invite_code"])
    with pytest.raises(storage.PermissionDenied):
        storage.post_announcement(conn, STUDENT, "я не староста")


def test_announcement_delivered_to_all_once(conn, gid):
    storage.subscribe(conn, STUDENT, storage.get_group(conn, gid)["invite_code"])
    _set_marker(conn, HEADMAN, announced="2026-11-05T11:00:00+00:00")
    _set_marker(conn, STUDENT, announced="2026-11-05T11:00:00+00:00")
    post_now = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
    storage.post_announcement(conn, HEADMAN, "всем привет", now=post_now)

    tick = datetime(2026, 11, 5, 12, 0, 30, tzinfo=timezone.utc)
    delivered = storage.pop_deliverable_announcements(conn, tick)
    recipients = {d["tg_user_id"] for d in delivered}
    assert recipients == {HEADMAN, STUDENT}
    assert storage.pop_deliverable_announcements(conn, tick) == []


def test_announcement_deferred_until_quiet_hours_end(conn, gid):
    storage.subscribe(conn, STUDENT, storage.get_group(conn, gid)["invite_code"])
    storage.set_quiet_hours(conn, STUDENT, "11:00", "13:00")
    _set_marker(conn, STUDENT, announced="2026-11-05T09:00:00+00:00")
    _set_marker(conn, HEADMAN, announced="2026-11-05T09:00:00+00:00")
    post_now = datetime(2026, 11, 5, 9, 30, tzinfo=timezone.utc)
    storage.post_announcement(conn, HEADMAN, "ночью", now=post_now)

    quiet_tick = datetime(2026, 11, 5, 9, 40, tzinfo=timezone.utc)
    during = storage.pop_deliverable_announcements(conn, quiet_tick)
    assert all(d["tg_user_id"] != STUDENT for d in during)

    after_tick = datetime(2026, 11, 5, 10, 5, tzinfo=timezone.utc)
    after = storage.pop_deliverable_announcements(conn, after_tick)
    assert any(d["tg_user_id"] == STUDENT for d in after)



def test_transfer_role_moves_headman(conn, gid):
    storage.subscribe(conn, STUDENT, storage.get_group(conn, gid)["invite_code"])
    storage.transfer_role(conn, HEADMAN, STUDENT)
    assert storage.get_group(conn, gid)["headman_id"] == STUDENT
    with pytest.raises(storage.PermissionDenied):
        storage.require_headman(conn, HEADMAN)
    assert storage.require_headman(conn, STUDENT)["id"] == gid


def test_transfer_role_only_to_member(conn, gid):
    with pytest.raises(storage.NotAMember):
        storage.transfer_role(conn, HEADMAN, 999)


def test_transfer_role_only_by_headman(conn, gid):
    storage.subscribe(conn, STUDENT, storage.get_group(conn, gid)["invite_code"])
    with pytest.raises(storage.PermissionDenied):
        storage.transfer_role(conn, STUDENT, STUDENT)



def test_student_unsubscribes(conn, gid):
    storage.subscribe(conn, STUDENT, storage.get_group(conn, gid)["invite_code"])
    storage.unsubscribe(conn, STUDENT)
    assert storage.group_of(conn, STUDENT) is None


def test_headman_cannot_leave_with_subscribers(conn, gid):
    storage.subscribe(conn, STUDENT, storage.get_group(conn, gid)["invite_code"])
    with pytest.raises(storage.HeadmanHasSubscribers):
        storage.unsubscribe(conn, HEADMAN)
    assert storage.group_of(conn, HEADMAN) is not None


def test_last_subscriber_headman_leaves_and_group_stays(conn, gid):
    storage.unsubscribe(conn, HEADMAN)
    assert storage.group_of(conn, HEADMAN) is None
    assert storage.get_group(conn, gid) is not None



def test_former_lone_headman_has_no_rights_over_abandoned_group(conn):
    old = storage.register_group(conn, HEADMAN, "СТАРАЯ", URL)
    storage.unsubscribe(conn, HEADMAN)
    new = storage.register_group(conn, HEADMAN, "НОВАЯ", URL)

    assert storage.require_headman(conn, HEADMAN)["id"] == new["id"]
    storage.set_source(conn, HEADMAN, "http://new/")
    assert storage.get_group(conn, old["id"])["source_url"] == URL
    assert storage.get_group(conn, new["id"])["source_url"] == "http://new/"


def test_former_headman_joining_elsewhere_loses_rights(conn):
    storage.register_group(conn, HEADMAN, "СТАРАЯ", URL)
    storage.unsubscribe(conn, HEADMAN)
    other = storage.register_group(conn, OTHER, "ЧУЖАЯ", URL)
    storage.subscribe(conn, HEADMAN, other["invite_code"])
    with pytest.raises(storage.PermissionDenied):
        storage.require_headman(conn, HEADMAN)


def test_settings_require_membership(conn, gid):
    with pytest.raises(storage.NotAMember):
        storage.set_remind_minutes(conn, 999, 30)
    with pytest.raises(storage.NotAMember):
        storage.set_quiet_hours(conn, 999, "22:00", "08:00")
