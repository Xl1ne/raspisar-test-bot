import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

from app import config, timeutil

SOURCE_AUTO = "auto"
SOURCE_MANUAL = "manual"

INVITE_CODE_BYTES = 6
CALENDAR_CODE_BYTES = 16


class PermissionDenied(Exception):
    """Операцию вызвал тот, у кого нет на неё права (NFR-03)."""


class AlreadyInGroup(Exception):
    """Пользователь уже состоит в группе: один пользователь — одна группа."""


class LessonNotFound(Exception):
    """Правка адресована занятию, которого нет в расписании группы."""


class AnnouncementLimit(Exception):
    """Исчерпан суточный лимит объявлений на группу (NFR-08)."""


class NotAMember(Exception):
    """Действие адресовано пользователю, который не состоит в группе."""


class HeadmanHasSubscribers(Exception):
    """Староста не может выйти, пока в группе есть другие подписчики (Р-16)."""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    invite_code TEXT NOT NULL UNIQUE,
    headman_id INTEGER,
    calendar_code TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS lessons (
    id INTEGER PRIMARY KEY,
    group_id INTEGER NOT NULL REFERENCES groups(id),
    date TEXT NOT NULL,
    time_start TEXT NOT NULL,
    time_end TEXT NOT NULL,
    subject TEXT NOT NULL,
    kind TEXT NOT NULL,
    room TEXT NOT NULL,
    teacher TEXT NOT NULL,
    source TEXT NOT NULL,
    cancelled INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS subscribers (
    id INTEGER PRIMARY KEY,
    tg_user_id INTEGER NOT NULL UNIQUE,
    group_id INTEGER NOT NULL REFERENCES groups(id),
    remind_minutes INTEGER,
    quiet_start TEXT,
    quiet_end TEXT,
    reminded_until TEXT,
    announced_until TEXT
);
CREATE TABLE IF NOT EXISTS announcements (
    id INTEGER PRIMARY KEY,
    group_id INTEGER NOT NULL REFERENCES groups(id),
    text TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    author_id INTEGER NOT NULL
);
"""


BUSY_TIMEOUT_MS = 5000


def connect():
    directory = os.path.dirname(config.DB_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    return conn


@contextmanager
def session():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def run(fn, *args):
    with session() as conn:
        return fn(conn, *args)


def _migrate(conn):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(subscribers)")}
    for col in ("reminded_until", "announced_until"):
        if col not in cols:
            conn.execute(f"ALTER TABLE subscribers ADD COLUMN {col} TEXT")


def init_db(conn):
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    _migrate(conn)
    conn.commit()


def ensure_schema():
    run(init_db)


def get_group(conn, group_id):
    return conn.execute("SELECT * FROM groups WHERE id = ?", (group_id,)).fetchone()


def list_groups(conn):
    return conn.execute("SELECT * FROM groups ORDER BY id").fetchall()


def find_group_by_calendar_code(conn, code):
    return conn.execute("SELECT * FROM groups WHERE calendar_code = ?", (code,)).fetchone()


def save_collection(conn, group_id, occurrences):
    with conn:
        conn.execute(
            "DELETE FROM lessons WHERE group_id = ? AND source = ?", (group_id, SOURCE_AUTO)
        )
        conn.executemany(
            "INSERT INTO lessons (group_id, date, time_start, time_end, subject, kind,"
            " room, teacher, source, cancelled) VALUES (?,?,?,?,?,?,?,?,?,0)",
            [
                (
                    group_id,
                    o["date"].isoformat(),
                    o["time_start"].isoformat(),
                    o["time_end"].isoformat(),
                    o["subject"],
                    o["kind"],
                    o["room"],
                    o["teacher"],
                    SOURCE_AUTO,
                )
                for o in occurrences
            ],
        )


def _lesson_dict(r):
    return {
        "date": date.fromisoformat(r["date"]),
        "time_start": datetime.fromisoformat(r["time_start"]),
        "time_end": datetime.fromisoformat(r["time_end"]),
        "subject": r["subject"],
        "kind": r["kind"],
        "room": r["room"],
        "teacher": r["teacher"],
        "source": r["source"],
        "cancelled": bool(r["cancelled"]),
    }


def lesson_title(lesson):
    return f"{lesson['subject']} ({lesson['kind']})" if lesson["kind"] else lesson["subject"]


def get_schedule(conn, group_id):
    rows = conn.execute(
        "SELECT * FROM lessons WHERE group_id = ?", (group_id,)
    ).fetchall()
    resolved = {}
    for r in rows:
        key = (r["date"], r["subject"], r["kind"])
        if key not in resolved or r["source"] == SOURCE_MANUAL:
            resolved[key] = r
    picked = sorted(resolved.values(), key=lambda r: r["time_start"])
    return [_lesson_dict(r) for r in picked]


def group_of(conn, tg_user_id):
    return conn.execute(
        "SELECT g.* FROM groups g JOIN subscribers s ON s.group_id = g.id"
        " WHERE s.tg_user_id = ?",
        (tg_user_id,),
    ).fetchone()


def require_headman(conn, executor_id):
    group = conn.execute(
        "SELECT g.* FROM groups g JOIN subscribers s ON s.group_id = g.id"
        " WHERE g.headman_id = ? AND s.tg_user_id = ?",
        (executor_id, executor_id),
    ).fetchone()
    if group is None:
        raise PermissionDenied("операция доступна только старосте группы")
    return group


def register_group(conn, headman_id, name, source_url):
    if group_of(conn, headman_id) is not None:
        raise AlreadyInGroup("пользователь уже состоит в группе")
    invite_code = secrets.token_urlsafe(INVITE_CODE_BYTES)
    calendar_code = secrets.token_urlsafe(CALENDAR_CODE_BYTES)
    with conn:
        cur = conn.execute(
            "INSERT INTO groups (name, source_url, invite_code, headman_id, calendar_code)"
            " VALUES (?,?,?,?,?)",
            (name, source_url, invite_code, headman_id, calendar_code),
        )
        group_id = cur.lastrowid
        _add_subscriber(conn, headman_id, group_id)
    return get_group(conn, group_id)


def subscribe(conn, tg_user_id, invite_code):
    group = conn.execute(
        "SELECT * FROM groups WHERE invite_code = ?", (invite_code,)
    ).fetchone()
    if group is None:
        raise LookupError("неверный код приглашения")
    current = group_of(conn, tg_user_id)
    if current is not None:
        if current["id"] == group["id"]:
            return group
        raise AlreadyInGroup("пользователь уже состоит в другой группе")
    with conn:
        _add_subscriber(conn, tg_user_id, group["id"])
    return group


def set_source(conn, executor_id, source_url):
    group = require_headman(conn, executor_id)
    with conn:
        conn.execute(
            "UPDATE groups SET source_url = ? WHERE id = ?", (source_url, group["id"])
        )
    return get_group(conn, group["id"])


def list_subscribers(conn, executor_id):
    group = require_headman(conn, executor_id)
    rows = conn.execute(
        "SELECT tg_user_id FROM subscribers WHERE group_id = ? ORDER BY id",
        (group["id"],),
    ).fetchall()
    return [
        {"tg_user_id": r["tg_user_id"], "is_headman": r["tg_user_id"] == group["headman_id"]}
        for r in rows
    ]


def _current_lesson(conn, group_id, day_iso, subject, kind):
    return conn.execute(
        "SELECT * FROM lessons WHERE group_id = ? AND date = ? AND subject = ?"
        " AND kind = ? ORDER BY (source = ?) DESC LIMIT 1",
        (group_id, day_iso, subject, kind, SOURCE_MANUAL),
    ).fetchone()


def _write_manual(conn, executor_id, day, subject, kind, **changes):
    group = require_headman(conn, executor_id)
    day_iso = day.isoformat()
    base = _current_lesson(conn, group["id"], day_iso, subject, kind)
    if base is None:
        raise LessonNotFound(f"{day_iso} {subject} ({kind})")
    row = {
        "time_start": base["time_start"],
        "time_end": base["time_end"],
        "room": base["room"],
        "teacher": base["teacher"],
        "cancelled": base["cancelled"],
    }
    row.update(changes)
    with conn:
        conn.execute(
            "DELETE FROM lessons WHERE group_id = ? AND date = ? AND subject = ?"
            " AND kind = ? AND source = ?",
            (group["id"], day_iso, subject, kind, SOURCE_MANUAL),
        )
        conn.execute(
            "INSERT INTO lessons (group_id, date, time_start, time_end, subject, kind,"
            " room, teacher, source, cancelled) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                group["id"], day_iso, row["time_start"], row["time_end"],
                subject, kind, row["room"], row["teacher"], SOURCE_MANUAL, row["cancelled"],
            ),
        )
    return group["id"]


def cancel_lesson(conn, executor_id, day, subject, kind):
    return _write_manual(conn, executor_id, day, subject, kind, cancelled=1)


def reschedule_lesson(conn, executor_id, day, subject, kind, new_start, new_end):
    return _write_manual(
        conn, executor_id, day, subject, kind,
        time_start=new_start.astimezone(timezone.utc).isoformat(),
        time_end=new_end.astimezone(timezone.utc).isoformat(),
    )


def change_room(conn, executor_id, day, subject, kind, new_room):
    return _write_manual(conn, executor_id, day, subject, kind, room=new_room)


def _add_subscriber(conn, tg_user_id, group_id):
    now = timeutil.now_utc().isoformat()
    conn.execute(
        "INSERT INTO subscribers (tg_user_id, group_id, reminded_until, announced_until)"
        " VALUES (?, ?, ?, ?)",
        (tg_user_id, group_id, now, now),
    )


def set_remind_minutes(conn, tg_user_id, minutes):
    if not (config.REMIND_MIN_MINUTES <= minutes <= config.REMIND_MAX_MINUTES):
        raise ValueError(
            f"интервал должен быть от {config.REMIND_MIN_MINUTES} до {config.REMIND_MAX_MINUTES} минут"
        )
    with conn:
        cur = conn.execute(
            "UPDATE subscribers SET remind_minutes = ? WHERE tg_user_id = ?",
            (minutes, tg_user_id),
        )
    if cur.rowcount == 0:
        raise NotAMember("пользователь не состоит в группе")


def set_quiet_hours(conn, tg_user_id, start_hhmm, end_hhmm):
    with conn:
        cur = conn.execute(
            "UPDATE subscribers SET quiet_start = ?, quiet_end = ? WHERE tg_user_id = ?",
            (start_hhmm, end_hhmm, tg_user_id),
        )
    if cur.rowcount == 0:
        raise NotAMember("пользователь не состоит в группе")


def other_subscriber_ids(conn, group_id, exclude_id):
    rows = conn.execute(
        "SELECT tg_user_id FROM subscribers WHERE group_id = ? AND tg_user_id <> ?",
        (group_id, exclude_id),
    ).fetchall()
    return [r["tg_user_id"] for r in rows]


def post_announcement(conn, executor_id, text, now=None):
    group = require_headman(conn, executor_id)
    now = now or timeutil.now_utc()
    today = timeutil.to_display(now).date()
    day_start = timeutil.to_utc(today, "00:00").isoformat()
    day_end = timeutil.to_utc(today + timedelta(days=1), "00:00").isoformat()
    count = conn.execute(
        "SELECT COUNT(*) c FROM announcements WHERE group_id = ? AND sent_at >= ? AND sent_at < ?",
        (group["id"], day_start, day_end),
    ).fetchone()["c"]
    if count >= config.ANNOUNCEMENT_DAILY_LIMIT:
        raise AnnouncementLimit(
            f"за сутки можно отправить не более {config.ANNOUNCEMENT_DAILY_LIMIT} объявлений"
        )
    with conn:
        conn.execute(
            "INSERT INTO announcements (group_id, text, sent_at, author_id) VALUES (?,?,?,?)",
            (group["id"], text, now.isoformat(), executor_id),
        )
    return group["id"]


def pop_due_reminders(conn, now):
    out = []
    for s in conn.execute("SELECT * FROM subscribers").fetchall():
        marker = datetime.fromisoformat(s["reminded_until"]) if s["reminded_until"] else now
        remind_min = (
            s["remind_minutes"] if s["remind_minutes"] is not None else config.REMIND_DEFAULT_MINUTES
        )
        for lesson in get_schedule(conn, s["group_id"]):
            if lesson["cancelled"] or now >= lesson["time_start"]:
                continue
            remind_at = lesson["time_start"] - timedelta(minutes=remind_min)
            if marker < remind_at <= now and not timeutil.in_quiet_hours(
                remind_at, s["quiet_start"], s["quiet_end"]
            ):
                out.append({"tg_user_id": s["tg_user_id"], "lesson": lesson})
        conn.execute(
            "UPDATE subscribers SET reminded_until = ? WHERE id = ?", (now.isoformat(), s["id"])
        )
    conn.commit()
    return out


def pop_deliverable_announcements(conn, now):
    out = []
    for s in conn.execute("SELECT * FROM subscribers").fetchall():
        if timeutil.in_quiet_hours(now, s["quiet_start"], s["quiet_end"]):
            continue
        marker = s["announced_until"] if s["announced_until"] else now.isoformat()
        pending = conn.execute(
            "SELECT * FROM announcements WHERE group_id = ? AND sent_at > ? AND sent_at <= ?"
            " ORDER BY sent_at",
            (s["group_id"], marker, now.isoformat()),
        ).fetchall()
        for a in pending:
            out.append({"tg_user_id": s["tg_user_id"], "text": a["text"]})
        if pending:
            conn.execute(
                "UPDATE subscribers SET announced_until = ? WHERE id = ?",
                (pending[-1]["sent_at"], s["id"]),
            )
    conn.commit()
    return out


def transfer_role(conn, executor_id, new_headman_id):
    group = require_headman(conn, executor_id)
    member = conn.execute(
        "SELECT 1 FROM subscribers WHERE tg_user_id = ? AND group_id = ?",
        (new_headman_id, group["id"]),
    ).fetchone()
    if member is None:
        raise NotAMember("нового старосту можно назначить только из подписчиков группы")
    with conn:
        conn.execute("UPDATE groups SET headman_id = ? WHERE id = ?", (new_headman_id, group["id"]))
    return group["id"]


def unsubscribe(conn, tg_user_id):
    group = group_of(conn, tg_user_id)
    if group is None:
        raise NotAMember("пользователь не состоит в группе")
    if group["headman_id"] == tg_user_id:
        others = conn.execute(
            "SELECT COUNT(*) c FROM subscribers WHERE group_id = ? AND tg_user_id <> ?",
            (group["id"], tg_user_id),
        ).fetchone()["c"]
        if others > 0:
            raise HeadmanHasSubscribers("сначала передайте роль старосты другому подписчику")
    with conn:
        conn.execute("DELETE FROM subscribers WHERE tg_user_id = ?", (tg_user_id,))
    return group
