"""Chemins et persistance des réglages de l'application."""
import json
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
SERVERS_DIR = APP_DIR / "servers"
RUNTIMES_DIR = APP_DIR / "runtimes"
SETTINGS_FILE = DATA_DIR / "settings.json"

DEFAULT_SETTINGS = {
    "ai_provider": "gemini",            # "gemini" | "ollama"
    "gemini_api_key": "",
    "gemini_model": "gemini-2.5-flash",
    "ollama_url": "http://localhost:11434",
    "ollama_model": "llama3.1",
    "java_path": "",                    # vide = détection/auto-téléchargement
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
