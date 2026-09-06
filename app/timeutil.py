from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app import config

_MSK = ZoneInfo(config.TZ_DISPLAY)

ODD = "odd"
EVEN = "even"
BOTH = "both"


def _monday(day):
    return day - timedelta(days=day.weekday())


def is_odd_week(day, study_start):
    weeks = (_monday(day) - _monday(study_start)).days // 7
    return weeks % 2 == 0


def now_utc():
    return datetime.now(tz=timezone.utc)


def today_msk():
    return datetime.now(tz=_MSK).date()


def week_bounds(day):
    monday = _monday(day)
    return monday, monday + timedelta(days=6)


def parse_hhmm(hhmm):
    hour, minute = (int(part) for part in hhmm.split(":"))
    return time(hour, minute)


def to_utc(day, hhmm):
    local = datetime.combine(day, parse_hhmm(hhmm), tzinfo=_MSK)
    return local.astimezone(timezone.utc)


def to_display(moment):
    return moment.astimezone(_MSK)


def in_quiet_hours(moment, start_hhmm, end_hhmm):
    if not start_hhmm or not end_hhmm:
        return False
    local = to_display(moment).time()
    start = parse_hhmm(start_hhmm)
    end = parse_hhmm(end_hhmm)
    if start <= end:
        return start <= local < end
    return local >= start or local < end


def expand(rows, study_start, semester_end):
    out = []
    day = study_start
    while day <= semester_end:
        odd = is_odd_week(day, study_start)
        for row in rows:
            if row.weekday != day.weekday():
                continue
            if row.parity == ODD and not odd:
                continue
            if row.parity == EVEN and odd:
                continue
            start_hhmm, end_hhmm = config.BELL[row.pair]
            out.append(
                {
                    "date": day,
                    "time_start": to_utc(day, start_hhmm),
                    "time_end": to_utc(day, end_hhmm),
                    "subject": row.subject,
                    "kind": row.kind,
                    "room": row.room,
                    "teacher": row.teacher,
                }
            )
        day += timedelta(days=1)
    return out


def seconds_until_hour(hour):
    now = datetime.now(tz=_MSK)
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()
