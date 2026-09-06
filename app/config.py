import os
from datetime import date

TZ_DISPLAY = os.getenv("RASPISAR_TZ", "Europe/Moscow")

STUDY_START = date.fromisoformat(os.getenv("RASPISAR_STUDY_START", "2026-09-01"))
SEMESTER_END = date.fromisoformat(os.getenv("RASPISAR_SEMESTER_END", "2026-12-27"))

COLLECT_HOUR = int(os.getenv("RASPISAR_COLLECT_HOUR", "3"))
FETCH_TIMEOUT = int(os.getenv("RASPISAR_FETCH_TIMEOUT", "15"))

DB_PATH = os.getenv("RASPISAR_DB", "data/raspisar.db")

PUBLIC_BASE_URL = os.getenv("RASPISAR_PUBLIC_URL", "http://localhost:8000").rstrip("/")

REMIND_DEFAULT_MINUTES = int(os.getenv("RASPISAR_REMIND_DEFAULT", "60"))
REMIND_MIN_MINUTES = int(os.getenv("RASPISAR_REMIND_MIN", "5"))
REMIND_MAX_MINUTES = int(os.getenv("RASPISAR_REMIND_MAX", "180"))

ANNOUNCEMENT_DAILY_LIMIT = int(os.getenv("RASPISAR_ANNOUNCE_LIMIT", "5"))

DISPATCH_INTERVAL_SECONDS = int(os.getenv("RASPISAR_DISPATCH_INTERVAL", "60"))

EDIT_HORIZON_DAYS = int(os.getenv("RASPISAR_EDIT_HORIZON_DAYS", "30"))

BACKUP_HOUR = int(os.getenv("RASPISAR_BACKUP_HOUR", "4"))
BACKUP_DIR = os.getenv("RASPISAR_BACKUP_DIR", "data/backups")
BACKUP_KEEP = int(os.getenv("RASPISAR_BACKUP_KEEP", "7"))

BELL = {
    1: ("08:20", "09:40"),
    2: ("09:50", "11:10"),
    3: ("11:50", "13:10"),
    4: ("13:20", "14:40"),
    5: ("15:00", "16:20"),
    6: ("16:30", "17:50"),
    7: ("18:00", "19:20"),
    8: ("19:30", "20:50"),
}
