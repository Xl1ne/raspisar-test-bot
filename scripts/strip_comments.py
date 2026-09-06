import io
import re
import subprocess
import sys
import tokenize
from pathlib import Path

KEEP = ("#!", "# -*- coding", "# coding=", "# syntax=", "# escape=")


_BY_SUFFIX = {".py": "py", ".yml": "hash", ".yaml": "hash", ".sh": "hash", ".html": "html", ".htm": "html"}


def kind(name):
    path = Path(name)
    if path.name == "Dockerfile" or path.name.startswith("Dockerfile."):
        return "dockerfile"
    return _BY_SUFFIX.get(path.suffix)


def _line_ending(line):
    return line[len(line.rstrip("\r\n")):]


def strip_py(text):
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return text
    cuts = {}
    for token in tokens:
        if token.type == tokenize.COMMENT and not token.string.startswith(KEEP):
            cuts[token.start[0]] = token.start[1]
    if not cuts:
        return text
    out = []
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        if number not in cuts:
            out.append(line)
            continue
        head = line[: cuts[number]]
        if head.strip():
            out.append(head.rstrip() + _line_ending(line))
    return "".join(out)


def _hash_position(line, inline):
    quote = None
    for index, char in enumerate(line):
        if quote is not None:
            if char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
            continue
        if char == "#":
            if index == 0 or line[:index].strip() == "":
                return index
            if inline and line[index - 1] in " \t":
                return index
    return None


def strip_hash(text, inline):
    out = []
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        position = _hash_position(line, inline)
        if position is None:
            out.append(line)
            continue
        if number == 1 and line.lstrip().startswith(KEEP):
            out.append(line)
            continue
        head = line[:position]
        if head.strip():
            out.append(head.rstrip() + _line_ending(line))
    return "".join(out)


def strip_html(text):
    text = re.sub(r"^[ \t]*<!--.*?-->[ \t]*\r?\n", "", text, flags=re.S | re.M)
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def strip(name, text):
    handler = kind(name)
    if handler == "py":
        return strip_py(text)
    if handler == "hash":
        return strip_hash(text, inline=True)
    if handler == "dockerfile":
        return strip_hash(text, inline=False)
    if handler == "html":
        return strip_html(text)
    return text


def run_filter(name):
    data = sys.stdin.buffer.read()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        sys.stdout.buffer.write(data)
        return 0
    sys.stdout.buffer.write(strip(name, text).encode("utf-8"))
    return 0


def _git(*args):
    return subprocess.run(
        ["git", *args], capture_output=True, check=True
    ).stdout


def check():
    tracked = _git("ls-files", "-z").decode("utf-8").split("\0")
    dirty = []
    for name in tracked:
        if not name or kind(name) is None:
            continue
        try:
            blob = _git("cat-file", "blob", f":{name}")
        except subprocess.CalledProcessError:
            continue
        text = blob.decode("utf-8", errors="replace")
        if strip(name, text) != text:
            dirty.append(name)
    if dirty:
        print("Комментарии найдены в индексе (уйдут в коммит):")
        for name in dirty:
            print(f"  {name}")
        return 1
    print("Комментариев в индексе нет — то, что уйдёт в коммит, чистое.")
    return 0


def main(argv):
    if len(argv) == 3 and argv[1] == "--filter":
        return run_filter(argv[2])
    if len(argv) == 2 and argv[1] == "--check":
        return check()
    print("Использование: strip_comments.py --filter <имя файла> | --check", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
