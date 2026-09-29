"""Sauvegardes des mondes : zip horodaté, rotation, restauration.

Emplacement : `backups/<serveur>/AAAA-MM-JJ_HH-MM-SS_<raison>.zip`, hors du
dossier serveur (une restauration ou une suppression du serveur ne touche
pas aux sauvegardes).

Serveur lancé : `save-off`, `save-all flush` (on attend « Saved the game »),
zip, puis `save-on` — le monde n'est pas modifié pendant la copie.

Rotation : seules les sauvegardes automatiques (intervalle, avant arrêt,
avant redémarrage, avant restauration) sont supprimées au-delà de `keep` ;
les sauvegardes manuelles sont conservées.
"""
import re
import shutil
import threading
import time
import zipfile
from pathlib import Path, PurePosixPath

from ..config import BACKUPS_DIR
from ..i18n import t
from .properties import load_properties

DEFAULT_KEEP = 10
REASONS = ("manual", "auto", "stop", "restart", "restore")
_ROTATED = ("auto", "stop", "restart", "restore")
_SKIP = {"session.lock"}
_SAVED = re.compile(r"Saved the (game|world)")
_NAME = re.compile(r"^(\d{4}-\d\d-\d\d)_(\d\d)-(\d\d)-(\d\d)(?:-\d+)?_(\w+)\.zip$")
_locks: dict = {}


class BackupError(Exception):
    pass


def backup_dir(name: str) -> Path:
    return BACKUPS_DIR / name


def world_dirs(server_path: Path) -> list:
    """Dossiers du monde : <level>, <level>_nether, <level>_the_end
    (Paper/Purpur les séparent ; Fabric/Forge rangent tout dans <level>)."""
    server_path = Path(server_path)
    level = load_properties(server_path / "server.properties").get(
        "level-name") or "world"
    return [server_path / n for n in (level, f"{level}_nether",
                                      f"{level}_the_end")
            if (server_path / n).is_dir()]


def busy(name: str) -> bool:
    lock = _locks.get(name)
    return bool(lock and lock.locked())


def fmt_size(n: int) -> str:
    for unit in ("o", "Ko", "Mo", "Go"):
        if n < 1024 or unit == "Go":
            return f"{n:.0f} {unit}" if unit == "o" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} Go"


def reason_label(reason: str) -> str:
    return t(f"bk_r_{reason}") if reason in REASONS else t("bk_r_other")


# ================================================================ liste

def list_backups(name: str) -> list:
    """Sauvegardes du serveur, plus récentes d'abord :
    {path, file, date, reason, size, ts}."""
    d = backup_dir(name)
    if not d.is_dir():
        return []
    out = []
    for f in d.glob("*.zip"):
        try:
            st = f.stat()
        except OSError:
            continue
        m = _NAME.match(f.name)
        if m:
            date = f"{m.group(1)} {m.group(2)}:{m.group(3)}:{m.group(4)}"
            reason = m.group(5)
        else:
            date = time.strftime("%Y-%m-%d %H:%M:%S",
                                 time.localtime(st.st_mtime))
            reason = "other"
        out.append({"path": f, "file": f.name, "date": date,
                    "reason": reason, "size": st.st_size,
                    "ts": st.st_mtime})
    out.sort(key=lambda b: (b["date"], b["ts"]), reverse=True)
    return out


def rotate(name: str, keep: int) -> int:
    """Supprime les sauvegardes automatiques au-delà des `keep` plus
    récentes. Retourne le nombre de fichiers supprimés."""
    keep = max(1, int(keep))
    auto = [b for b in list_backups(name) if b["reason"] in _ROTATED]
    n = 0
    for b in auto[keep:]:
        try:
            b["path"].unlink()
            n += 1
        except OSError:
            pass
    return n


def delete(path: Path) -> None:
    Path(path).unlink(missing_ok=True)


# ================================================================ création

def _wait_line(proc, pattern, seen: int, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        lines, seen = proc.lines_since(seen)
        if any(pattern.search(line) for line in lines):
            return True
        if not proc.is_running():
            return False
        time.sleep(0.25)
    return False


def _zip(name: str, server_path: Path, dirs: list, reason: str) -> Path:
    dest = backup_dir(name)
    dest.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    final = dest / f"{stamp}_{reason}.zip"
    i = 1
    while final.exists():
        final = dest / f"{stamp}-{i}_{reason}.zip"
        i += 1
    tmp = final.with_name(final.name + ".part")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED,
                             compresslevel=6) as z:
            for d in dirs:
                for f in sorted(d.rglob("*")):
                    if not f.is_file() or f.name in _SKIP:
                        continue
                    try:
                        z.write(f, f.relative_to(server_path).as_posix())
                    except OSError:
                        pass          # fichier verrouillé par Java
        tmp.replace(final)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return final


def create(name: str, server_path: Path, reason: str = "manual",
           keep: int = DEFAULT_KEEP, proc=None, log=print) -> Path:
    """Zippe le monde. `proc` (ServerProcess) : si le serveur tourne, la
    sauvegarde passe par save-off / save-all flush / save-on."""
    server_path = Path(server_path)
    lock = _locks.setdefault(name, threading.Lock())
    if not lock.acquire(blocking=False):
        raise BackupError(t("bk_busy"))
    try:
        dirs = world_dirs(server_path)
        if not dirs:
            raise BackupError(t("bk_no_world"))
        log(t("bk_console_start", reason=reason_label(reason)))
        t0 = time.time()
        live = proc is not None and proc.is_running() and proc.ready
        if live:
            proc.hide_saves_until = float("inf")
            proc.send("save-off")
            seen = proc.seq
            proc.send("save-all flush")
            _wait_line(proc, _SAVED, seen, timeout=60)
        try:
            path = _zip(name, server_path, dirs, reason)
        finally:
            if live:
                proc.send("save-on")
                proc.hide_saves_until = time.time() + 5
        rotate(name, keep)
        log(t("bk_console_done", file=path.name,
              size=fmt_size(path.stat().st_size),
              sec=f"{time.time() - t0:.0f}"))
        return path
    finally:
        lock.release()


# ================================================================ restauration

def _safe(rel: str) -> bool:
    parts = PurePosixPath(rel).parts
    return bool(parts) and ".." not in parts and not rel.startswith("/") \
        and ":" not in rel


def restore(name: str, server_path: Path, zip_path: Path,
            keep: int = DEFAULT_KEEP, log=print) -> None:
    """Remplace le monde par le contenu du zip (serveur arrêté). Le monde
    actuel est d'abord sauvegardé (raison « restore »)."""
    server_path = Path(server_path)
    with zipfile.ZipFile(zip_path) as z:
        members = [m for m in z.namelist() if _safe(m)]
        tops = {PurePosixPath(m).parts[0] for m in members}
        if not tops:
            raise BackupError(t("bk_no_world"))
        if world_dirs(server_path):
            create(name, server_path, "restore", keep=keep, log=log)
        for top in tops:
            target = server_path / top
            if target.is_dir():
                shutil.rmtree(target)
        for m in members:
            if m.endswith("/"):
                continue
            out = server_path / m
            out.parent.mkdir(parents=True, exist_ok=True)
            with z.open(m) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)
