"""Chemins et persistance des réglages de l'application."""
import json
import os
import sys
from pathlib import Path


def _base_dir() -> Path:
    # Version packagée (exe) : données dans %LOCALAPPDATA%\ServerCraftAgent —
    # Program Files n'est pas accessible en écriture sans admin.
    if getattr(sys, "frozen", False):
        root = os.environ.get("LOCALAPPDATA")
        if root:
            return Path(root) / "ServerCraftAgent"
        return Path.home() / "AppData" / "Local" / "ServerCraftAgent"
    return Path(__file__).resolve().parent.parent


APP_DIR = _base_dir()
DATA_DIR = APP_DIR / "data"
SERVERS_DIR = APP_DIR / "servers"
RUNTIMES_DIR = APP_DIR / "runtimes"
SETTINGS_FILE = DATA_DIR / "settings.json"

DEFAULT_SETTINGS = {
    "curseforge_api_key": "",           # console.curseforge.com (gratuit)
    "java_path": "",                    # vide = détection/auto-téléchargement
    "language": "fr",                   # "fr" | "en"
    "server_interface": True,           # fenêtre d'administration au lancement
}


def ensure_dirs() -> None:
    for d in (DATA_DIR, SERVERS_DIR, RUNTIMES_DIR):
        d.mkdir(parents=True, exist_ok=True)


def load_settings() -> dict:
    ensure_dirs()
    settings = dict(DEFAULT_SETTINGS)
    if SETTINGS_FILE.exists():
        try:
            settings.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    return settings


def save_settings(settings: dict) -> None:
    ensure_dirs()
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")
