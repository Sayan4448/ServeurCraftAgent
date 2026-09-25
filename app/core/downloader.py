"""Récupération des versions Minecraft et téléchargement des server.jar.

Loaders supportés : Paper, Purpur, Fabric, Forge, NeoForge.
- Paper  : API papermc.io v2
- Purpur : API purpurmc.org v2
- Fabric : meta.fabricmc.net (JAR serveur pré-généré)
- Forge  : promotions_slim.json + maven (installeur à exécuter avec --installServer)
- NeoForge : maven-metadata.xml (installeur à exécuter avec --installServer)
"""
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

_UA = {"User-Agent": "ServerCraftAgent/1.0 (local server manager)"}

PAPER_API = "https://fill.papermc.io/v3/projects/paper"
PURPUR_API = "https://api.purpurmc.org/v2/purpur"
FABRIC_META = "https://meta.fabricmc.net/v2/versions"
FORGE_PROMOS = "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
FORGE_MAVEN = "https://maven.minecraftforge.net/net/minecraftforge/forge"
NEOFORGE_META = "https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml"
NEOFORGE_MAVEN = "https://maven.neoforged.net/releases/net/neoforged/neoforge"
MOHIST_API = "https://api.mohistmc.com/project/mohist"

LOADERS = ("paper", "purpur", "fabric", "forge", "neoforge", "mohist")
LOADER_LABELS = {
    "paper": "Paper (plugins)",
    "purpur": "Purpur (plugins)",
    "fabric": "Fabric (mods)",
    "forge": "Forge (mods)",
    "neoforge": "NeoForge (mods)",
    "mohist": "Mohist (mods + plugins)",
}

# Où vont les contenus additionnels selon le loader
PLUGIN_LOADERS = ("paper", "purpur", "mohist")   # ont un dossier plugins/
MOD_LOADERS = ("fabric", "forge", "neoforge", "mohist")  # dossier mods/


class DownloadError(Exception):
    pass


def _get_json(url: str, timeout: int = 30):
    r = requests.get(url, headers=_UA, timeout=timeout)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------- versions

def list_paper_versions() -> list:
    data = _get_json(PAPER_API)
    versions = []
    for group in data.get("versions", {}).values():
        versions.extend(group)
    stable = [v for v in versions if "-" not in v]  # exclut rc/pre
    return stable or versions


def list_purpur_versions() -> list:
    data = _get_json(PURPUR_API)
    return list(reversed(data.get("versions", [])))


def list_fabric_versions() -> list:
    data = _get_json(f"{FABRIC_META}/game")
    return [v["version"] for v in data if v.get("stable")]


def list_forge_versions() -> list:
    """Versions de Minecraft ayant un build Forge (clé 'x.y-latest'/'-recommended')."""
    data = _get_json(FORGE_PROMOS).get("promos", {})
    mcs = set()
    for key in data:
        mc, _, kind = key.rpartition("-")
        if kind in ("latest", "recommended") and mc:
            mcs.add(mc)
    return _sort_mc_versions(mcs)


def _neoforge_to_mc(ver: str):
    """NeoForge -> version MC.
    Ancien schéma : 21.1.x -> 1.21.1 / 21.0.x -> 1.21
    Nouveau (Mojang 2026) : 26.1.2.x -> 26.1.2 / 26.2.0.x -> 26.2"""
    parts = ver.split("-")[0].split("+")[0].split(".")
    if len(parts) == 3 and parts[0].isdigit():
        major, minor = parts[0], parts[1]
        return f"1.{major}.{minor}" if minor != "0" else f"1.{major}"
    if len(parts) >= 4 and all(p.isdigit() for p in parts[:3]):
        y, d, p = parts[0], parts[1], parts[2]
        return f"{y}.{d}.{p}" if p != "0" else f"{y}.{d}"
    return None


def _mc_to_neoforge_prefix(mc: str) -> str:
    parts = mc.split(".")
    if parts[0] == "1":  # 1.21.1 -> 21.1 ; 1.21 -> 21.0
        return f"{parts[1]}.{parts[2]}" if len(parts) >= 3 else f"{parts[1]}.0"
    # 26.1.2 -> 26.1.2 ; 26.2 -> 26.2.0
    return ".".join(parts[:3]) if len(parts) >= 3 else f"{parts[0]}.{parts[1]}.0"


def list_neoforge_versions() -> list:
    """Versions de Minecraft supportées par NeoForge."""
    r = requests.get(NEOFORGE_META, headers=_UA, timeout=30)
    r.raise_for_status()
    root = ET.fromstring(r.text)
    mcs = set()
    for v in root.iter("version"):
        mc = _neoforge_to_mc(v.text.strip())
        if mc:
            mcs.add(mc)
    return _sort_mc_versions(mcs)


def _sort_mc_versions(versions) -> list:
    def key(v):
        out = []
        for p in v.split("."):
            out.append(int(p) if p.isdigit() else -1)
        return out
    return sorted(versions, key=key, reverse=True)


def list_mohist_versions() -> list:
    data = _get_json(f"{MOHIST_API}/versions")
    return _sort_mc_versions(v["name"] for v in data)


def get_versions(loader: str) -> list:
    return {
        "paper": list_paper_versions,
        "purpur": list_purpur_versions,
        "fabric": list_fabric_versions,
        "forge": list_forge_versions,
        "neoforge": list_neoforge_versions,
        "mohist": list_mohist_versions,
    }[loader]()


# ------------------------------------------------------- urls de téléchargement

def paper_download(version: str):
    build = _get_json(f"{PAPER_API}/versions/{version}/builds/latest")
    dl = build["downloads"]["server:default"]
    return dl["url"], dl["name"], "jar"


def purpur_download(version: str):
    url = f"{PURPUR_API}/{version}/latest/download"
    return url, f"purpur-{version}.jar", "jar"


def fabric_download(version: str):
    loaders = _get_json(f"{FABRIC_META}/loader/{version}")
    if not loaders:
        raise DownloadError(f"Aucun loader Fabric pour {version}")
    loader_ver = loaders[0]["loader"]["version"]
    installer = _get_json(f"{FABRIC_META}/installer")[0]["version"]
    url = f"{FABRIC_META}/loader/{version}/{loader_ver}/{installer}/server/jar"
    return url, f"fabric-server-{version}.jar", "jar"


def forge_download(mc_version: str):
    promos = _get_json(FORGE_PROMOS).get("promos", {})
    forge_ver = promos.get(f"{mc_version}-recommended") or promos.get(f"{mc_version}-latest")
    if not forge_ver:
        raise DownloadError(f"Aucun build Forge pour {mc_version}")
    # Les versions 1.20.3+ n'ont pas de préfixe MC dans le nom de fichier ? Si :
    # le schéma maven reste forge-{mc}-{forge}-installer.jar
    filename = f"forge-{mc_version}-{forge_ver}-installer.jar"
    url = f"{FORGE_MAVEN}/{mc_version}-{forge_ver}/{filename}"
    return url, filename, "installer"


def neoforge_download(mc_version: str):
    r = requests.get(NEOFORGE_META, headers=_UA, timeout=30)
    r.raise_for_status()
    root = ET.fromstring(r.text)
    prefix = _mc_to_neoforge_prefix(mc_version)
    best = None
    for v in root.iter("version"):
        ver = v.text.strip()
        if ver.split("-")[0].startswith(prefix + "."):
            best = ver
    if not best:
        raise DownloadError(f"Aucun build NeoForge pour {mc_version}")
    filename = f"neoforge-{best}-installer.jar"
    url = f"{NEOFORGE_MAVEN}/{best}/{filename}"
    return url, filename, "installer"


def mohist_download(mc_version: str):
    build = _get_json(f"{MOHIST_API}/{mc_version}/builds/latest")
    url = f"{MOHIST_API}/{mc_version}/builds/{build['id']}/download"
    return url, f"mohist-{mc_version}-{build['id']}.jar", "jar"


def get_download(loader: str, mc_version: str):
    """Retourne (url, nom_fichier, kind) où kind vaut 'jar' ou 'installer'."""
    return {
        "paper": paper_download,
        "purpur": purpur_download,
        "fabric": fabric_download,
        "forge": forge_download,
        "neoforge": neoforge_download,
        "mohist": mohist_download,
    }[loader](mc_version)


# ---------------------------------------------------------------- téléchargement

def download_file(url: str, dest: Path, progress_cb=None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, headers=_UA, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done = 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1024 * 256):
                f.write(chunk)
                done += len(chunk)
                if progress_cb:
                    progress_cb(done, total)
    tmp.replace(dest)
    return dest
