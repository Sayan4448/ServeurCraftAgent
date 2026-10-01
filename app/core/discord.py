"""Notifications Discord par webhook.

Optionnel : rien n'est envoyé tant qu'aucun webhook n'est renseigné dans
⚙ Paramètres. Les envois passent par une file et un thread dédié (jamais
bloquant pour la console ni pour l'UI) ; les mentions sont désactivées.
"""
import queue
import re
import threading
import time
from datetime import datetime, timezone

import requests

from ..config import load_settings
from ..i18n import t

EVENTS = ("started", "stopped", "crashed", "join", "leave")
_COLORS = {"started": 0x22C55E, "stopped": 0x64748B, "crashed": 0xEF4444,
           "join": 0x3B82F6, "leave": 0xF59E0B, "test": 0x3B82F6}
_URL = re.compile(r"^https://(?:(?:ptb|canary)\.)?discord(?:app)?\.com"
                  r"/api/webhooks/\d+/[\w-]+/?$")
_q: "queue.Queue" = queue.Queue()
_worker = None
_worker_lock = threading.Lock()


def valid_url(url: str) -> bool:
    return bool(_URL.match((url or "").strip()))


def event_enabled(settings: dict, event: str) -> bool:
    return bool((settings.get("discord_events") or {}).get(event, True))


def notify(event: str, server: str, player: str = "", code=None,
           detail: str = "") -> None:
    """Met en file une notification (thread-safe, non bloquant)."""
    s = load_settings()
    url = (s.get("discord_webhook") or "").strip()
    if not valid_url(url) or not event_enabled(s, event):
        return
    _q.put((url, _payload(event, server, player, code, detail)))
    _ensure_worker()


def send_test(url: str) -> str | None:
    """Envoi synchrone d'un message de test (depuis un thread).
    Retourne None si OK, sinon le message d'erreur."""
    if not valid_url(url):
        return t("dc_bad_url")
    return _post(url.strip(), _payload("test", "", "", None, ""))


def _payload(event, server, player, code, detail) -> dict:
    title = t(f"dc_{event}" if event != "test" else "dc_test_msg",
              server=server, player=player, code=code)
    embed = {"title": title[:256], "color": _COLORS.get(event, 0x3B82F6),
             "footer": {"text": "ServerCraft Agent"},
             "timestamp": datetime.now(timezone.utc).isoformat()}
    if detail:
        embed["description"] = f"```\n{detail[-1800:]}\n```"
    return {"username": "ServerCraft Agent", "embeds": [embed],
            "allowed_mentions": {"parse": []}}


def _post(url: str, payload: dict) -> str | None:
    for _ in range(3):
        try:
            r = requests.post(url, json=payload, timeout=10)
        except requests.RequestException as e:
            return str(e)
        if r.status_code == 429:          # limite de débit Discord
            try:
                wait = float(r.json().get("retry_after", 1))
            except (ValueError, TypeError, AttributeError):
                wait = 1.0            # corps inattendu (proxy, HTML…)
            time.sleep(max(0.0, min(wait, 10)))
            continue
        return None if r.ok else f"HTTP {r.status_code}"
    return "HTTP 429"


def _run() -> None:
    while True:
        url, payload = _q.get()
        try:
            _post(url, payload)
        except Exception:  # noqa: BLE001 — le thread d'envoi ne meurt pas
            pass


def _ensure_worker() -> None:
    global _worker
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run, daemon=True,
                                       name="discord")
            _worker.start()
