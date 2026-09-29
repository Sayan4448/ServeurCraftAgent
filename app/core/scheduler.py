"""Tâches de fond des serveurs lancés (thread unique, aucun appel Tk).

- sauvegarde automatique toutes les `backup_interval_min` minutes
- redémarrage quotidien à `restart_time` (HH:MM), annoncé en jeu 5 min,
  1 min et 10 s avant
- commandes planifiées `scheduled_commands` :
  {"cmd": "say …", "mode": "every" | "at", "value": "30" | "HH:MM"}
"""
import re
import threading
import time
from datetime import datetime, timedelta

from ..i18n import t
from . import backups as backups_mod
from . import server_manager as sm

TICK = 1.0
# (secondes avant le redémarrage, message annoncé en jeu)
RESTART_WARNINGS = ((300, "sch_warn_5m"), (60, "sch_warn_1m"),
                    (10, "sch_warn_10s"))
_GRACE = 5            # annonce ignorée si son heure est passée de plus de 5 s
_MIN_UPTIME = 120     # pas de redémarrage planifié juste après un démarrage
_HHMM = re.compile(r"^\s*([01]?\d|2[0-3])[:hH]([0-5]\d)\s*$")
_started = False


def start() -> None:
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, daemon=True, name="scheduler").start()


# ================================================================ validation

def parse_hhmm(value):
    """'4:05' / '04h05' -> (4, 5) ; None si invalide ou vide."""
    m = _HHMM.match(str(value or ""))
    return (int(m.group(1)), int(m.group(2))) if m else None


def fmt_hhmm(hm) -> str:
    return f"{hm[0]:02d}:{hm[1]:02d}"


def clean_tasks(tasks) -> list:
    """Normalise la liste des commandes planifiées. Lève ValueError (message
    traduit) sur une ligne invalide ; ignore les lignes sans commande."""
    out = []
    for task in tasks or []:
        cmd = str(task.get("cmd", "")).strip().lstrip("/").strip()
        if not cmd:
            continue
        mode = task.get("mode", "every")
        value = str(task.get("value", "")).strip()
        if mode == "at":
            hm = parse_hhmm(value)
            if not hm:
                raise ValueError(t("sch_bad_time", v=value))
            value = fmt_hhmm(hm)
        else:
            mode = "every"
            try:
                minutes = float(value.replace(",", "."))
            except ValueError:
                minutes = 0
            if minutes <= 0:
                raise ValueError(t("sch_bad_every", v=value))
            value = f"{minutes:g}"
        out.append({"cmd": cmd, "mode": mode, "value": value})
    return out


# ================================================================ boucle

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


def _state(proc) -> dict:
    """État du planificateur propre à une exécution du serveur."""
    st = getattr(proc, "_sched", None)
    if st is None or st["run"] != proc.started_at:
        st = proc._sched = {"run": proc.started_at, "restart_key": None,
                            "restart_at": 0.0, "warned": set(),
                            "cmd_last": {}, "cmd_day": {}}
    return st


def _tick(proc, now: float) -> None:
    if not (proc.is_running() and proc.ready) or proc.stop_requested:
        return
    st = _state(proc)
    _auto_backup(proc, now)
    _daily_restart(proc, st, now)
    if not proc.stop_requested:
        _commands(proc, st, now)


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


def _next_at(hm, after: float) -> float:
    base = datetime.fromtimestamp(after)
    target = base.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
    if target.timestamp() <= after:
        target += timedelta(days=1)
    return target.timestamp()


def _daily_restart(proc, st: dict, now: float) -> None:
    hm = parse_hhmm(proc.meta.get("restart_time"))
    if not hm:
        st["restart_key"] = None
        return
    if st["restart_key"] != hm:
        st.update(restart_key=hm, restart_at=_next_at(hm, now),
                  warned=set())
    left = st["restart_at"] - now
    for secs, key in RESTART_WARNINGS:
        if left <= secs and secs not in st["warned"]:
            st["warned"].add(secs)
            if left > secs - _GRACE:
                proc.send(f"say {t(key)}")
    if left <= 0:
        st.update(restart_at=_next_at(hm, now + 60), warned=set())
        if now - proc.started_at >= _MIN_UPTIME:
            proc.log(t("sch_restarting", time=fmt_hhmm(hm)))
            proc.restart()


def _commands(proc, st: dict, now: float) -> None:
    tasks = proc.meta.get("scheduled_commands") or []
    today = time.strftime("%Y-%m-%d", time.localtime(now))
    hhmm = time.strftime("%H:%M", time.localtime(now))
    for i, task in enumerate(tasks):
        cmd = str(task.get("cmd", "")).strip().lstrip("/")
        if not cmd:
            continue
        key = (i, cmd, task.get("mode"), task.get("value"))
        if task.get("mode") == "at":
            hm = parse_hhmm(task.get("value"))
            if not hm or fmt_hhmm(hm) != hhmm or \
                    st["cmd_day"].get(key) == today:
                continue
            st["cmd_day"][key] = today
        else:
            try:
                every = float(str(task.get("value")).replace(",", ".")) * 60
            except (TypeError, ValueError):
                continue
            if every <= 0:
                continue
            last = st["cmd_last"].setdefault(key, now)
            if now - last < every:
                continue
            st["cmd_last"][key] = now
        proc.log(t("sch_cmd_log", cmd=cmd))
        proc.send(cmd)
