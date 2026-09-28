"""Bannis et opérateurs — fonctionne serveur lancé OU arrêté.

- Serveur lancé : on passe par les commandes (`pardon`, `op`, `ban`…), le
  serveur met lui-même à jour ses fichiers JSON.
- Serveur arrêté : on édite directement `banned-players.json`,
  `banned-ips.json` et `ops.json` (le serveur les relit au démarrage).
"""
import hashlib
import json
import time
import uuid as uuidlib
from pathlib import Path

import requests

BANNED = "banned-players.json"
BANNED_IPS = "banned-ips.json"
OPS = "ops.json"


def _read(path: Path) -> list:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _write(path: Path, data: list) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                    encoding="utf-8")


def offline_uuid(name: str) -> str:
    """UUID « hors-ligne » calculé comme le fait le serveur Minecraft."""
    h = bytearray(hashlib.md5(f"OfflinePlayer:{name}".encode()).digest())
    h[6] = (h[6] & 0x0F) | 0x30
    h[8] = (h[8] & 0x3F) | 0x80
    return str(uuidlib.UUID(bytes=bytes(h)))


def player_uuid(name: str, online_mode: bool) -> str:
    if online_mode:
        try:
            r = requests.get(
                f"https://api.mojang.com/users/profiles/minecraft/{name}",
                timeout=8)
            if r.ok:
                raw = r.json()["id"]
                return str(uuidlib.UUID(raw))
        except (requests.RequestException, KeyError, ValueError):
            pass
    return offline_uuid(name)


# ---------------------------------------------------------------- lecture

def list_bans(server_dir: Path) -> list:
    """[{name, uuid, reason, source, created, expires, ip?}] — joueurs + IP."""
    d = Path(server_dir)
    out = []
    for e in _read(d / BANNED):
        out.append({"name": e.get("name", "?"), "uuid": e.get("uuid", ""),
                    "reason": e.get("reason", ""),
                    "source": e.get("source", ""),
                    "created": e.get("created", ""),
                    "expires": e.get("expires", "forever"), "ip": None})
    for e in _read(d / BANNED_IPS):
        out.append({"name": e.get("ip", "?"), "uuid": "", "ip": e.get("ip"),
                    "reason": e.get("reason", ""),
                    "source": e.get("source", ""),
                    "created": e.get("created", ""),
                    "expires": e.get("expires", "forever")})
    return out


def list_ops(server_dir: Path) -> list:
    return [{"name": e.get("name", "?"), "uuid": e.get("uuid", ""),
             "level": e.get("level", 4)}
            for e in _read(Path(server_dir) / OPS)]


def is_op(server_dir: Path, name: str) -> bool:
    return any(o["name"].lower() == name.lower()
               for o in list_ops(server_dir))


# ---------------------------------------------------------------- actions

def unban(server_dir: Path, entry: dict, proc=None) -> None:
    if proc and proc.is_running():
        proc.send(f"pardon-ip {entry['ip']}" if entry.get("ip")
                  else f"pardon {entry['name']}")
        return
    d = Path(server_dir)
    if entry.get("ip"):
        f = d / BANNED_IPS
        _write(f, [e for e in _read(f) if e.get("ip") != entry["ip"]])
    else:
        f = d / BANNED
        _write(f, [e for e in _read(f)
                   if e.get("name", "").lower() != entry["name"].lower()])


def op(server_dir: Path, name: str, uuid: str = "", proc=None,
       online_mode: bool = False) -> None:
    if proc and proc.is_running():
        proc.send(f"op {name}")
        return
    f = Path(server_dir) / OPS
    ops = [e for e in _read(f) if e.get("name", "").lower() != name.lower()]
    ops.append({"uuid": uuid or player_uuid(name, online_mode), "name": name,
                "level": 4, "bypassesPlayerLimit": False})
    _write(f, ops)


def deop(server_dir: Path, name: str, proc=None) -> None:
    if proc and proc.is_running():
        proc.send(f"deop {name}")
        return
    f = Path(server_dir) / OPS
    _write(f, [e for e in _read(f)
               if e.get("name", "").lower() != name.lower()])


def ban(server_dir: Path, name: str, reason: str = "", proc=None,
        online_mode: bool = False) -> None:
    if proc and proc.is_running():
        proc.send(f"ban {name} {reason}".strip())
        return
    f = Path(server_dir) / BANNED
    bans = [e for e in _read(f) if e.get("name", "").lower() != name.lower()]
    bans.append({
        "uuid": player_uuid(name, online_mode), "name": name,
        "created": time.strftime("%Y-%m-%d %H:%M:%S +0000", time.gmtime()),
        "source": "ServerCraft Agent", "expires": "forever",
        "reason": reason or "Banni par un opérateur",
    })
    _write(f, bans)
