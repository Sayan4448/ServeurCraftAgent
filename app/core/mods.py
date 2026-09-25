"""Mods & plugins : sources Modrinth + CurseForge, install, et Playit.gg."""
import json
from pathlib import Path

import requests

from .downloader import MOD_LOADERS, PLUGIN_LOADERS, download_file
from .properties import load_properties, save_properties, update_properties

MODRINTH_API = "https://api.modrinth.com/v2"
CURSEFORGE_API = "https://api.curseforge.com/v1"
FORGECDN = "https://edge.forgecdn.net/files"
_UA = {"User-Agent": "ServerCraftAgent/0.2 (local server manager)"}

VOICE_PROJECTS = {
    "simple_voice_chat": "simple-voice-chat",
    "plasmo_voice": "plasmo-voice",
}
VOICE_LABELS = {
    "simple_voice_chat": "Simple Voice Chat",
    "plasmo_voice": "Plasmo Voice",
}

# Catégories Modrinth selon le loader (ordre = préférence).
LOADER_MAP = {
    "paper": ["paper", "bukkit"],
    "purpur": ["purpur", "paper", "bukkit"],
    "fabric": ["fabric"],
    "forge": ["forge"],
    "neoforge": ["neoforge"],
    "mohist": ["forge", "bukkit"],
}

# CurseForge : classId 6 = mods, 5 = plugins Bukkit. ModLoaderType enum.
CF_MODLOADER = {
    "forge": 1, "fabric": 4, "neoforge": 6,
}
CF_CLASS_MOD = 6
CF_CLASS_PLUGIN = 5

DEFAULT_VOICE_PORT = 24454


class ModError(Exception):
    pass


# ------------------------------------------------------------- helpers dossiers

def supports_plugins(loader: str) -> bool:
    return loader in PLUGIN_LOADERS


def supports_mods(loader: str) -> bool:
    return loader in MOD_LOADERS


def target_dir(server_dir: Path, loader: str, kind: str) -> Path:
    """kind = 'mod' | 'plugin' -> dossier de destination selon le loader."""
    if kind == "plugin":
        if not supports_plugins(loader):
            raise ModError(f"{loader} ne supporte pas les plugins Bukkit.")
        return server_dir / "plugins"
    if not supports_mods(loader):
        raise ModError(f"{loader} ne supporte pas les mods.")
    return server_dir / "mods"


def default_kind(loader: str) -> str:
    """Type de contenu privilégié pour ce loader."""
    if loader in ("paper", "purpur"):
        return "plugin"
    return "mod"


def list_installed(server_dir: Path, loader: str) -> list:
    """Fichiers .jar présents dans mods/ et plugins/ (selon le loader)."""
    out = []
    dirs = []
    if supports_mods(loader):
        dirs.append(("mod", server_dir / "mods"))
    if supports_plugins(loader):
        dirs.append(("plugin", server_dir / "plugins"))
    for kind, d in dirs:
        if d.exists():
            for f in sorted(d.glob("*.jar")):
                out.append({"kind": kind, "name": f.name, "path": str(f)})
    return out


def remove_installed(path: str) -> None:
    Path(path).unlink(missing_ok=True)


# ------------------------------------------------------------------- Modrinth

def search_modrinth(query: str, loader: str, mc_version: str,
                    kind: str = "mod", limit: int = 20,
                    offset: int = 0) -> list:
    """Recherche Modrinth. kind = 'mod' | 'plugin'."""
    facets = [["project_type:" + ("plugin" if kind == "plugin" else "mod")]]
    if mc_version:
        facets.append(["versions:" + mc_version])
    loaders = LOADER_MAP.get(loader, [loader])
    # mohist : mods = forge ; plugins = bukkit/paper
    if loader == "mohist":
        loaders = ["forge"] if kind == "mod" else ["bukkit", "paper", "spigot"]
    # Modrinth : éléments d'une même sous-liste = OU logique
    facets.append([f"categories:{l}" for l in loaders])
    r = requests.get(
        f"{MODRINTH_API}/search",
        params={
            "query": query, "facets": json.dumps(facets),
            "limit": limit, "offset": offset, "index": "downloads",
        },
        headers=_UA, timeout=20,
    )
    r.raise_for_status()
    return [
        {
            "id": h["project_id"], "slug": h["slug"], "title": h["title"],
            "description": h["description"], "downloads": h["downloads"],
            "author": h["author"], "source": "modrinth",
            "kind": kind, "icon": h.get("icon_url", ""),
        }
        for h in r.json().get("hits", [])
    ]


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
        params.pop("loaders")
        r = requests.get(
            f"{MODRINTH_API}/project/{project}/version",
            params=params, headers=_UA, timeout=30,
        )
        r.raise_for_status()
        versions = r.json()
    return versions


def install_modrinth(project_slug: str, server_dir: Path, loader: str,
                     mc_version: str, kind: str, progress_cb=None) -> Path:
    loaders = LOADER_MAP.get(loader, [loader])
    if loader == "mohist":
        loaders = ["forge"] if kind == "mod" else ["bukkit", "paper", "spigot"]
    versions = _modrinth_versions(project_slug, loaders, mc_version)
    if not versions:
        raise ModError(f"{project_slug} : aucune version pour {mc_version}")
    files = versions[0].get("files", [])
    jar = next((f for f in files if f.get("primary")), None) or next(
        (f for f in files if f["filename"].endswith(".jar")), None)
    if not jar:
        raise ModError(f"{project_slug} : aucun fichier .jar téléchargeable")
    dest = target_dir(server_dir, loader, kind) / jar["filename"]
    return download_file(jar["url"], dest, progress_cb)


# ----------------------------------------------------------------- CurseForge

def _cf_headers(api_key: str) -> dict:
    return {**_UA, "x-api-key": api_key, "Accept": "application/json"}


def search_curseforge(query: str, loader: str, mc_version: str,
                      kind: str, api_key: str, limit: int = 20,
                      offset: int = 0) -> list:
    """Recherche CurseForge. Nécessite une clé API (console.curseforge.com)."""
    if not api_key:
        raise ModError("CurseForge nécessite une clé API "
                       "(console.curseforge.com — gratuite).")
    class_id = CF_CLASS_PLUGIN if kind == "plugin" else CF_CLASS_MOD
    params = {
        "gameId": 432, "classId": class_id, "searchFilter": query,
        "pageSize": limit, "index": offset, "sortField": 2,
        "sortOrder": "desc",
    }
    if mc_version:
        params["gameVersion"] = mc_version
    if kind == "mod" and loader in CF_MODLOADER:
        params["modLoaderType"] = CF_MODLOADER[loader]
    r = requests.get(f"{CURSEFORGE_API}/mods/search", params=params,
                     headers=_cf_headers(api_key), timeout=20)
    if r.status_code == 403:
        raise ModError("Clé API CurseForge invalide.")
    r.raise_for_status()
    out = []
    for m in r.json().get("data", []):
        out.append({
            "id": m["id"], "slug": m.get("slug", str(m["id"])),
            "title": m["name"], "description": (m.get("summary") or "")[:200],
            "downloads": m.get("downloadCount", 0),
            "author": ", ".join(a["name"] for a in m.get("authors", [])),
            "source": "curseforge", "kind": kind,
            "icon": (m.get("logo") or {}).get("thumbnailUrl", ""),
        })
    return out


def install_curseforge(mod_id: int, server_dir: Path, loader: str,
                       mc_version: str, kind: str, api_key: str,
                       progress_cb=None) -> Path:
    params = {"pageSize": 50}
    if mc_version:
        params["gameVersion"] = mc_version
    if kind == "mod" and loader in CF_MODLOADER:
        params["modLoaderType"] = CF_MODLOADER[loader]
    r = requests.get(f"{CURSEFORGE_API}/mods/{mod_id}/files", params=params,
                     headers=_cf_headers(api_key), timeout=20)
    r.raise_for_status()
    files = r.json().get("data", [])
    if not files:
        raise ModError(f"CurseForge mod {mod_id} : aucun fichier compatible.")
    f = files[0]
    url = f.get("downloadUrl")
    if not url:
        # Distribution restreinte : URL forgecdn reconstruite
        fid = str(f["id"])
        url = f"{FORGECDN}/{fid[:4]}/{fid[4:]}/{f['fileName']}"
    dest = target_dir(server_dir, loader, kind) / f["fileName"]
    return download_file(url, dest, progress_cb)


def install_result(result: dict, server_dir: Path, loader: str,
                   mc_version: str, api_key: str = "", progress_cb=None) -> Path:
    if result["source"] == "curseforge":
        return install_curseforge(result["id"], server_dir, loader,
                                  mc_version, result["kind"], api_key,
                                  progress_cb)
    return install_modrinth(result["slug"], server_dir, loader,
                            mc_version, result["kind"], progress_cb)


# ------------------------------------------------- versions par projet + dl

def _pick_jar(files: list):
    return next((f for f in files if f.get("primary")), None) or next(
        (f for f in files if f["filename"].endswith(".jar")), None)


def modrinth_version_list(project_slug: str, loader: str,
                          mc_version: str, kind: str) -> list:
    """Toutes les versions d'un projet compatibles loader/MC, plus récentes
    d'abord. Chaque entrée : name, date, game_versions, release_type, url,
    filename."""
    loaders = LOADER_MAP.get(loader, [loader])
    if loader == "mohist":
        loaders = ["forge"] if kind == "mod" else ["bukkit", "paper", "spigot"]
    out = []
    for v in _modrinth_versions(project_slug, loaders, mc_version):
        jar = _pick_jar(v.get("files", []))
        if not jar:
            continue
        out.append({
            "name": v["version_number"],
            "title": v["name"],
            "date": v["date_published"][:10],
            "game_versions": ", ".join(v["game_versions"]),
            "release_type": v.get("version_type", "release"),
            "url": jar["url"], "filename": jar["filename"],
        })
    return out


def curseforge_version_list(mod_id: int, loader: str, mc_version: str,
                            kind: str, api_key: str) -> list:
    params = {"pageSize": 50}
    if mc_version:
        params["gameVersion"] = mc_version
    if kind == "mod" and loader in CF_MODLOADER:
        params["modLoaderType"] = CF_MODLOADER[loader]
    r = requests.get(f"{CURSEFORGE_API}/mods/{mod_id}/files", params=params,
                     headers=_cf_headers(api_key), timeout=20)
    r.raise_for_status()
    types = {1: "release", 2: "beta", 3: "alpha"}
    out = []
    for f in r.json().get("data", []):
        url = f.get("downloadUrl")
        if not url:
            fid = str(f["id"])
            url = f"{FORGECDN}/{fid[:4]}/{fid[4:]}/{f['fileName']}"
        out.append({
            "name": f["displayName"],
            "title": f["fileName"],
            "date": f["fileDate"][:10],
            "game_versions": ", ".join(f["gameVersions"]),
            "release_type": types.get(f["releaseType"], "?"),
            "url": url, "filename": f["fileName"],
        })
    return out


def version_list(result: dict, loader: str, mc_version: str,
                 api_key: str = "") -> list:
    if result["source"] == "curseforge":
        return curseforge_version_list(result["id"], loader, mc_version,
                                       result["kind"], api_key)
    return modrinth_version_list(result["slug"], loader, mc_version,
                                 result["kind"])


def download_to(url: str, filename: str, server_dir: Path, loader: str,
                kind: str, progress_cb=None) -> Path:
    dest = target_dir(server_dir, loader, kind) / filename
    return download_file(url, dest, progress_cb)


# ---------------------------------------------------------------- Voice Chat

def install_voice_mod(
    server_dir: Path,
    loader: str,
    mc_version: str,
    which: str = "simple_voice_chat",
    progress_cb=None,
) -> Path:
    """Télécharge le plugin/mod Voice Chat dans plugins/ ou mods/."""
    project = VOICE_PROJECTS[which]
    kind = "plugin" if loader in ("paper", "purpur") else "mod"
    versions = _modrinth_versions(project, LOADER_MAP[loader], mc_version)
    if not versions:
        raise ModError(
            f"{VOICE_LABELS[which]} : aucune version trouvée pour {loader} {mc_version}"
        )
    files = versions[0].get("files", [])
    jar = next((f for f in files if f.get("primary")), None) or next(
        (f for f in files if f["filename"].endswith(".jar")), None)
    if not jar:
        raise ModError(f"{VOICE_LABELS[which]} : aucun fichier .jar téléchargeable")

    dest = target_dir(server_dir, loader, kind) / jar["filename"]
    download_file(jar["url"], dest, progress_cb)
    return dest


def voicechat_config_path(server_dir: Path, loader: str) -> Path:
    if supports_plugins(loader) and loader != "mohist":
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
