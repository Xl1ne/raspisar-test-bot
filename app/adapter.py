import re
import urllib.request
from dataclasses import dataclass

from bs4 import BeautifulSoup

from app import config, timeutil


class CollectError(Exception):
    pass


_DAYS = {
    "ПОНЕДЕЛЬНИК": 0,
    "ВТОРНИК": 1,
    "СРЕДА": 2,
    "ЧЕТВЕРГ": 3,
    "ПЯТНИЦА": 4,
    "СУББОТА": 5,
    "ВОСКРЕСЕНЬЕ": 6,
}
_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8}
_STREAM_PREFIX = re.compile(r"^П:\d+/")
_KIND = re.compile(r"\(([^)]+)\)\s*$")

GROUP_COLUMNS = 6
PAIR_CELL_OFFSET = GROUP_COLUMNS + 1
DAY_ROW_CELLS = GROUP_COLUMNS + 2


@dataclass(frozen=True)
class TemplateRow:
    weekday: int
    pair: int
    parity: str
    subject: str
    teacher: str
    room: str
    kind: str


def _compact(text):
    return "".join(text.split())


def _parse_block(text):
    lines = [ln.strip() for ln in text.split("\n")]
    lines = [ln for ln in lines if ln and ln != "\xa0"]
    if len(lines) < 3:
        return None
    subject = _STREAM_PREFIX.sub("", lines[0]).strip()
    teacher = lines[1]
    roomtype = lines[2].replace("\xa0", " ")
    match = _KIND.search(roomtype)
    if match:
        kind = match.group(1)
        room = roomtype[: match.start()].strip()
    else:
        kind = ""
        room = roomtype.strip()
    return {"subject": subject, "teacher": teacher, "room": room, "kind": kind}


def _parse_cell(cell, weekday, pair):
    inner = cell.find("table")
    if inner is not None:
        halves = inner.find_all("tr", recursive=False)
        out = []
        for row, parity in zip(halves, (timeutil.ODD, timeutil.EVEN)):
            block = _parse_block(row.get_text("\n"))
            if block:
                out.append(TemplateRow(weekday, pair, parity, **block))
        return out
    block = _parse_block(cell.get_text("\n"))
    if block:
        return [TemplateRow(weekday, pair, timeutil.BOTH, **block)]
    return []


def parse(html, group_code):
    soup = BeautifulSoup(html, "html.parser")

    header_cell = None
    for td in soup.find_all("td"):
        if group_code in td.get_text():
            header_cell = td
            break
    if header_cell is None:
        return []

    header_row = header_cell.find_parent("tr")
    grid = header_row.find_parent("table")
    group_headers = header_row.find_all("td", recursive=False)[1:]
    col = next((i for i, h in enumerate(group_headers) if group_code in h.get_text()), None)
    if col is None or grid is None:
        return []

    rows = []
    weekday = None
    for row in grid.find_all("tr", recursive=False):
        if row is header_row:
            continue
        cells = row.find_all("td", recursive=False)
        if len(cells) < PAIR_CELL_OFFSET:
            continue
        if len(cells) == DAY_ROW_CELLS:
            weekday = _DAYS.get(_compact(cells[0].get_text()))
        pair = _ROMAN.get(cells[-PAIR_CELL_OFFSET].get_text().strip())
        if weekday is None or pair is None:
            continue
        rows.extend(_parse_cell(cells[-GROUP_COLUMNS:][col], weekday, pair))
    return rows


def fetch(url):
    try:
        with urllib.request.urlopen(url, timeout=config.FETCH_TIMEOUT) as resp:
            return resp.read()
    except OSError as exc:
        raise CollectError(f"источник недоступен: {exc}") from exc


def collect(url, group_code):
    raw = fetch(url)
    try:
        rows = parse(raw, group_code)
    except Exception as exc:
        raise CollectError(f"страница не разобрана: {exc}") from exc
    if not rows:
        raise CollectError("расписание не разобрано: ноль занятий")
    return timeutil.expand(rows, config.STUDY_START, config.SEMESTER_END)
