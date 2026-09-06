
import pytest

from app import storage


HEADMAN = 100
STUDENT = 200
OTHER = 300
NAME = "ОБ-09.03.03.02-41"
URL = "http://source/"


def _codes(subs):
    return {s["tg_user_id"] for s in subs}


def test_register_makes_creator_headman(conn):
    group = storage.register_group(conn, HEADMAN, NAME, URL)
    assert group["headman_id"] == HEADMAN
    assert group["name"] == NAME
    assert group["source_url"] == URL


def test_register_issues_codes(conn):
    group = storage.register_group(conn, HEADMAN, NAME, URL)
    assert group["invite_code"] and len(group["invite_code"]) >= 6
    assert group["calendar_code"] and len(group["calendar_code"]) >= 12
    other = storage.register_group(conn, OTHER, "ГР-2", URL)
    assert group["invite_code"] != other["invite_code"]
    assert group["calendar_code"] != other["calendar_code"]


def test_creator_is_auto_subscribed_and_marked(conn):
    storage.register_group(conn, HEADMAN, NAME, URL)
    subs = storage.list_subscribers(conn, HEADMAN)
    assert _codes(subs) == {HEADMAN}
    assert any(s["tg_user_id"] == HEADMAN and s["is_headman"] for s in subs)


def test_user_already_in_group_cannot_register(conn):
    storage.register_group(conn, HEADMAN, NAME, URL)
    with pytest.raises(storage.AlreadyInGroup):
        storage.register_group(conn, HEADMAN, "ГР-2", URL)
    assert len(storage.list_groups(conn)) == 1


def test_student_in_group_cannot_register_own(conn):
    group = storage.register_group(conn, HEADMAN, NAME, URL)
    storage.subscribe(conn, STUDENT, group["invite_code"])
    with pytest.raises(storage.AlreadyInGroup):
        storage.register_group(conn, STUDENT, "ГР-2", URL)


def test_subscribe_with_correct_code(conn):
    group = storage.register_group(conn, HEADMAN, NAME, URL)
    joined = storage.subscribe(conn, STUDENT, group["invite_code"])
    assert joined["id"] == group["id"]
    assert _codes(storage.list_subscribers(conn, HEADMAN)) == {HEADMAN, STUDENT}


def test_subscribe_wrong_code_rejected(conn):
    storage.register_group(conn, HEADMAN, NAME, URL)
    with pytest.raises(LookupError):
        storage.subscribe(conn, STUDENT, "нет-такого-кода")
    assert _codes(storage.list_subscribers(conn, HEADMAN)) == {HEADMAN}


def test_subscribe_twice_no_duplicate(conn):
    group = storage.register_group(conn, HEADMAN, NAME, URL)
    storage.subscribe(conn, STUDENT, group["invite_code"])
    again = storage.subscribe(conn, STUDENT, group["invite_code"])
    assert again["id"] == group["id"]
    subs = storage.list_subscribers(conn, HEADMAN)
    assert sum(1 for s in subs if s["tg_user_id"] == STUDENT) == 1


def test_user_cannot_join_second_group(conn):
    g1 = storage.register_group(conn, HEADMAN, NAME, URL)
    g2 = storage.register_group(conn, OTHER, "ГР-2", URL)
    storage.subscribe(conn, STUDENT, g1["invite_code"])
    with pytest.raises(storage.AlreadyInGroup):
        storage.subscribe(conn, STUDENT, g2["invite_code"])


def test_set_source_by_headman(conn):
    group = storage.register_group(conn, HEADMAN, NAME, "http://old/")
    storage.set_source(conn, HEADMAN, "http://new/")
    assert storage.get_group(conn, group["id"])["source_url"] == "http://new/"


def test_set_source_by_student_denied_and_unchanged(conn):
    group = storage.register_group(conn, HEADMAN, NAME, "http://old/")
    storage.subscribe(conn, STUDENT, group["invite_code"])
    with pytest.raises(storage.PermissionDenied):
        storage.set_source(conn, STUDENT, "http://hacked/")
    assert storage.get_group(conn, group["id"])["source_url"] == "http://old/"


def test_set_source_by_outsider_denied(conn):
    with pytest.raises(storage.PermissionDenied):
        storage.set_source(conn, 999, "http://x/")


def test_list_subscribers_denied_for_student(conn):
    group = storage.register_group(conn, HEADMAN, NAME, URL)
    storage.subscribe(conn, STUDENT, group["invite_code"])
    with pytest.raises(storage.PermissionDenied):
        storage.list_subscribers(conn, STUDENT)


def test_list_subscribers_denied_for_outsider(conn):
    with pytest.raises(storage.PermissionDenied):
        storage.list_subscribers(conn, 999)


def test_list_subscribers_exposes_only_id_and_role(conn):
    group = storage.register_group(conn, HEADMAN, NAME, URL)
    storage.subscribe(conn, STUDENT, group["invite_code"])
    for s in storage.list_subscribers(conn, HEADMAN):
        assert set(s.keys()) == {"tg_user_id", "is_headman"}


def test_group_of(conn):
    group = storage.register_group(conn, HEADMAN, NAME, URL)
    assert storage.group_of(conn, HEADMAN)["id"] == group["id"]
    assert storage.group_of(conn, 999) is None
