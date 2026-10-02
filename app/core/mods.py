"""Mods & plugins : sources Modrinth + CurseForge, install, et Playit.gg."""
import hashlib
import json
from pathlib import Path

import requests

from ..i18n import t
from .downloader import MOD_LOADERS, PLUGIN_LOADERS, download_file
from .properties import load_properties, save_properties

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
    "paper": ["paper", "spigot", "bukkit"],
    "purpur": ["purpur", "paper", "spigot", "bukkit"],
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


# Origine des fichiers installés par l'app : {"plugins/X.jar": {"source":
# "modrinth", "project": "<id>"}} — sert à remplacer l'ancienne version d'un
# projet au lieu de laisser deux jars du même mod côte à côte.
MANIFEST = ".servercraft-mods.json"


class ModError(Exception):
    pass


def explain(e: Exception) -> str:
    """Message lisible pour une erreur de téléchargement / d'API."""
    if isinstance(e, ModError):
        return str(e)
    if isinstance(e, requests.Timeout):
        return t("net_err_timeout")
    if isinstance(e, requests.ConnectionError):
        return t("net_err_offline")
    if isinstance(e, requests.HTTPError) and e.response is not None:
        return t("net_err_http", code=e.response.status_code)
    return str(e)


# ------------------------------------------------- suivi des installations

def _manifest(server_dir: Path) -> dict:
    try:
        data = json.loads((Path(server_dir) / MANIFEST).read_text(
            encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _identify_modrinth(folder: Path, known: set) -> dict:
    """{nom de fichier: id de projet Modrinth, ou "" si Modrinth ne le
    connaît pas} pour les jars du dossier pas encore suivis (installés à la
    main ou par une ancienne version). Vide si Modrinth est injoignable."""
    hashes = {}
    for f in folder.glob("*.jar"):
        if f.name not in known:
            try:
                hashes[_sha1(f)] = f.name
            except OSError:
                pass
    if not hashes:
        return {}
    try:
        r = requests.post(f"{MODRINTH_API}/version_files",
                          json={"hashes": list(hashes), "algorithm": "sha1"},
                          headers=_UA, timeout=20)
        r.raise_for_status()
        found = r.json()
    except (requests.RequestException, ValueError):
        return {}
    return {name: str((found.get(h) or {}).get("project_id") or "")
            for h, name in hashes.items()}


def record_install(server_dir: Path, dest: Path, source: str,
                   project) -> list:
    """Note l'origine de `dest` et retire les autres versions du même projet
    dans le même dossier (deux jars du même mod font planter le serveur).
    Retourne les noms des fichiers retirés ; un fichier verrouillé par un
    serveur lancé est laissé en place."""
    server_dir, dest = Path(server_dir), Path(dest)
    project = str(project)
    folder = dest.parent
    sub = folder.name
    data = {rel: info for rel, info in _manifest(server_dir).items()
            if (server_dir / rel).exists()}
    if source == "modrinth":
        known = {Path(rel).name for rel in data
                 if Path(rel).parent.name == sub}
        for name, pid in _identify_modrinth(folder,
                                            known | {dest.name}).items():
            data[f"{sub}/{name}"] = {"source": "modrinth" if pid else "other",
                                     "project": pid}
    removed = []
    for rel, info in list(data.items()):
        f = server_dir / rel
        if f == dest or f.parent != folder or \
                info.get("source") != source or \
                str(info.get("project")) != project:
            continue
        try:
            f.unlink()
        except OSError:
            continue
        removed.append(f.name)
        del data[rel]
    data[f"{sub}/{dest.name}"] = {"source": source, "project": project}
    try:
        (server_dir / MANIFEST).write_text(json.dumps(data, indent=2),
                                           encoding="utf-8")
    except OSError:
        pass
    return removed


def _best_version(versions: list) -> dict:
    """Version la plus récente, en préférant une release stable à une
    bêta / alpha plus récente (la liste est déjà triée par date)."""
    for kind in ("release", "beta", "alpha"):
        for v in versions:
            if v.get("version_type", "release") == kind:
                return v
    return versions[0]


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
    loaders = _loaders_for(loader, kind)
    # Modrinth : éléments d'une même sous-liste = OU logique
    facets.append([f"categories:{l}" for l in loaders])
    facets.append(["server_side!=unsupported"])   # pas de mod 100 % client
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
            "url": f"https://modrinth.com/{'plugin' if kind == 'plugin' else 'mod'}/{h['slug']}",
        }
        for h in r.json().get("hits", [])
    ]


def _modrinth_versions(project: str, loaders: list, mc_version: str) -> list:
    """Versions du projet pour ce loader ET cette version de Minecraft.
    Aucun repli sur un autre loader : un jar Fabric ou Paper posé dans un
    serveur Forge l'empêche de démarrer."""
    r = requests.get(
        f"{MODRINTH_API}/project/{project}/version",
        params={"loaders": json.dumps(loaders),
                "game_versions": json.dumps([mc_version])},
        headers=_UA, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def _loaders_for(loader: str, kind: str) -> list:
    # mohist : mods = forge ; plugins = bukkit/paper
    if loader == "mohist":
        return ["forge"] if kind == "mod" else ["bukkit", "paper", "spigot"]
    return LOADER_MAP.get(loader, [loader])


def _required_deps(version: dict) -> list:
    return [str(d["project_id"]) for d in version.get("dependencies") or []
            if d.get("dependency_type") == "required" and d.get("project_id")]


def _install_deps(deps: list, parent: str, dest: Path, server_dir: Path,
                  loader: str, mc_version: str, kind: str, seen: set,
                  replaced: list | None, log=None) -> None:
    """Installe les dépendances obligatoires absentes. Si l'une d'elles est
    introuvable, `dest` est retiré : le mod seul ferait planter le serveur."""
    have = _installed_projects(server_dir)
    for pid in deps:
        if pid in seen or pid in have:
            continue
        try:
            got = install_modrinth(pid, server_dir, loader, mc_version, kind,
                                   replaced=replaced, _seen=seen, log=log)
        except (ModError, requests.RequestException) as e:
            dest.unlink(missing_ok=True)
            raise ModError(t("mod_err_dep", name=parent,
                             e=explain(e))) from e
        if log:
            log(t("mod_dep_added", name=got.name))


def _installed_projects(server_dir: Path) -> set:
    return {str(info.get("project")) for rel, info in
            _manifest(server_dir).items() if (Path(server_dir) / rel).exists()}


def _server_side(project: str) -> str:
    """`server_side` du projet Modrinth ("" si inconnu ou injoignable)."""
    try:
        r = requests.get(f"{MODRINTH_API}/project/{project}", headers=_UA,
                         timeout=15)
        r.raise_for_status()
        return str(r.json().get("server_side") or "")
    except (requests.RequestException, ValueError):
        return ""


def install_modrinth(project_slug: str, server_dir: Path, loader: str,
                     mc_version: str, kind: str, progress_cb=None,
                     replaced: list | None = None, _seen: set | None = None,
                     log=None) -> Path:
    """Installe la dernière version compatible (release de préférence) et
    ses dépendances obligatoires (ViaFabric pour ViaVersion, Fabric API…) :
    sans elles le serveur refuse de démarrer.
    `replaced` : liste complétée avec les anciennes versions retirées."""
    versions = _modrinth_versions(project_slug, _loaders_for(loader, kind),
                                  mc_version)
    if not versions:
        raise ModError(t("mod_err_noversion", name=project_slug,
                         loader=loader, mc=mc_version))
    version = _best_version(versions)
    jar = _pick_jar(version.get("files", []))
    if not jar:
        raise ModError(f"{project_slug} : aucun fichier .jar téléchargeable")
    project = str(version.get("project_id") or project_slug)
    seen = _seen if _seen is not None else set()
    if _seen is None and kind == "mod" and             _server_side(project) == "unsupported":
        raise ModError(t("mod_err_client", name=project_slug))
    seen.add(project)
    dest = target_dir(server_dir, loader, kind) / jar["filename"]
    download_file(jar["url"], dest, progress_cb)
    old = record_install(server_dir, dest, "modrinth", project)
    if replaced is not None:
        replaced += old
    _install_deps(_required_deps(version), project_slug, dest, server_dir,
                  loader, mc_version, kind, seen, replaced, log)
    return dest


# ----------------------------------------------------------------- CurseForge

def _cf_headers(api_key: str) -> dict:
    return {**_UA, "x-api-key": api_key, "Accept": "application/json"}


def cf_request(method: str, path: str, api_key: str, timeout: float = 20,
               **kw):
    """Appel à l'API CurseForge -> JSON. Toute erreur devient une ModError
    au message clair (clé absente, refusée, pas de réseau, quota, panne) ;
    la clé n'apparaît jamais dans le message."""
    key = (api_key or "").strip()
    if not key:
        raise ModError(t("cf_err_nokey"))
    try:
        r = requests.request(method, f"{CURSEFORGE_API}{path}",
                             headers=_cf_headers(key), timeout=timeout, **kw)
    except requests.Timeout as e:
        raise ModError(t("net_err_timeout")) from e
    except requests.RequestException as e:
        raise ModError(t("cf_err_net")) from e
    if r.status_code in (401, 403):
        raise ModError(t("cf_err_key"))
    if r.status_code == 429:
        raise ModError(t("cf_err_rate"))
    if r.status_code == 404:
        raise ModError(t("cf_err_notfound"))
    if not r.ok:
        raise ModError(t("cf_err_down", code=r.status_code))
    try:
        return r.json()
    except ValueError as e:
        raise ModError(t("cf_err_down", code=r.status_code)) from e


def check_curseforge_key(api_key: str) -> None:
    """Vérifie la clé auprès de CurseForge ; lève ModError si elle est
    absente, invalide ou expirée, ou si le service est injoignable."""
    cf_request("GET", "/games/432", api_key, timeout=10)


def search_curseforge(query: str, loader: str, mc_version: str,
                      kind: str, api_key: str, limit: int = 20,
                      offset: int = 0) -> list:
    """Recherche CurseForge. Nécessite une clé API (console.curseforge.com)."""
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
    data = cf_request("GET", "/mods/search", api_key, params=params)
    out = []
    for m in data.get("data", []):
        out.append({
            "id": m["id"], "slug": m.get("slug", str(m["id"])),
            "title": m["name"], "description": (m.get("summary") or "")[:200],
            "downloads": m.get("downloadCount", 0),
            "author": ", ".join(a["name"] for a in m.get("authors", [])),
            "source": "curseforge", "kind": kind,
            "icon": (m.get("logo") or {}).get("thumbnailUrl", ""),
            "url": (m.get("links") or {}).get("websiteUrl", ""),
        })
    return out


# ------------------------------------------------------- détails d'un projet

def modrinth_project(slug: str) -> dict:
    """Fiche complète Modrinth : description longue, galerie, liens."""
    r = requests.get(f"{MODRINTH_API}/project/{slug}", headers=_UA, timeout=20)
    r.raise_for_status()
    p = r.json()
    return {
        "title": p["title"], "description": p.get("description", ""),
        "body": p.get("body", ""),
        "author": "", "downloads": p.get("downloads", 0),
        "followers": p.get("followers", 0),
        "icon": p.get("icon_url", ""),
        "categories": p.get("categories", []),
        "gallery": [g["url"] for g in p.get("gallery", [])][:8],
        "url": (f"https://modrinth.com/{p.get('project_type', 'mod')}"
                f"/{p['slug']}"),
        "source_url": (p.get("source_url") or p.get("issues_url") or ""),
        "license": (p.get("license") or {}).get("id", ""),
    }


def curseforge_project(mod_id: int, api_key: str) -> dict:
    """Fiche CurseForge : description HTML brute → texte, screenshots, liens."""
    m = cf_request("GET", f"/mods/{mod_id}", api_key)["data"]
    body = ""
    try:
        d = cf_request("GET", f"/mods/{mod_id}/description", api_key)
        import re as _re
        body = _re.sub(r"<[^>]+>", " ", d.get("data", "") or "")
        body = _re.sub(r"\s+", " ", body).strip()
    except ModError:
        pass
    return {
        "title": m["name"], "description": m.get("summary", ""),
        "body": body,
        "author": ", ".join(a["name"] for a in m.get("authors", [])),
        "downloads": m.get("downloadCount", 0), "followers": 0,
        "icon": (m.get("logo") or {}).get("url", ""),
        "categories": [c["name"] for c in m.get("categories", [])],
        "gallery": [s["url"] for s in m.get("screenshots", [])][:8],
        "url": (m.get("links") or {}).get("websiteUrl", ""),
        "source_url": (m.get("links") or {}).get("sourceUrl", ""),
        "license": "",
    }


def project_details(result: dict, api_key: str = "") -> dict:
    if result["source"] == "curseforge":
        return curseforge_project(result["id"], api_key)
    return modrinth_project(result["slug"])


def install_curseforge(mod_id: int, server_dir: Path, loader: str,
                       mc_version: str, kind: str, api_key: str,
                       progress_cb=None,
                       replaced: list | None = None) -> Path:
    params = {"pageSize": 50}
    if mc_version:
        params["gameVersion"] = mc_version
    if kind == "mod" and loader in CF_MODLOADER:
        params["modLoaderType"] = CF_MODLOADER[loader]
    files = cf_request("GET", f"/mods/{mod_id}/files", api_key,
                       params=params).get("data", [])
    if not files:
        raise ModError(f"CurseForge mod {mod_id} : aucun fichier compatible.")
    # releaseType : 1 = release, 2 = bêta, 3 = alpha
    f = min(files, key=lambda x: x.get("releaseType") or 1)
    url = f.get("downloadUrl")
    if not url:
        # Distribution restreinte : URL forgecdn reconstruite
        fid = str(f["id"])
        url = f"{FORGECDN}/{fid[:4]}/{int(fid[4:])}/{f['fileName']}"
    dest = target_dir(server_dir, loader, kind) / f["fileName"]
    download_file(url, dest, progress_cb)
    old = record_install(server_dir, dest, "curseforge", mod_id)
    if replaced is not None:
        replaced += old
    return dest


def install_result(result: dict, server_dir: Path, loader: str,
                   mc_version: str, api_key: str = "", progress_cb=None,
                   replaced: list | None = None) -> Path:
    if result["source"] == "curseforge":
        return install_curseforge(result["id"], server_dir, loader,
                                  mc_version, result["kind"], api_key,
                                  progress_cb, replaced)
    return install_modrinth(result["slug"], server_dir, loader,
                            mc_version, result["kind"], progress_cb,
                            replaced)


# ------------------------------------------------- versions par projet + dl

def _pick_jar(files: list):
    return next((f for f in files if f.get("primary")), None) or next(
        (f for f in files if f["filename"].endswith(".jar")), None)


def modrinth_version_list(project_slug: str, loader: str,
                          mc_version: str, kind: str) -> list:
    """Toutes les versions d'un projet compatibles loader/MC, plus récentes
    d'abord. Chaque entrée : name, date, game_versions, release_type, url,
    filename."""
    out = []
    for v in _modrinth_versions(project_slug, _loaders_for(loader, kind),
                                mc_version):
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
            "deps": _required_deps(v),
        })
    return out


def curseforge_version_list(mod_id: int, loader: str, mc_version: str,
                            kind: str, api_key: str) -> list:
    params = {"pageSize": 50}
    if mc_version:
        params["gameVersion"] = mc_version
    if kind == "mod" and loader in CF_MODLOADER:
        params["modLoaderType"] = CF_MODLOADER[loader]
    data = cf_request("GET", f"/mods/{mod_id}/files", api_key, params=params)
    types = {1: "release", 2: "beta", 3: "alpha"}
    out = []
    for f in data.get("data", []):
        url = f.get("downloadUrl")
        if not url:
            fid = str(f["id"])
            url = f"{FORGECDN}/{fid[:4]}/{int(fid[4:])}/{f['fileName']}"
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
                kind: str, progress_cb=None, result: dict | None = None,
                replaced: list | None = None, deps: list | None = None,
                mc_version: str = "") -> Path:
    """Télécharge une version précise. `result` (résultat de recherche) :
    permet de remplacer la version déjà installée du même projet.
    `deps` : projets Modrinth obligatoires de cette version, installés s'ils
    manquent (pour `mc_version`)."""
    dest = target_dir(server_dir, loader, kind) / filename
    download_file(url, dest, progress_cb)
    if result:
        old = record_install(server_dir, dest, result["source"],
                             result["id"])
        if replaced is not None:
            replaced += old
    if deps and mc_version:
        _install_deps(deps, filename, dest, server_dir, loader, mc_version,
                      kind, {str(result["id"])} if result else set(),
                      replaced)
    return dest


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
    versions = _modrinth_versions(project, _loaders_for(loader, kind),
                                  mc_version)
    if not versions:
        raise ModError(
            f"{VOICE_LABELS[which]} : aucune version trouvée pour {loader} {mc_version}"
        )
    version = _best_version(versions)
    jar = _pick_jar(version.get("files", []))
    if not jar:
        raise ModError(f"{VOICE_LABELS[which]} : aucun fichier .jar téléchargeable")

    dest = target_dir(server_dir, loader, kind) / jar["filename"]
    download_file(jar["url"], dest, progress_cb)
    record_install(server_dir, dest, "modrinth",
                   version.get("project_id") or project)
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
