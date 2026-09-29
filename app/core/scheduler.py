"""Tâches de fond des serveurs lancés (thread unique, aucun appel Tk).

- sauvegarde automatique toutes les `backup_interval_min` minutes
"""
import threading
import time

from . import backups as backups_mod
from . import server_manager as sm

TICK = 1.0
_started = False


def start() -> None:
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, daemon=True, name="scheduler").start()


def _loop() -> None:
    while True:
        now = time.time()
        for proc in list(sm.PROCESSES.values()):
            try:
                _tick(proc, now)
            except Exception:  # noqa: BLE001 — la boucle ne doit pas mourir
                import traceback
                traceback.print_exc()
        time.sleep(TICK)


def _tick(proc, now: float) -> None:
    if not (proc.is_running() and proc.ready) or proc.stop_requested:
        return
    _auto_backup(proc, now)


def _auto_backup(proc, now: float) -> None:
    try:
        every = float(proc.meta.get("backup_interval_min") or 0)
    except (TypeError, ValueError):
        return
    if every <= 0 or backups_mod.busy(proc.name):
        return
    if now - max(proc.started_at, proc.last_backup) >= every * 60:
        proc.last_backup = now
        threading.Thread(target=proc.backup, args=("auto",),
                         daemon=True).start()
