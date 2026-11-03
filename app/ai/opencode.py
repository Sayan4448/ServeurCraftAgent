"""OpenCode (opencode.ai, github.com/anomalyco/opencode) : agent IA open source
en ligne de commande, avec des modèles gratuits (OpenCode Zen, sans compte).

- Binaire : `opencode` du PATH (.exe), sinon copie gérée par l'app dans
  runtimes/opencode/, téléchargée depuis les releases GitHub.
- Config : data/opencode/opencode.json (passée par OPENCODE_CONFIG, fusionnée
  avec celle de l'utilisateur) → serveur MCP « servercraft » (mcp_bridge).
- Messages : `opencode run --format json` (une ligne JSON par événement),
  conversation reprise avec `--session <id>`.

Aucun appel Tk ici : fonctions bloquantes, à appeler depuis un thread.
"""
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

from .. import config
from ..core.downloader import download_file

VERSION = "v1.19.5"
# « baseline » : fonctionne aussi sur les processeurs sans AVX2
ASSET = "opencode-windows-x64-baseline.zip"
URL = ("https://github.com/anomalyco/opencode/releases/download/"
       f"{VERSION}/{ASSET}")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
_EXE = "opencode.exe" if os.name == "nt" else "opencode"


class OpenCodeError(Exception):
    pass


def _managed() -> Path:
    return config.RUNTIMES_DIR / "opencode" / VERSION / _EXE


def find_exe() -> Path | None:
    found = shutil.which("opencode")
    # sous Windows, un .cmd (npm) passerait les messages par cmd.exe : & | %
    # y seraient interprétés → seulement un vrai .exe
    if found and (os.name != "nt" or found.lower().endswith(".exe")):
        return Path(found)
    return _managed() if _managed().exists() else None


def ensure_exe(progress=None) -> Path:
    """Chemin d'opencode, téléchargé au besoin. Lève OpenCodeError."""
    from ..i18n import t
    exe = find_exe()
    if exe:
        return exe
    if os.name != "nt":
        raise OpenCodeError(t("oc_err_missing"))
    dest = _managed()
    archive = dest.parent / ASSET
    try:
        download_file(URL, archive, progress)
        with zipfile.ZipFile(archive) as z:
            member = next((n for n in z.namelist()
                           if n.replace("\\", "/").rsplit("/", 1)[-1].lower()
                           == "opencode.exe"), None)
            if not member:
                raise OpenCodeError(t("oc_err_archive"))
            tmp = dest.with_suffix(".part")
            with z.open(member) as src, open(tmp, "wb") as out:
                shutil.copyfileobj(src, out)
        tmp.replace(dest)
    except OpenCodeError:
        raise
    except Exception as e:  # noqa: BLE001 — réseau, disque, zip corrompu
        raise OpenCodeError(t("oc_err_download", e=e)) from e
    finally:
        archive.unlink(missing_ok=True)
    return dest


def write_config(url: str, token: str, instructions: str) -> Path:
    """Écrit data/opencode/opencode.json (+ consignes) et retourne son chemin."""
    d = config.DATA_DIR / "opencode"
    d.mkdir(parents=True, exist_ok=True)
    rules = d / "servercraft-instructions.md"
    rules.write_text(instructions, encoding="utf-8")
    cfg = {
        "$schema": "https://opencode.ai/config.json",
        "mcp": {"servercraft": {
            "type": "remote", "url": url, "enabled": True, "oauth": False,
            "timeout": 180000,          # tunnels Playit, installation de mods
            "headers": {"Authorization": f"Bearer {token}"}}},
        # chemin absolu en « / » : un « \ » serait un échappement de glob
        "instructions": [rules.as_posix()],
    }
    path = d / "opencode.json"
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return path


def _env(cfg: Path) -> dict:
    return {**os.environ, "OPENCODE_CONFIG": str(cfg)}


def run(exe: Path, message: str, cwd: Path, cfg: Path, model: str = "",
        session: str = "") -> subprocess.Popen:
    """Lance `opencode run` ; lire `stdout` ligne par ligne (parse_event)."""
    cmd = [str(exe), "run", "--format", "json"]
    if session:
        cmd += ["--session", session]
    if model:
        cmd += ["--model", model]
    # un message commençant par « - » serait pris pour une option
    cmd.append(" " + message if message.startswith("-") else message)
    return subprocess.Popen(
        cmd, cwd=str(cwd), env=_env(cfg), stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace", creationflags=NO_WINDOW)


def parse_event(line: str) -> tuple:
    """Ligne de `opencode run --format json` -> (texte à afficher, session).
    Une ligne qui n'est pas du JSON (journal, erreur) est affichée telle quelle."""
    try:
        ev = json.loads(line)
    except ValueError:
        return line.rstrip(), ""
    if not isinstance(ev, dict):
        return line.rstrip(), ""
    sid = str(ev.get("sessionID") or "")
    part = ev.get("part") if isinstance(ev.get("part"), dict) else {}
    kind = ev.get("type")
    if kind == "text":
        return str(part.get("text") or "").strip(), sid
    if kind == "tool_use":
        st = part.get("state") if isinstance(part.get("state"), dict) else {}
        name = part.get("tool", "?")
        if st.get("status") == "error":
            return f"✗ {name} : {st.get('error', '')}", sid
        return f"⚙ {name}" + (f" — {st['title']}" if st.get("title")
                              else ""), sid
    if kind == "error":
        err = ev.get("error")
        if isinstance(err, dict):
            data = err.get("data") if isinstance(err.get("data"), dict) else {}
            err = data.get("message") or err.get("name") or json.dumps(err)
        return f"✖ {err}", sid
    return "", sid                      # step_start, step_finish…


def list_models(exe: Path, cfg: Path) -> list:
    """`opencode models` (provider/modèle), modèles OpenCode gratuits en tête ;
    [] si la commande échoue."""
    try:
        out = subprocess.run(
            [str(exe), "models"], env=_env(cfg), stdin=subprocess.DEVNULL,
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=90, creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    models = [ln.strip() for ln in out.splitlines()
              if "/" in ln and " " not in ln.strip()]
    return sorted(set(models), key=lambda m: (
        not m.startswith("opencode/"), "free" not in m, m))


def open_tui(exe: Path, cwd: Path, cfg: Path, model: str = "",
             session: str = "") -> None:
    """OpenCode complet (interface plein écran) dans une nouvelle console :
    connexion aux fournisseurs (/connect), choix du modèle…"""
    cmd = [str(exe)]
    if session:
        cmd += ["--session", session]
    if model:
        cmd += ["--model", model]
    subprocess.Popen(cmd, cwd=str(cwd), env=_env(cfg),
                     creationflags=NEW_CONSOLE)
