import hashlib

from icalendar import Calendar, Event

from app import timeutil

_PRODID = "-//Raspisar//Schedule//RU"


def _uid(group, lesson):
    raw = f"{group['calendar_code']}|{lesson['date'].isoformat()}|{lesson['subject']}|{lesson['kind']}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest() + "@raspisar"


def build_ics(group, lessons):
    stamp = timeutil.now_utc()
    cal = Calendar()
    cal.add("prodid", _PRODID)
    cal.add("version", "2.0")
    cal.add("x-wr-calname", group["name"])
    for lesson in lessons:
        event = Event()
        event.add("uid", _uid(group, lesson))
        event.add("dtstamp", stamp)
        event.add("dtstart", lesson["time_start"])
        event.add("dtend", lesson["time_end"])
        summary = f"{lesson['subject']} ({lesson['kind']})" if lesson["kind"] else lesson["subject"]
        if lesson["cancelled"]:
            event.add("status", "CANCELLED")
            summary = "Отменено: " + summary
        event.add("summary", summary)
        if lesson["room"]:
            event.add("location", lesson["room"])
        if lesson["teacher"]:
            event.add("description", f"Преподаватель: {lesson['teacher']}")
        cal.add_component(event)
    return cal.to_ical()
