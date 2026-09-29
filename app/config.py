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
BACKUPS_DIR = APP_DIR / "backups"
SETTINGS_FILE = DATA_DIR / "settings.json"

DEFAULT_SETTINGS = {
    "curseforge_api_key": "",           # console.curseforge.com (gratuit)
    "java_path": "",                    # vide = détection/auto-téléchargement
    "language": "fr",                   # fr | en | ru | ja | es | de
    "theme": "dark",                    # "dark" | "light"
    "server_interface": True,           # fenêtre d'administration au lancement
    "monitoring": True,
    "discord_webhook": "",              # vide = aucune notification envoyée
    "discord_events": {"started": True, "stopped": True, "crashed": True,
                       "join": True, "leave": True},
    "ai_beta": False,                   # onglet « Agent IA » (early access)
    # — paramètres de l'Agent IA (bêta) —
    "ai_provider": "gemini",
    "gemini_api_key": "",
    "gemini_model": "gemini-2.5-flash",
    "anthropic_api_key": "",
    "anthropic_model": "claude-sonnet-4-5",
    "openai_api_key": "",
    "openai_base": "https://api.openai.com/v1",
    "openai_model": "gpt-4o-mini",
    "ollama_url": "http://localhost:11434",
    "ollama_model": "llama3.1",
    "lmstudio_url": "http://localhost:1234/v1",
    "lmstudio_model": "",
    "custom_base": "",
    "custom_key": "",
    "custom_model": "",
    "auto_mod_enabled": False,
    "auto_mod_rules": "Aucune insulte, aucun spam, respect entre joueurs.",
}


def ensure_dirs() -> None:
    for d in (DATA_DIR, SERVERS_DIR, RUNTIMES_DIR, BACKUPS_DIR):
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
