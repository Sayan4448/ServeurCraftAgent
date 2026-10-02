"""Import de modpack avec tri automatique mods client / mods serveur.

Formats reconnus :
- **.mrpack** (Modrinth) : chaque fichier déclare `env.server` → tri exact.
- **.zip CurseForge** (`manifest.json`) : fichiers téléchargés via l'API
  CurseForge (clé requise), tri par hash SHA1 → Modrinth.
- **Dossier d'instance** Prism / MultiMC / ATLauncher / .minecraft, ou
  **zip de .jar** : tri par hash → Modrinth, puis métadonnées du jar.

Ordre de décision pour un jar sans info fournie par le pack :
1. SHA1 → Modrinth `/version_files` → `client_side` / `server_side` ;
2. métadonnées internes (`fabric.mod.json` → `environment`, etc.) ;
3. liste de mods connus 100 % client (sodium, iris, minimaps…).
"""
import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

import requests

from .downloader import download_file
from .mods import _toml_client_only

MODRINTH = "https://api.modrinth.com/v2"
CURSEFORGE = "https://api.curseforge.com/v1"
FORGECDN = "https://edge.forgecdn.net/files"
HEADERS = {"User-Agent": "ServerCraftAgent/1.0"}

# loaders des packs -> loaders ServerCraft
_MR_LOADERS = {"fabric-loader": "fabric", "quilt-loader": "fabric",
               "forge": "forge", "neoforge": "neoforge"}
_PRISM_LOADERS = {"net.fabricmc.fabric-loader": "fabric",
                  "org.quiltmc.quilt-loader": "fabric",
                  "net.minecraftforge": "forge", "net.neoforged": "neoforge"}

# noms de fichiers de mods connus pour être 100% client (dernier recours)
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
    "skinlayers", "emotecraft", "figura", "chesttracker",
    "roughlyenoughitems", "controlling", "mousetweaks", "betterthirdperson",
    "fancymenu", "drippyloadingscreen", "loadingscreen", "fpsdisplay",
)


class ModpackError(Exception):
    pass


# ================================================================ lecture

def read_pack(path) -> dict:
    """Détecte le format et lit MC / loader / nom. Ne télécharge rien."""
    p = Path(path)
    info = {"path": p, "name": p.stem, "mc_version": None, "loader": None,
            "loader_version": None, "format": "jars"}
    if p.is_dir():
        info["format"] = "folder"
        mmc = p / "mmc-pack.json"
        if mmc.exists():
            try:
                for comp in json.loads(mmc.read_text(encoding="utf-8"))[
                        "components"]:
                    uid = comp.get("uid", "")
                    if uid == "net.minecraft":
                        info["mc_version"] = comp.get("version")
                    elif uid in _PRISM_LOADERS:
                        info["loader"] = _PRISM_LOADERS[uid]
                        info["loader_version"] = comp.get("version")
            except (ValueError, KeyError, OSError):
                pass
        return info
    if not zipfile.is_zipfile(p):
        raise ModpackError("Fichier non reconnu (attendu .mrpack ou .zip).")
    with zipfile.ZipFile(p) as z:
        names = set(z.namelist())
        if "modrinth.index.json" in names:
            idx = json.loads(z.read("modrinth.index.json"))
            deps = idx.get("dependencies", {})
            info.update(format="mrpack", name=idx.get("name", p.stem),
                        mc_version=deps.get("minecraft"))
            for k, v in _MR_LOADERS.items():
                if k in deps:
                    info["loader"] = v
                    info["loader_version"] = deps[k]
            info["files"] = idx.get("files", [])
        elif "manifest.json" in names:
            man = json.loads(z.read("manifest.json"))
            mc = man.get("minecraft", {})
            info.update(format="curseforge", name=man.get("name", p.stem),
                        mc_version=mc.get("version"),
                        overrides=man.get("overrides", "overrides"))
            for ml in mc.get("modLoaders", []):
                lid, _, lver = ml.get("id", "").partition("-")
                if lid in ("forge", "neoforge", "fabric"):
                    info["loader"] = lid
                    info["loader_version"] = lver or None
                    if ml.get("primary"):
                        break
            info["files"] = man.get("files", [])
    return info


# ================================================================ tri

def _sha1_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _modrinth_sides(hashes: list) -> dict:
    """sha1 -> (titre, 'client'|'server'|None) via Modrinth."""
    hashes = [h for h in hashes if h]
    if not hashes:
        return {}
    try:
        r = requests.post(f"{MODRINTH}/version_files",
                          json={"hashes": hashes, "algorithm": "sha1"},
                          headers=HEADERS, timeout=30)
        versions = r.json() if r.ok else {}
        ids = list({v["project_id"] for v in versions.values()
                    if "project_id" in v})
        projects = {}
        for i in range(0, len(ids), 200):
            r = requests.get(f"{MODRINTH}/projects",
                             params={"ids": json.dumps(ids[i:i + 200])},
                             headers=HEADERS, timeout=30)
            if r.ok:
                projects.update({p["id"]: p for p in r.json()})
    except (requests.RequestException, ValueError):
        return {}
    out = {}
    for sha, ver in versions.items():
        proj = projects.get(ver.get("project_id"), {})
        ss, cs = proj.get("server_side"), proj.get("client_side")
        side = ("client" if ss == "unsupported"
                else "server" if ss in ("required", "optional")
                or cs == "unsupported" else None)
        out[sha] = (proj.get("title"), side)
    return out


def _jar_meta_side(data: bytes) -> str | None:
    """'client' | 'server' d'après les métadonnées internes du jar, None si
    elles ne tranchent pas (un mods.toml sans mention ne prouve pas que le
    mod marche sur un serveur : la liste des mods client connus décide)."""
    try:
        import io
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = set(z.namelist())
            for meta_name in ("fabric.mod.json", "quilt.mod.json"):
                if meta_name in names:
                    try:
                        meta = json.loads(z.read(meta_name))
                    except ValueError:
                        continue
                    env = str(meta.get("environment") or meta.get(
                        "minecraft", {}).get("environment") or "").lower()
                    if env == "client":
                        return "client"
                    if env == "server":
                        return "server"
            if "META-INF/neoforge.mods.toml" in names or \
                    "META-INF/mods.toml" in names:
                toml = z.read("META-INF/neoforge.mods.toml"
                              if "META-INF/neoforge.mods.toml" in names
                              else "META-INF/mods.toml").decode(
                    "utf-8", "replace")
                if _toml_client_only(toml):
                    return "client"
    except (zipfile.BadZipFile, OSError, KeyError):
        pass
    return None


def _hint_client(name: str) -> bool:
    n = name.lower()
    return any(h in n for h in CLIENT_HINTS)


def _classify(items: list) -> None:
    """Complète item['side'] ('server'|'client'|'unknown') et item['title']."""
    todo = [it for it in items if not it.get("side")]
    sides = _modrinth_sides([it.get("sha1") for it in todo])
    for it in todo:
        title, side = sides.get(it.get("sha1"), (None, None))
        if title:
            it["title"] = title
        if not side and it.get("data") is not None:
            side = _jar_meta_side(it["data"])
        if not side and _hint_client(it["name"]):
            side = "client"
        it["side"] = side or it.get("default") or "unknown"


# ================================================================ plan

def plan(pack: dict, cf_key: str = "", log=print) -> dict:
    """Construit la liste des mods à installer, triée client / serveur.

    Chaque élément : {name, title, dest (chemin relatif), side, url|data}.
    """
    fmt = pack["format"]
    items, overrides = [], []
    p = Path(pack["path"])

    if fmt == "mrpack":
        for f in pack.get("files", []):
            rel = f.get("path", "")
            if not _safe(rel):
                continue
            env = f.get("env") or {}
            server = env.get("server", "required")
            name = PurePosixPath(rel).name
            items.append({
                "name": name, "title": name, "dest": rel,
                "url": (f.get("downloads") or [None])[0],
                "sha1": (f.get("hashes") or {}).get("sha1"),
                # le pack peut se tromper : on revérifie via Modrinth,
                # « serveur » par défaut si Modrinth ne connaît pas le mod
                "side": "client" if server == "unsupported" else None,
                "default": "server",
            })
        overrides = [("overrides/", ""), ("server-overrides/", "")]

    elif fmt == "curseforge":
        from . import mods as mods_mod
        ids =[f["fileID"] for f in pack.get("files", [])
               if f.get("required", True) and "fileID" in f]
        log(f"CurseForge : résolution de {len(ids)} fichier(s)…")
        data = []
        for i in range(0, len(ids), 500):
            try:                      # clé refusée, quota, réseau…
                data += mods_mod.cf_request(
                    "POST", "/mods/files", cf_key, timeout=60,
                    json={"fileIds": ids[i:i + 500]}).get("data", [])
            except mods_mod.ModError as e:
                raise ModpackError(str(e)) from e
        for f in data:
            fid = str(f["id"])
            url = f.get("downloadUrl") or \
                f"{FORGECDN}/{fid[:4]}/{int(fid[4:])}/{f['fileName']}"
            sha1 = next((h["value"] for h in f.get("hashes", [])
                         if h.get("algo") == 1), None)
            items.append({"name": f["fileName"], "title": f.get(
                "displayName", f["fileName"]), "dest": f"mods/{f['fileName']}",
                "url": url, "sha1": sha1})
        ov = pack.get("overrides", "overrides").rstrip("/") + "/"
        overrides = [(ov, "")]

    elif fmt == "folder":
        base = next((d for d in (p / ".minecraft", p / "minecraft", p)
                     if (d / "mods").is_dir()), p)
        jars = sorted((base / "mods").glob("*.jar")) if \
            (base / "mods").is_dir() else sorted(p.rglob("*.jar"))
        for j in jars:
            data = j.read_bytes()
            items.append({"name": j.name, "title": j.name,
                          "dest": f"mods/{j.name}", "data": data,
                          "sha1": _sha1_bytes(data)})
        pack["_config_dir"] = base / "config"

    else:                             # zip de jars
        with zipfile.ZipFile(p) as z:
            for n in z.namelist():
                if n.lower().endswith(".jar") and not n.endswith("/"):
                    data = z.read(n)
                    name = PurePosixPath(n).name
                    items.append({"name": name, "title": name,
                                  "dest": f"mods/{name}", "data": data,
                                  "sha1": _sha1_bytes(data)})

    # jars livrés dans les overrides (mrpack/CF) : à trier aussi
    if overrides and zipfile.is_zipfile(p):
        with zipfile.ZipFile(p) as z:
            for n in z.namelist():
                for prefix, _ in overrides:
                    rel = n[len(prefix):]
                    if n.startswith(prefix) and rel.startswith("mods/") \
                            and rel.endswith(".jar") and _safe(rel):
                        data = z.read(n)
                        items.append({"name": PurePosixPath(rel).name,
                                      "title": PurePosixPath(rel).name,
                                      "dest": rel, "data": data,
                                      "sha1": _sha1_bytes(data)})
    log(f"Analyse de {len(items)} mod(s)…")
    _classify(items)
    groups = {"server": [], "client": [], "unknown": []}
    for it in items:
        groups[it["side"]].append(it)
    return {"pack": pack, "overrides": overrides, **groups}


def _safe(rel: str) -> bool:
    parts = PurePosixPath(rel).parts
    return bool(parts) and ".." not in parts and not rel.startswith("/") \
        and ":" not in rel


# ================================================================ installation

def apply_plan(pl: dict, server_dir: Path, include_client: bool = False,
               log=print) -> dict:
    """Installe les mods serveur + indéterminés (+ client si demandé) et
    copie les fichiers de config du pack. Retourne les compteurs."""
    server_dir = Path(server_dir)
    todo = pl["server"] + pl["unknown"] + (pl["client"] if include_client
                                           else [])
    ok, failed = 0, []
    for i, it in enumerate(todo, 1):
        dest = server_dir / it["dest"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            if it.get("data") is not None:
                dest.write_bytes(it["data"])
            elif it.get("url"):
                download_file(it["url"], dest)
            else:
                raise ModpackError("aucune source")
            ok += 1
            if i % 10 == 0 or i == len(todo):
                log(f"  {i}/{len(todo)} mod(s) installé(s)")
        except Exception as e:  # noqa: BLE001
            failed.append(f"{it['name']} ({e})")
    # fichiers de configuration du pack (hors mods, déjà traités)
    p = Path(pl["pack"]["path"])
    copied = 0
    if pl["overrides"] and zipfile.is_zipfile(p):
        with zipfile.ZipFile(p) as z:
            for n in z.namelist():
                for prefix, _ in pl["overrides"]:
                    rel = n[len(prefix):]
                    if n.startswith(prefix) and rel and not n.endswith("/") \
                            and not rel.startswith("mods/") and _safe(rel):
                        out = server_dir / rel
                        out.parent.mkdir(parents=True, exist_ok=True)
                        out.write_bytes(z.read(n))
                        copied += 1
    cfg = pl["pack"].get("_config_dir")
    if cfg and Path(cfg).is_dir():
        shutil.copytree(cfg, server_dir / "config", dirs_exist_ok=True)
        copied += sum(1 for _ in Path(cfg).rglob("*") if _.is_file())
    if copied:
        log(f"  {copied} fichier(s) de configuration copié(s)")
    for f in failed[:10]:
        log(f"  ⚠ échec : {f}")
    return {"installed": ok, "failed": len(failed),
            "client_skipped": 0 if include_client else len(pl["client"]),
            "configs": copied}


# ------------------------------------------------ compatibilité (v0.20)

def collect_jars(path: Path, workdir: Path | None = None) -> list:
    path = Path(path)
    if path.is_dir():
        return sorted(path.rglob("*.jar"))
    if path.suffix.lower() == ".jar":
        return [path]
    if zipfile.is_zipfile(path):
        tmp = Path(workdir or tempfile.mkdtemp(prefix="modpack_"))
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if name.lower().endswith(".jar") and not name.endswith("/"):
                    (tmp / Path(name).name).write_bytes(z.read(name))
        return sorted(tmp.glob("*.jar"))
    return []


def analyze(jars: list) -> dict:
    items = []
    for j in jars:
        data = Path(j).read_bytes()
        items.append({"name": Path(j).name, "title": Path(j).name,
                      "path": Path(j), "data": data,
                      "sha1": _sha1_bytes(data)})
    _classify(items)
    out = {"server": [], "client": [], "unknown": []}
    for it in items:
        out[it["side"]].append((it["path"], it.get("title") or it["name"]))
    return out


def install(files: list, server_dir: Path, subdir: str = "mods") -> int:
    dest = Path(server_dir) / subdir
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in files:
        try:
            shutil.copy2(f, dest / Path(f).name)
            n += 1
        except OSError:
            pass
    return n
