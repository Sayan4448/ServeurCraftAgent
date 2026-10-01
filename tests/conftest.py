"""Isolation des tests : aucune lecture/écriture dans les vraies données.

`app.config` calcule ses chemins à l'import et les autres modules les
importent par nom : chaque copie est redirigée vers un dossier temporaire.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.core import backups, item_icons, java, playit  # noqa: E402
from app.core import server_manager as sm  # noqa: E402


@pytest.fixture(autouse=True)
def app_dirs(tmp_path, monkeypatch):
    """Redirige servers/, data/, runtimes/ et backups/ vers tmp_path."""
    dirs = {name: tmp_path / name
            for name in ("data", "servers", "runtimes", "backups")}
    for d in dirs.values():
        d.mkdir()
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "DATA_DIR", dirs["data"])
    monkeypatch.setattr(config, "SERVERS_DIR", dirs["servers"])
    monkeypatch.setattr(config, "RUNTIMES_DIR", dirs["runtimes"])
    monkeypatch.setattr(config, "BACKUPS_DIR", dirs["backups"])
    monkeypatch.setattr(config, "SETTINGS_FILE",
                        dirs["data"] / "settings.json")
    monkeypatch.setattr(sm, "SERVERS_DIR", dirs["servers"])
    monkeypatch.setattr(backups, "BACKUPS_DIR", dirs["backups"])
    monkeypatch.setattr(java, "RUNTIMES_DIR", dirs["runtimes"])
    monkeypatch.setattr(item_icons, "RUNTIMES_DIR", dirs["runtimes"])
    monkeypatch.setattr(playit, "DATA_DIR", dirs["data"])
    monkeypatch.setattr(playit, "RUNTIMES_DIR", dirs["runtimes"])
    monkeypatch.setattr(playit, "SECRET_FILE", dirs["data"] / "playit.toml")
    monkeypatch.setattr(sm, "PROCESSES", {})
    return dirs


@pytest.fixture
def make_server(app_dirs):
    """Crée un dossier serveur minimal (servercraft.json) et le retourne."""
    def _make(name="test", **meta):
        path = app_dirs["servers"] / name
        path.mkdir(parents=True, exist_ok=True)
        data = {"name": name, "loader": "paper", "mc_version": "1.21.4",
                "ram_mb": 2048, "port": 25565, "accounts": "both"}
        data.update(meta)
        (path / sm.META_FILE).write_text(json.dumps(data), encoding="utf-8")
        return path
    return _make


class FakePopen:
    """Process Java simulé : sorties scriptées, entrées enregistrées."""

    def __init__(self):
        self.pid = 4242
        self.sent = []
        self.returncode = None
        self.stdin = self

    # stdin
    def write(self, text):
        self.sent.append(text)

    def flush(self):
        pass

    # process
    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


@pytest.fixture
def running_proc(make_server):
    """ServerProcess « lancé » adossé à un FakePopen (aucun Java)."""
    def _make(name="test", **meta):
        make_server(name, **meta)
        proc = sm.get_process(name)
        proc.proc = FakePopen()
        proc.ready = True
        return proc
    return _make
