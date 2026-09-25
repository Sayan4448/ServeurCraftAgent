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
    "ai_provider": "gemini",            # clé dans ai.providers.PROVIDERS
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
    "curseforge_api_key": "",           # console.curseforge.com (gratuit)
    "auto_mod_enabled": False,          # modération autonome du chat par l'IA
    "auto_mod_rules": "Aucune insulte, aucun spam, respect entre joueurs.",
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
