"""Détection des adresses IP du serveur."""
import os
import re
import socket
from pathlib import Path

import requests


def local_ip() -> str:
    """IP locale de la machine (celle à donner aux joueurs du même réseau)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def public_ip(timeout: float = 3.0) -> str | None:
    """IP publique (WAN) — None si indéterminable (offline, NAT…)."""
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            ip = requests.get(url, timeout=timeout).text.strip()
            if ip:
                return ip
        except requests.RequestException:
            continue
    return None


def _listeners(port: int) -> list:
    """Connexions TCP en écoute sur ce port (psutil : lecture de la table
    du système, aucun socket ouvert)."""
    import psutil
    return [c for c in psutil.net_connections(kind="tcp")
            if c.status == psutil.CONN_LISTEN and c.laddr
            and c.laddr.port == int(port)]


def port_in_use(port: int) -> bool:
    """True si un autre programme écoute déjà sur ce port TCP (le serveur
    Minecraft planterait au démarrage avec « FAILED TO BIND TO PORT »)."""
    try:
        return bool(_listeners(port))
    except Exception:  # noqa: BLE001 — psutil absent ou droits insuffisants
        return _bind_fails(port)


def _bind_fails(port: int) -> bool:
    """Repli sans psutil : le port est pris si on ne peut pas s'y lier
    (liaison seule, sans écoute : n'alerte pas le pare-feu)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if os.name != "nt":
            # Unix : sans ça, un port tout juste libéré paraît occupé.
            # (Sous Windows l'option aurait l'effet inverse : elle laisse
            # se lier à un port réellement utilisé.)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", int(port)))
        return False
    except OSError:
        return True
    finally:
        s.close()


def port_owner(port: int) -> str:
    """« java.exe (PID 1234) » : le programme qui écoute sur ce port, ou ""
    si on ne peut pas le savoir."""
    try:
        import psutil
        for conn in _listeners(port):
            if conn.pid:
                try:
                    name = psutil.Process(conn.pid).name()
                except psutil.Error:
                    name = "?"
                return f"{name} (PID {conn.pid})"
    except Exception:  # noqa: BLE001 — droits insuffisants, psutil absent
        pass
    return ""


def playit_address(server_dir: Path) -> str | None:
    """Adresse du tunnel playit.gg si le serveur en a un (PLAYIT-README.txt)."""
    f = server_dir / "PLAYIT-README.txt"
    if not f.exists():
        return None
    m = re.search(r"(?m)^Adresse\s*:\s*(\S+)", f.read_text(
        encoding="utf-8", errors="ignore"))
    return m.group(1) if m else None
