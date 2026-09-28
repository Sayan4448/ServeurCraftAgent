"""Import de modpack : analyse des .jar et tri automatique client/serveur.

Stratégie (la plus fiable possible, sans IA) :
1. Hash SHA1 de chaque .jar → requête Modrinth `/v2/version_files` → projet
   → champs `client_side` / `server_side` (`required`/`optional`/`unsupported`).
2. Pour les .jar inconnus de Modrinth : inspection interne du jar —
   `fabric.mod.json` (`"environment"`), `quilt.mod.json`, `META-INF/mods.toml`.
3. En dernier recours : liste de mods connus côté client (sodium, iris…).
"""
import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

import requests

MODRINTH = "https://api.modrinth.com/v2"
HEADERS = {"User-Agent": "ServerCraftAgent/0.20"}

# noms de fichiers de mods connus pour être 100% client (fallback)
CLIENT_HINTS = (
    "sodium", "iris", "optifine", "rubidium", "embeddium", "oculus",
    "dynamic-fps", "dynamicfps", "lambdynamiclights", "entityculling",
    "entity_texture_features", "entity_model_features", "modmenu",
    "reeses", "immediatelyfast", "citresewn", "continuity", "litematica",
    "minihud", "tweakeroo", "xaero", "journeymap", "betterf3",
    "sodium-extra", "irisshaders", "canvas", "moreculling", "zoomify",
    "shulkerboxtooltip", "appleskin", "waila", "wthit", "jade",
    "sound_physics", "presencefootsteps", "ambientsounds", "dynamiccrosshair",
    "fpsreducer", "betterclouds", "waveycapes", "notenoughanimations",
    "skinlayers", "emotecraft", "figura", "chesttracker", "roughtlyenoughitems",
)


def collect_jars(path: Path, workdir: Path | None = None) -> list[Path]:
    """Retourne les .jar d'un dossier, d'un .zip (extrait) ou d'un jar seul."""
    path = Path(path)
    if path.is_dir():
        return sorted(path.rglob("*.jar"))
    if path.suffix.lower() == ".jar":
        return [path]
    if path.suffix.lower() == ".zip":
        tmp = Path(workdir or tempfile.mkdtemp(prefix="modpack_"))
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if name.lower().endswith(".jar") and not name.endswith("/"):
                    out = tmp / Path(name).name
                    out.write_bytes(z.read(name))
        return sorted(tmp.glob("*.jar"))
    return []


def _sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _jar_side(path: Path) -> str | None:
    """'client' | 'server' | 'both' | None — lu dans les métadonnées du jar."""
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            for meta_name in ("fabric.mod.json", "quilt.mod.json"):
                if meta_name in names:
                    try:
                        meta = json.loads(z.read(meta_name))
                    except (ValueError, KeyError):
                        continue
                    env = (meta.get("environment") or
                           meta.get("minecraft", {}).get("environment") or "")
                    env = str(env).lower()
                    if env == "client":
                        return "client"
                    if env == "server":
                        return "server"
                    if env in ("*", ""):
                        return "both"
            if "META-INF/neoforge.mods.toml" in names or \
                    "META-INF/mods.toml" in names:
                return "both"  # Forge/NeoForge : pas de champ fiable
    except (zipfile.BadZipFile, OSError):
        pass
    return None


def _hinted_client(path: Path) -> bool:
    n = path.name.lower()
    return any(h in n for h in CLIENT_HINTS)


def analyze(jars: list[Path]) -> dict:
    """Trie les jars : {'server': [(p, titre)], 'client': [...], 'unknown': ...}"""
    hashes = {p: _sha1(p) for p in jars}
    versions = {}
    if hashes:
        try:
            r = requests.post(
                f"{MODRINTH}/version_files",
                json={"hashes": list(hashes.values()), "algorithm": "sha1"},
                headers=HEADERS, timeout=20)
            versions = r.json() if r.ok else {}
        except requests.RequestException:
            versions = {}

    project_ids = [v["project_id"] for v in versions.values()
                   if "project_id" in v]
    projects = {}
    if project_ids:
        try:
            r = requests.get(
                f"{MODRINTH}/projects",
                params={"ids": json.dumps(project_ids)},
                headers=HEADERS, timeout=15)
            if r.ok:
                projects = {p["id"]: p for p in r.json()}
        except requests.RequestException:
            pass

    out = {"server": [], "client": [], "unknown": []}
    by_hash = {h: p for p, h in hashes.items()}
    for sha, ver in versions.items():
        path = by_hash.get(sha)
        proj = projects.get(ver.get("project_id"), {})
        title = proj.get("title") or path.name
        cs, ss = proj.get("client_side"), proj.get("server_side")
        if ss == "unsupported":
            out["client"].append((path, title))
        elif ss in ("required", "optional"):
            out["server"].append((path, title))
        elif cs == "unsupported":
            out["server"].append((path, title))
        else:
            out["unknown"].append((path, title))

    known = {p for lst in out.values() for p, _t in lst}
    for p in jars:
        if p in known:
            continue
        side = _jar_side(p)
        if side == "client" or _hinted_client(p):
            out["client"].append((p, p.name))
        elif side in ("server", "both"):
            out["server"].append((p, p.name))
        else:
            out["unknown"].append((p, p.name))
    return out


def install(files: list[Path], server_dir: Path, subdir: str = "mods") -> int:
    """Copie les .jar dans server_dir/subdir. Retourne le nombre copié."""
    dest = Path(server_dir) / subdir
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in files:
        try:
            shutil.copy2(f, dest / f.name)
            n += 1
        except OSError:
            pass
    return n
