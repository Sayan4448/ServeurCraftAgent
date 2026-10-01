"""Lecture/écriture des fichiers au format .properties de Minecraft."""
from pathlib import Path

DEFAULTS = {
    "server-port": "25565",
    "online-mode": "false",            # offline : pas de compte Minecraft requis
    "motd": "Serveur ServerCraft",
    "max-players": "20",
    "difficulty": "normal",
    "gamemode": "survival",
    "view-distance": "10",
    "simulation-distance": "10",
    "enable-command-block": "false",
    "spawn-protection": "0",
    "white-list": "false",
    "pvp": "true",
    "spawn-monsters": "true",
    "spawn-animals": "true",
    "spawn-npcs": "true",
    "allow-nether": "true",
    "allow-flight": "true",            # évite les kicks avec certains mods
    "sync-chunk-writes": "false",
}


MIN_RAM_MB = 256


def parse_port(text) -> int | None:
    """Port TCP/UDP valide (1–65535), ou None."""
    try:
        port = int(str(text).strip())
    except ValueError:
        return None
    return port if 1 <= port <= 65535 else None


def parse_ram_mb(text) -> int | None:
    """« 4 » ou « 2,5 » (Go) -> Mo ; None si ce n'est pas un nombre ou si
    c'est trop peu pour lancer Java (-Xmx0M empêche tout démarrage)."""
    try:
        mb = int(float(str(text).strip().replace(",", ".")) * 1024)
    except (ValueError, OverflowError):
        return None
    return mb if mb >= MIN_RAM_MB else None


def parse_count(text, minimum: int = 1) -> int | None:
    """Entier ≥ `minimum` (nombre de joueurs…), ou None."""
    try:
        n = int(str(text).strip())
    except ValueError:
        return None
    return n if n >= minimum else None


def load_properties(path: Path) -> dict:
    props = {}
    if not path.exists():
        return props
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        props[k.strip()] = v.strip()
    return props


def save_properties(path: Path, props: dict) -> None:
    lines = [f"{k}={v}" for k, v in props.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_server_properties(
    path: Path,
    port: int = 25565,
    online_mode: bool = False,
    motd: str = "Serveur ServerCraft",
    max_players: int = 20,
    difficulty: str = "normal",
    gamemode: str = "survival",
    extra: dict = None,
) -> None:
    props = dict(DEFAULTS)
    props.update({
        "server-port": str(port),
        "online-mode": "true" if online_mode else "false",
        "motd": motd,
        "max-players": str(max_players),
        "difficulty": difficulty,
        "gamemode": gamemode,
    })
    if extra:
        props.update({k: str(v) for k, v in extra.items()})
    save_properties(path, props)


def update_properties(path: Path, changes: dict) -> dict:
    props = load_properties(path)
    props.update({k: str(v) for k, v in changes.items()})
    save_properties(path, props)
    return props
