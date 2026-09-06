import os
import sqlite3
from datetime import date, datetime

from app import config

SOURCE_AUTO = "auto"
SOURCE_MANUAL = "manual"

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
    quiet_end TEXT
);
CREATE TABLE IF NOT EXISTS announcements (
    id INTEGER PRIMARY KEY,
    group_id INTEGER NOT NULL REFERENCES groups(id),
    text TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    author_id INTEGER NOT NULL
);
"""


def connect(path=None):
    db_path = path or config.DB_PATH
    directory = os.path.dirname(db_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn):
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    conn.commit()


def ensure_schema(path=None):
    conn = connect(path)
    try:
        init_db(conn)
    finally:
        conn.close()


def create_group(conn, name, source_url, invite_code, headman_id, calendar_code):
    cur = conn.execute(
        "INSERT INTO groups (name, source_url, invite_code, headman_id, calendar_code)"
        " VALUES (?,?,?,?,?)",
        (name, source_url, invite_code, headman_id, calendar_code),
    )
    conn.commit()
    return cur.lastrowid


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


def get_schedule(conn, group_id):
    rows = conn.execute(
        "SELECT * FROM lessons WHERE group_id = ? ORDER BY time_start", (group_id,)
    ).fetchall()
    return [
        {
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
        for r in rows
    ]
