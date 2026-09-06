from app import storage
from app.ical import build_ics


def render_calendar(conn, code):
    group = storage.find_group_by_calendar_code(conn, code)
    if group is None:
        raise LookupError(code)
    return build_ics(group, storage.get_schedule(conn, group["id"]))
