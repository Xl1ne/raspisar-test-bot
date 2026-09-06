from pathlib import Path

from app.adapter import parse

FIXTURE = (Path(__file__).parent / "fixtures" / "raspisanie.html").read_text(encoding="utf-8")
GROUP = "ОБ-09.03.03.02-41"


def _find(lessons, wd, pair, parity):
    hits = [l for l in lessons if l.weekday == wd and l.pair == pair and l.parity == parity]
    assert len(hits) == 1, f"ожидалась одна пара ({wd},{pair},{parity}), нашлось {len(hits)}"
    return hits[0]


def test_full_cell_both_weeks_and_stream_prefix_stripped():
    lessons = parse(FIXTURE, GROUP)
    l = _find(lessons, 0, 4, "both")
    assert l.subject == "Мат. прогр."
    assert l.teacher == "Родионов В.И."
    assert l.room == "421/6к"
    assert l.kind == "Лек"


def test_numerator_only_lesson():
    lessons = parse(FIXTURE, GROUP)
    l = _find(lessons, 0, 5, "odd")
    assert l.subject == "МОиИО"
    assert l.kind == "Прак"
    assert not [x for x in lessons if x.weekday == 0 and x.pair == 5 and x.parity == "even"]


def test_split_cell_numerator_and_denominator():
    lessons = parse(FIXTURE, GROUP)
    num = _find(lessons, 1, 4, "odd")
    den = _find(lessons, 1, 4, "even")
    assert num.subject == "НиН" and num.kind == "Лек" and num.room == ""
    assert den.subject == "НиН" and den.kind == "Прак" and den.room == ""
    assert num.teacher == "Щербакова И.Г."


def test_wednesday_numerator_is_lecture_denominator_is_lab():
    lessons = parse(FIXTURE, GROUP)
    assert _find(lessons, 2, 4, "odd").kind == "Лек"
    assert _find(lessons, 2, 4, "even").kind == "Лаб"


def test_saturday_stream_denominator_only():
    lessons = parse(FIXTURE, GROUP)
    l = _find(lessons, 5, 2, "even")
    assert l.subject == "ИБ"
    assert l.teacher == "Трусов А.С."
    assert not [x for x in lessons if x.weekday == 5 and x.pair == 2 and x.parity == "odd"]


def test_unknown_group_yields_nothing():
    assert parse(FIXTURE, "ОБ-99.99.99.99-99") == []


import urllib.error

import pytest

from app import adapter
from app.adapter import CollectError, collect, fetch


def test_fetch_network_error_is_collect_error(monkeypatch):
    def boom(url, timeout):
        raise urllib.error.URLError("сеть недоступна")
    monkeypatch.setattr(adapter.urllib.request, "urlopen", boom)
    with pytest.raises(CollectError):
        fetch("http://source/")


def test_fetch_http_error_is_collect_error(monkeypatch):
    def boom(url, timeout):
        raise urllib.error.HTTPError(url, 500, "ошибка сервера", None, None)
    monkeypatch.setattr(adapter.urllib.request, "urlopen", boom)
    with pytest.raises(CollectError):
        fetch("http://source/")


def test_collect_empty_page_is_collect_error(monkeypatch):
    monkeypatch.setattr(adapter, "fetch", lambda url: b"")
    with pytest.raises(CollectError):
        collect("http://source/", GROUP)


def test_collect_foreign_layout_is_collect_error(monkeypatch):
    foreign = "<html><body><table><tr><td>" + GROUP + "</td></tr></table></body></html>"
    monkeypatch.setattr(adapter, "fetch", lambda url: foreign.encode("utf-8"))
    with pytest.raises(CollectError):
        collect("http://source/", GROUP)


def test_collect_accepts_bytes_and_expands(monkeypatch):
    monkeypatch.setattr(adapter, "fetch", lambda url: FIXTURE.encode("utf-8"))
    occurrences = collect("http://source/", GROUP)
    assert len(occurrences) > 100
    assert {"date", "time_start", "time_end", "subject", "kind", "room", "teacher"} <= set(occurrences[0])
