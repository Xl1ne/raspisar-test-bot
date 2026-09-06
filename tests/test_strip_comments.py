import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from strip_comments import strip


def test_python_inline_and_whole_line():
    source = "#!/usr/bin/env python3\n# заголовок\nx = 1  # хвост\ny = 2\n"
    assert strip("a.py", source) == "#!/usr/bin/env python3\nx = 1\ny = 2\n"


def test_python_keeps_hash_inside_string_and_docstring():
    source = 'def f():\n    """Документация."""\n    return "#не комментарий"\n'
    assert strip("a.py", source) == source


def test_python_broken_syntax_returns_source_untouched():
    source = "def f(:\n    pass  # хвост\n"
    assert strip("a.py", source) == source


def test_yaml_inline_and_quoted():
    source = 'services:\n  # комментарий\n  name: "a#b"\n  port: 8000 # хвост\n'
    assert strip("c.yml", source) == 'services:\n  name: "a#b"\n  port: 8000\n'


def test_dockerfile_keeps_directive_and_inline_shell():
    source = "# syntax=docker/dockerfile:1\n# комментарий\nRUN echo 1 # не трогаем\n"
    assert strip("Dockerfile", source) == "# syntax=docker/dockerfile:1\nRUN echo 1 # не трогаем\n"


def test_html_comments_removed():
    source = "<p>раз</p>\n<!-- заметка -->\n<p>два</p><!-- хвост -->\n"
    assert strip("i.html", source) == "<p>раз</p>\n<p>два</p>\n"


def test_unknown_extension_untouched():
    source = "# это остаётся\n"
    assert strip("README.md", source) == source
