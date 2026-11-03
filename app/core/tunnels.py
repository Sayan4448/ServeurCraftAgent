"""Tunnels Playit.gg multiples (Java, Bedrock, Voice Chat, autres…).

Chaque tunnel : {"name", "proto" ("tcp"|"udp"), "address" (hôte:port public),
"local" (port local)}. Stockés dans servercraft.json (`tunnels`).
"""
from pathlib import Path

from . import mods as mods_mod

DEFAULTS = [
    {"name": "Java", "proto": "tcp", "address": "", "local": 25565},
    {"name": "Bedrock", "proto": "udp", "address": "", "local": 19132},
    {"name": "Voice Chat", "proto": "udp", "address": "", "local": 24454},
]


def clean(tunnels: list) -> list:
    out = []
    for tn in tunnels or []:
        addr = (tn.get("address") or "").strip()
        if not addr:
            continue
        try:
            local = int(tn.get("local") or 0)
        except (TypeError, ValueError):
            local = 0
        out.append({"name": (tn.get("name") or "Tunnel").strip() or "Tunnel",
                    "proto": "udp" if tn.get("proto") == "udp" else "tcp",
                    "address": addr, "local": local})
    return out


def apply(server_dir: Path, loader: str, tunnels: list,
          java_port: int = 25565, voice: str = "none") -> str:
    """Donne au mod vocal (Simple Voice Chat ou Plasmo Voice) l'adresse du
    tunnel UDP qui vise son port, et écrit un récapitulatif
    PLAYIT-README.txt. Retourne ce récapitulatif."""
    server_dir = Path(server_dir)
    tunnels = clean(tunnels)
    voice = mods_mod.voice_mod(server_dir, loader, voice)
    if voice != "none":
        vport = mods_mod.voice_port(server_dir, loader, voice, java_port)
        vc_tunnel = next((tn for tn in tunnels if tn["proto"] == "udp"
                          and tn["local"] == vport), None)
        if vc_tunnel:
            mods_mod.set_voice_host(server_dir, loader, voice,
                                    vc_tunnel["address"], vport)
    lines = ["=== Tunnels Playit.gg ===", ""]
    for tn in tunnels:
        lines.append(f"{tn['name']:<12} {tn['proto'].upper():<4} "
                     f"{tn['address']:<32} -> localhost:{tn['local']}")
    if not tunnels:
        lines.append("(aucun tunnel)")
    java = next((tn for tn in tunnels if tn["proto"] == "tcp"
                 and tn["local"] == java_port), None)
    if java:
        lines += ["", f"Adresse : {java['address']}"]
    lines += ["", "Dans playit.gg, créez un tunnel par ligne (même protocole "
                  "et même port local)."]
    summary = "\n".join(lines)
    (server_dir / "PLAYIT-README.txt").write_text(summary, encoding="utf-8")
    return summary
