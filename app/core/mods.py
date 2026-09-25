"""Installation de mods/plugins (Modrinth) et configuration Playit.gg + Voice Chat."""
import json
from pathlib import Path

import requests

from .downloader import download_file
from .properties import load_properties, save_properties, update_properties

MODRINTH_API = "https://api.modrinth.com/v2"
_UA = {"User-Agent": "ServerCraftAgent/1.0 (local server manager)"}

VOICE_PROJECTS = {
    "simple_voice_chat": "simple-voice-chat",
    "plasmo_voice": "plasmo-voice",
}
VOICE_LABELS = {
    "simple_voice_chat": "Simple Voice Chat",
    "plasmo_voice": "Plasmo Voice",
}

# Loaders Modrinth à interroger selon le type de serveur (repli inclus).
LOADER_MAP = {
    "paper": ["paper", "bukkit"],
    "purpur": ["purpur", "paper", "bukkit"],
    "fabric": ["fabric"],
    "forge": ["forge"],
    "neoforge": ["neoforge"],
}

DEFAULT_VOICE_PORT = 24454


class ModError(Exception):
    pass


def _modrinth_versions(project: str, loaders: list, mc_version: str) -> list:
    params = {
        "loaders": json.dumps(loaders),
        "game_versions": json.dumps([mc_version]),
    }
    r = requests.get(
        f"{MODRINTH_API}/project/{project}/version",
        params=params, headers=_UA, timeout=30,
    )
    r.raise_for_status()
    versions = r.json()
    if not versions and loaders:
        # Repli : certaines releases n'étiquettent pas tous les loaders.
        params.pop("loaders")
        r = requests.get(
            f"{MODRINTH_API}/project/{project}/version",
            params=params, headers=_UA, timeout=30,
        )
        r.raise_for_status()
        versions = r.json()
    return versions


def install_voice_mod(
    server_dir: Path,
    loader: str,
    mc_version: str,
    which: str = "simple_voice_chat",
    progress_cb=None,
) -> Path:
    """Télécharge le plugin/mod Voice Chat dans plugins/ ou mods/."""
    project = VOICE_PROJECTS[which]
    versions = _modrinth_versions(project, LOADER_MAP[loader], mc_version)
    if not versions:
        raise ModError(
            f"{VOICE_LABELS[which]} : aucune version trouvée pour {loader} {mc_version}"
        )
    files = versions[0].get("files", [])
    jar = next((f for f in files if f.get("primary")), None) or next(
        (f for f in files if f["filename"].endswith(".jar")), None
    )
    if not jar:
        raise ModError(f"{VOICE_LABELS[which]} : aucun fichier .jar téléchargeable")

    sub = "plugins" if loader in ("paper", "purpur") else "mods"
    dest = server_dir / sub / jar["filename"]
    download_file(jar["url"], dest, progress_cb)
    return dest


def voicechat_config_path(server_dir: Path, loader: str) -> Path:
    if loader in ("paper", "purpur"):
        return server_dir / "plugins" / "voicechat" / "voicechat-server.properties"
    return server_dir / "config" / "voicechat" / "voicechat-server.properties"


def write_voicechat_config(
    server_dir: Path,
    loader: str,
    voice_port: int = DEFAULT_VOICE_PORT,
    voice_host: str = "",
) -> Path:
    """Pré-génère voicechat-server.properties (le plugin lit ce fichier au démarrage)."""
    path = voicechat_config_path(server_dir, loader)
    props = load_properties(path)
    props.setdefault("port", str(voice_port))
    props["port"] = str(voice_port)
    props["bind_address"] = ""
    props["voice_host"] = voice_host
    props.setdefault("allow_groups", "true")
    props.setdefault("max_voice_distance", "48")
    path.parent.mkdir(parents=True, exist_ok=True)
    save_properties(path, props)
    return path


def configure_playit(
    server_dir: Path,
    loader: str,
    address: str,
    tcp_port: int,
    udp_port: int = 0,
    local_server_port: int = 25565,
    local_voice_port: int = DEFAULT_VOICE_PORT,
    voice_enabled: bool = True,
) -> str:
    """Applique la config Playit et retourne le récapitulatif à copier.

    Playit fait du tunnel : le serveur continue d'écouter en local, playit
    expose les ports publics. On renseigne donc `voice_host` (ce que le serveur
    Voice Chat annonce aux clients) avec l'adresse + port UDP publics.
    """
    voice_host = f"{address}:{udp_port}" if udp_port else address
    if voice_enabled:
        write_voicechat_config(server_dir, loader, local_voice_port, voice_host)

    lines = [
        "=== Récapitulatif Playit.gg ===",
        "",
        f"Adresse à donner aux joueurs (Minecraft) : {address}:{tcp_port}",
        "",
        "Dans le panneau playit.gg, crée :",
        f"  - Tunnel TCP  -> localhost:{local_server_port}   (port public {tcp_port})",
    ]
    if voice_enabled:
        lines += [
            f"  - Tunnel UDP  -> localhost:{local_voice_port}   (port public {udp_port})",
            "",
            f"voicechat-server.properties : voice_host={voice_host}",
        ]
    lines += [
        "",
        "Le serveur écoute en local (pas besoin d'ouvrir les ports du routeur).",
        "Mode offline : les joueurs peuvent rejoindre sans compte Minecraft.",
    ]
    summary = "\n".join(lines)
    (server_dir / "PLAYIT-README.txt").write_text(summary, encoding="utf-8")
    return summary
