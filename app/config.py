import os
from datetime import date

TZ_DISPLAY = os.getenv("RASPISAR_TZ", "Europe/Moscow")

STUDY_START = date.fromisoformat(os.getenv("RASPISAR_STUDY_START", "2026-09-01"))
SEMESTER_END = date.fromisoformat(os.getenv("RASPISAR_SEMESTER_END", "2026-12-27"))

COLLECT_HOUR = int(os.getenv("RASPISAR_COLLECT_HOUR", "3"))
FETCH_TIMEOUT = int(os.getenv("RASPISAR_FETCH_TIMEOUT", "15"))

DB_PATH = os.getenv("RASPISAR_DB", "data/raspisar.db")

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
