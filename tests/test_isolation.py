from pathlib import Path

APP = Path(__file__).parent.parent / "app"


def _modules_mentioning(needle):
    hits = []
    for path in APP.glob("*.py"):
        if needle in path.read_text(encoding="utf-8"):
            hits.append(path.name)
    return set(hits)


def test_html_parser_lives_only_in_adapter():
    for needle in ("bs4", "BeautifulSoup"):
        assert _modules_mentioning(needle) <= {"adapter.py"}, needle


def test_timezone_conversion_lives_only_in_timeutil():
    for needle in ("zoneinfo", "ZoneInfo"):
        assert _modules_mentioning(needle) <= {"timeutil.py"}, needle
