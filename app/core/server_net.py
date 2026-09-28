"""Détection des adresses IP du serveur."""
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


def playit_address(server_dir: Path) -> str | None:
    """Adresse du tunnel playit.gg si le serveur en a un (PLAYIT-README.txt)."""
    f = server_dir / "PLAYIT-README.txt"
    if not f.exists():
        return None
    m = re.search(r"(?m)^Adresse\s*:\s*(\S+)", f.read_text(
        encoding="utf-8", errors="ignore"))
    return m.group(1) if m else None
