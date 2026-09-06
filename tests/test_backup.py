import sqlite3

from app import config, storage
from app.scheduler import backup_once


def _isolate(tmp_path, monkeypatch, keep=7):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "live.db"))
    monkeypatch.setattr(config, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(config, "BACKUP_KEEP", keep)
    storage.ensure_schema()


def test_backup_creates_restorable_copy(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    storage.run(storage.register_group, 1, "ГР", "http://s/")
    target = backup_once()
    copy = sqlite3.connect(target)
    try:
        assert copy.execute("SELECT COUNT(*) FROM groups").fetchone()[0] == 1
    finally:
        copy.close()


def test_backup_rotation_keeps_last_n(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch, keep=2)
    (tmp_path / "backups").mkdir()
    for stamp in ("20260101", "20260102"):
        (tmp_path / "backups" / f"raspisar-{stamp}.db").write_bytes(b"")
    backup_once()
    names = sorted(p.name for p in (tmp_path / "backups").iterdir())
    assert len(names) == 2
    assert "raspisar-20260101.db" not in names
