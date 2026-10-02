"""Tunnels Playit.gg automatiques : une adresse gratuite pour les joueurs,
sans ouvrir de port sur la box ni donner son IP publique.

1. Liaison (une seule fois) : un code est déclaré à api.playit.gg, l'utilisateur
   valide dans son navigateur (compte gratuit ou invité) et l'app reçoit la
   clé secrète de l'agent (data/playit.toml, jamais commitée).
2. Tunnels : créés via l'API pour chaque serveur (Java TCP, Bedrock UDP,
   Voice Chat UDP) ; les adresses publiques sont lues dans /v1/agents/rundata.
   L'agent doit avoir tourné au moins une fois avant : tant qu'il n'a pas
   annoncé sa version, l'API refuse la création (AgentVersionTooOld).
3. Transport : l'agent officiel playit (téléchargé depuis GitHub) tourne en
   arrière-plan tant qu'un serveur qui l'utilise est lancé.

Aucun appel Tk ici : fonctions bloquantes, à appeler depuis un thread.
"""
import re
import secrets
import subprocess
import threading
import time
from pathlib import Path

import requests

from ..config import DATA_DIR, RUNTIMES_DIR
from .downloader import download_file

API = "https://api.playit.gg"
AGENT_VERSION = "v1.0.10"
AGENT_URL = ("https://github.com/playit-cloud/playit-agent/releases/download/"
             f"{AGENT_VERSION}/playit-windows-x86_64-signed.exe")
AGENT_EXE = RUNTIMES_DIR / "playit" / f"playit-{AGENT_VERSION}.exe"
AGENT_LOG = RUNTIMES_DIR / "playit" / "agent.log"
SECRET_FILE = DATA_DIR / "playit.toml"
CLAIM_URL = "https://playit.gg/claim/{}"
CLAIM_TIMEOUT = 600
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

AGENT_READY_TIMEOUT = 45
# kind -> (tunnel_type de l'API, None = port libre ; type de port ; nom affiché)
KINDS = {
    "java": ("minecraft-java", "tcp", "Java"),
    "bedrock": ("minecraft-bedrock", "udp", "Bedrock"),
    "voice": (None, "udp", "Voice Chat"),
}
_SECRET_RE = re.compile(r'secret_key\s*=\s*"([^"]+)"')


class PlayitError(Exception):
    pass


_ERRORS = {
    "not linked": "pl_err_notlinked", "cancelled": "pl_err_cancel",
    "timeout": "pl_err_timeout", "rejected": "pl_err_rejected",
    "UserRejected": "pl_err_rejected", "CodeExpired": "pl_err_timeout",
    "InvalidAgentKey": "pl_err_key", "NoLongerValid": "pl_err_key",
    "RequiresVerifiedAccount": "pl_err_verify",
    "GuestAccountNotAllowed": "pl_err_verify",
    "RequiresPlayitPremium": "pl_err_premium",
    "PublicPortRequiresPlayitPremium": "pl_err_premium",
    "RegionRequiresPlayitPremium": "pl_err_premium",
    "AgentVersionTooOld": "pl_err_agent_old",
}


def explain(e: Exception) -> str:
    """Message traduit pour une erreur Playit."""
    from ..i18n import t
    msg = str(e)
    if msg in _ERRORS:
        return t(_ERRORS[msg])
    if msg.startswith("pending: "):
        return t("pl_err_pending", msg=msg[len("pending: "):])
    return msg


# ================================================================== API

def _call(path: str, body=None, secret: str | None = None,
          timeout: float = 15):
    from ..i18n import t
    headers = {"Authorization": f"Agent-Key {secret}"} if secret else {}
    try:
        r = requests.post(API + path, json=body or {}, headers=headers,
                          timeout=timeout)
    except requests.RequestException as e:
        raise PlayitError(t("pl_err_net", e=e)) from e
    if r.status_code == 429:
        raise PlayitError(t("pl_err_busy"))
    try:
        j = r.json()
    except ValueError:
        raise PlayitError(t("pl_err_http", code=r.status_code))
    if j.get("status") == "success":
        return j.get("data")
    data = j.get("data")
    if isinstance(data, dict):
        data = data.get("message", data)
    raise PlayitError(str(data))


# ================================================================ secret

def secret() -> str:
    try:
        m = _SECRET_RE.search(SECRET_FILE.read_text(encoding="utf-8"))
        return m.group(1).strip() if m else ""
    except OSError:
        return ""


def linked() -> bool:
    return bool(secret())


def _save_secret(key: str) -> None:
    SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    SECRET_FILE.write_text(f'secret_key = "{key.strip()}"\n',
                           encoding="utf-8")


def unlink() -> None:
    stop_agent()
    SECRET_FILE.unlink(missing_ok=True)


# ================================================================ liaison

def new_claim() -> tuple:
    """(code, url à ouvrir dans le navigateur)."""
    code = secrets.token_hex(5)
    return code, CLAIM_URL.format(code)


def link(code: str, on_status=None, cancel: threading.Event | None = None,
         timeout: float = CLAIM_TIMEOUT) -> str:
    """Attend la validation du code dans le navigateur puis enregistre la
    clé. `on_status(état)` : WaitingForUserVisit / WaitingForUser /
    UserAccepted. Lève PlayitError (refus, expiration, annulation)."""
    end = time.time() + timeout
    last = None
    # même format que l'agent officiel (« playit 1.0.10 ») : l'API en tire
    # la version de l'agent
    body = {"code": code, "agent_type": "self-managed",
            "version": f"playit {AGENT_VERSION.lstrip('v')}"}
    while True:
        if cancel and cancel.is_set():
            raise PlayitError("cancelled")
        if time.time() > end:
            raise PlayitError("timeout")
        state = _call("/claim/setup", body)
        if state != last and on_status:
            on_status(state)
        last = state
        if state == "UserRejected":
            raise PlayitError("rejected")
        if state == "UserAccepted":
            break
        time.sleep(1.5)
    while True:
        if cancel and cancel.is_set():
            raise PlayitError("cancelled")
        try:
            key = _call("/claim/exchange", {"code": code})["secret_key"]
            break
        except PlayitError as e:
            if str(e) not in ("NotAccepted", "NotSetup") or \
                    time.time() > end:
                raise
            time.sleep(1.5)
    _save_secret(key)
    return key


# ================================================================ tunnels

def rundata(key: str | None = None) -> dict:
    key = key or secret()
    if not key:
        raise PlayitError("not linked")
    return _call("/v1/agents/rundata", secret=key)


def _field(tunnel: dict, name: str) -> str:
    for f in (tunnel.get("agent_config") or {}).get("fields") or []:
        if f.get("name") == name:
            return str(f.get("value", ""))
    return ""


def _matches(tunnel: dict, kind: str, local: int) -> bool:
    want_type, proto, _ = KINDS[kind]
    return (tunnel.get("port_type") == proto
            and (tunnel.get("tunnel_type") or None) == want_type
            and _field(tunnel, "local_port") == str(local))


def wanted_for(meta: dict) -> list:
    """Tunnels d'un serveur : [(kind, port local)] — Java en TCP et Bedrock
    en UDP (prêt si le cross-play est activé plus tard), + Voice Chat."""
    from .crossplay import BEDROCK_PORT
    from .mods import DEFAULT_VOICE_PORT
    out = [("java", int(meta.get("port", 25565))),
           ("bedrock", BEDROCK_PORT)]
    if meta.get("voice", "none") not in ("none", "", None):
        out.append(("voice", DEFAULT_VOICE_PORT))
    return out


def setup_server(name: str, server_dir, log=None) -> list:
    """Tout-en-un pour un serveur : tunnels créés / retrouvés, adresses
    enregistrées dans servercraft.json (`tunnels`, `playit_auto`), config
    Voice Chat, puis agent démarré. `log(event, label, value)`."""
    import json
    from . import tunnels as tunnels_mod
    from .server_manager import META_FILE
    f = Path(server_dir) / META_FILE
    meta = json.loads(f.read_text(encoding="utf-8"))
    found = ensure_tunnels(name, wanted_for(meta), log)
    keep = [tn for tn in meta.get("tunnels") or []
            if not any(tn.get("proto") == x["proto"]
                       and str(tn.get("local")) == str(x["local"])
                       for x in found)]
    meta["tunnels"] = found + keep
    meta["playit_auto"] = True
    f.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    tunnels_mod.apply(Path(server_dir), meta.get("loader", ""),
                      meta["tunnels"], java_port=int(meta.get("port", 25565)),
                      voice=meta.get("voice", "none"))
    if log:
        log("agent", "", "")
    return found


def ensure_tunnels(server: str, wanted: list, log=None,
                   timeout: float = 90) -> list:
    """Crée les tunnels manquants pour `server` et attend leurs adresses.
    Retourne des entrées au format de `tunnels.py`
    ({name, proto, address, local})."""
    key = secret()
    rd = rundata(key)
    agent_id = rd["agent_id"]
    start_agent()
    for kind, local in wanted:
        known = rd.get("tunnels", []) + rd.get("pending", [])
        if any(_matches(tn, kind, local) for tn in rd.get("tunnels", [])):
            continue
        name = _tunnel_name(server, kind)
        if any(p.get("name") == name for p in known):
            continue                                    # déjà en attente
        tunnel_type, proto, label = KINDS[kind]
        if log:
            log("create", label, local)
        _create_tunnel(key, {
            "name": name, "tunnel_type": tunnel_type, "port_type": proto,
            "port_count": 1, "enabled": True, "alloc": None,
            "firewall_id": None, "proxy_protocol": None,
            "origin": {"type": "agent", "data": {
                "agent_id": agent_id, "local_ip": "127.0.0.1",
                "local_port": int(local)}},
        })
    end = time.time() + timeout
    while True:
        rd = rundata(key)
        found, missing = [], []
        for kind, local in wanted:
            tn = next((x for x in rd.get("tunnels", [])
                       if _matches(x, kind, local)
                       and x.get("display_address")), None)
            if tn:
                found.append({"name": KINDS[kind][2], "proto": KINDS[kind][1],
                              "address": tn["display_address"],
                              "local": local, "playit": True})
            else:
                missing.append(kind)
        if not missing:
            if log:
                for tn in found:
                    log("ready", tn["name"], tn["address"])
            return found
        if time.time() > end:
            pend = [p.get("status_msg", "") for p in rd.get("pending", [])
                    if p.get("status_msg")]
            raise PlayitError(("pending: " + ", ".join(pend)) if pend
                              else "timeout")
        time.sleep(3)


def _create_tunnel(key: str, body: dict) -> None:
    """Crée un tunnel. Juste après la liaison, l'agent n'a pas encore annoncé
    sa version : l'API répond AgentVersionTooOld le temps qu'il se connecte."""
    end = time.time() + AGENT_READY_TIMEOUT
    while True:
        try:
            _call("/tunnels/create", body, secret=key)
            return
        except PlayitError as e:
            if str(e) != "AgentVersionTooOld" or time.time() > end:
                raise
            time.sleep(2)


def _tunnel_name(server: str, kind: str) -> str:
    base = re.sub(r"[^A-Za-z0-9 _.-]", "", f"SC {server}")[:40].strip()
    return f"{base} {KINDS[kind][2]}"[:60]


# ================================================================ agent

_agent: subprocess.Popen | None = None
_agent_lock = threading.Lock()
_agent_tail: list = []


def ensure_agent_exe(progress=None) -> Path:
    if not AGENT_EXE.exists():
        download_file(AGENT_URL, AGENT_EXE, progress)
    return AGENT_EXE


def agent_running() -> bool:
    return _agent is not None and _agent.poll() is None


def agent_error() -> str:
    """Dernière erreur de l'agent (s'il s'est arrêté tout seul)."""
    if _agent is not None and _agent.poll() is not None:
        return next((ln for ln in reversed(_agent_tail) if ln.strip()), "")
    return ""


def start_agent() -> None:
    """Lance l'agent playit (une seule instance pour tous les serveurs)."""
    global _agent
    with _agent_lock:
        if agent_running():
            return
        if not linked():
            raise PlayitError("not linked")
        exe = ensure_agent_exe()
        _agent_tail.clear()
        _agent = subprocess.Popen(
            [str(exe), "--secret", secret(), "--log-path", str(AGENT_LOG)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            errors="replace", creationflags=NO_WINDOW)
        threading.Thread(target=_drain, args=(_agent,), daemon=True).start()


def _drain(proc) -> None:
    for line in proc.stdout:
        _agent_tail.append(line.rstrip())
        del _agent_tail[:-30]


def stop_agent() -> None:
    global _agent
    with _agent_lock:
        if _agent is not None and _agent.poll() is None:
            _agent.terminate()
            try:
                _agent.wait(5)
            except subprocess.TimeoutExpired:
                _agent.kill()
        _agent = None


def release(processes) -> None:
    """Arrête l'agent si plus aucun serveur Playit-auto ne tourne (un
    serveur en cours de redémarrage compte comme lancé)."""
    if not any((p.is_running() or getattr(p, "_starting", False))
               and p.meta.get("playit_auto") for p in processes):
        stop_agent()
