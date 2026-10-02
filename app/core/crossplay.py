"""Cross-play Java ⇄ Bedrock et authentification premium/crack.

Architecture (automatique, rien à configurer) :
- **Geyser Standalone** : proxy Bedrock → Java lancé à côté du serveur
  (dossier `geyser/`), démarré au « Done » du serveur et arrêté avec lui.
  Indépendant de l'API Paper/Fabric → fonctionne sur toutes les versions
  et tous les loaders.
- **Floodgate** (plugin/mod sur le serveur quand disponible) : les joueurs
  Bedrock entrent sans compte Java, même en mode Premium. Sa clé `key.pem`
  est copiée automatiquement vers Geyser.
- **ViaVersion + ViaBackwards** (ViaFabric sur Fabric) : Geyser parle
  toujours la dernière version de Java ; ils lui permettent de rejoindre un
  serveur d'une autre version.
- **ViaProxy** : même traduction, mais hors du serveur — pour ceux qui ne
  peuvent pas porter ViaVersion (Forge, NeoForge, versions ≤ 1.17 qui
  tournent sous un Java trop ancien). Chaîne : Bedrock → Geyser → ViaProxy
  → serveur. Sans lui, le serveur répond « Client incompatible ».
- **AuthMe** (plugins) / **EasyAuth** (Fabric) : mot de passe pour les
  comptes crack quand le serveur accepte premium ET crack.
"""
import re
import shutil
import socket
import subprocess
import time
import zipfile
from pathlib import Path

import requests

from . import java as java_mod
from . import mods as mods_mod
from .downloader import download_file

GEYSER_BUILD = ("https://download.geysermc.org/v2/projects/{p}/versions/"
                "latest/builds/latest")
GEYSER_URL = GEYSER_BUILD + "/downloads/{plat}"
VIAPROXY_RELEASE = ("https://api.github.com/repos/ViaVersion/ViaProxy/"
                    "releases/latest")
VIAPROXY_DIR = "viaproxy"
_UA = {"User-Agent": "ServerCraftAgent (local server manager)"}
BEDROCK_PORT = 19132
GEYSER_DIR = "geyser"
GEYSER_JAR = "Geyser-Standalone.jar"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# fichiers ajoutés par le cross-play (pour la désinstallation)
_OURS = ("geyser", "floodgate", "viaversion", "viabackwards", "viafabric")
_VIA = ("viaversion", "viafabric")


class CrossplayError(Exception):
    pass


def supported(loader: str) -> bool:
    return True                       # Geyser Standalone : tous les loaders


def installed(server_dir: Path) -> bool:
    return (Path(server_dir) / GEYSER_DIR / GEYSER_JAR).exists()


def geyser_dir(server_dir: Path) -> Path:
    return Path(server_dir) / GEYSER_DIR


def _floodgate_key(server_dir: Path) -> Path | None:
    for rel in ("plugins/floodgate/key.pem", "config/floodgate/key.pem"):
        p = Path(server_dir) / rel
        if p.exists():
            return p
    return None


def _has_floodgate(server_dir: Path) -> bool:
    for sub in ("plugins", "mods"):
        d = Path(server_dir) / sub
        if d.exists() and any(f.name.lower().startswith("floodgate")
                              for f in d.glob("*.jar")):
            return True
    return False


def _has_via(server_dir: Path) -> bool:
    for sub in ("plugins", "mods"):
        d = Path(server_dir) / sub
        if d.exists() and any(f.name.lower().startswith(_VIA)
                              for f in d.glob("*.jar")):
            return True
    return False


def _via_possible(loader: str, mc_version: str) -> bool:
    """ViaVersion peut tourner dans ce serveur : il existe pour les plugins
    et Fabric, et demande Java 17 (donc Minecraft 1.18+)."""
    return (mods_mod.supports_plugins(loader) or loader == "fabric") and \
        java_mod.required_java_major(mc_version) >= 17


def needs_proxy(server_dir: Path, loader: str, mc_version: str) -> bool:
    """Geyser doit passer par ViaProxy pour joindre ce serveur."""
    return not (_via_possible(loader, mc_version) and _has_via(server_dir))


def proxy_java(log=print) -> Path:
    """Java pour Geyser et ViaProxy (17+) : celui d'un vieux serveur
    (Java 8) ne les lance pas."""
    return java_mod.ensure_java("1.21", log=log)


def _remove_plugin_geyser(server_dir: Path) -> None:
    """Retire un éventuel Geyser en plugin/mod (incompatible selon versions)."""
    for sub in ("plugins", "mods"):
        d = Path(server_dir) / sub
        if d.exists():
            for f in d.glob("*.jar"):
                if f.name.lower().startswith("geyser"):
                    f.unlink(missing_ok=True)


# ------------------------------------------------------------ installation

def install(server_dir: Path, loader: str, mc_version: str, java=None,
            log=print) -> None:
    """`java` : ignoré (Geyser a son propre Java, voir proxy_java)."""
    server_dir = Path(server_dir)
    gdir = geyser_dir(server_dir)
    gdir.mkdir(parents=True, exist_ok=True)
    _remove_plugin_geyser(server_dir)

    log("Cross-play : téléchargement de Geyser (proxy Bedrock)…")
    download_file(GEYSER_URL.format(p="geyser", plat="standalone"),
                  gdir / GEYSER_JAR)

    if _via_possible(loader, mc_version):
        _install_server_side(server_dir, loader, mc_version, log)
    else:
        log("Cross-play : ViaProxy (traduction de version)…")
        ensure_viaproxy()

    log("Cross-play : génération de la configuration Geyser…")
    _generate_config(gdir, proxy_java(log))
    log(f"✔ Cross-play installé — Bedrock : port UDP {BEDROCK_PORT}")


def _install_server_side(server_dir: Path, loader: str, mc_version: str,
                         log) -> None:
    # Floodgate côté serveur : Bedrock sans compte Java
    try:
        if mods_mod.supports_plugins(loader):
            log("Cross-play : Floodgate…")
            download_file(GEYSER_URL.format(p="floodgate", plat="spigot"),
                          server_dir / "plugins" / "Floodgate-Spigot.jar")
        elif loader == "fabric":
            log("Cross-play : Floodgate…")
            mods_mod.install_modrinth("floodgate", server_dir, loader,
                                      mc_version, "mod", log=log)
            mods_mod.install_modrinth("fabric-api", server_dir, loader,
                                      mc_version, "mod", log=log)
    except (mods_mod.ModError, requests.RequestException) as e:
        log(f"  ⚠ Floodgate non installé ({e}) — les joueurs Bedrock "
            "utiliseront leur pseudo Xbox en mode hors-ligne.")

    # Geyser parle la dernière version de Java : Via traduit pour le serveur.
    # Sur Fabric, ViaVersion ne se charge qu'avec ViaFabric.
    plugins = mods_mod.supports_plugins(loader)
    for slug in (("viaversion", "viabackwards") if plugins
                 else ("viafabric", "viabackwards")):
        try:
            mods_mod.install_modrinth(slug, server_dir, loader, mc_version,
                                      "plugin" if plugins else "mod", log=log)
        except (mods_mod.ModError, requests.RequestException) as e:
            # sans Via, le démarrage passe par ViaProxy (needs_proxy)
            log(f"  ⚠ {slug} non installé : {e}")


def _generate_config(gdir: Path, java, timeout: float = 60) -> bool:
    """Lance Geyser une fois pour qu'il écrive sa config.yml, puis l'arrête."""
    cfg = gdir / "config.yml"
    if cfg.exists():
        return True
    p = subprocess.Popen([str(java), "-jar", GEYSER_JAR, "--nogui"],
                         cwd=str(gdir), stdin=subprocess.PIPE,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=NO_WINDOW)
    t0 = time.time()
    while time.time() - t0 < timeout and not cfg.exists():
        time.sleep(0.5)
    time.sleep(1.0)
    p.kill()
    p.wait()
    return cfg.exists()


def uninstall(server_dir: Path, loader: str = "") -> int:
    """Retire les jars du cross-play. Lève CrossplayError si un fichier est
    verrouillé (serveur lancé) : rien d'autre n'est alors supprimé."""
    jars = [f for sub in ("plugins", "mods")
            for f in (Path(server_dir) / sub).glob("*.jar")
            if f.name.lower().startswith(_OURS)]
    for f in jars:
        try:                          # ouvert en écriture = pas verrouillé
            with open(f, "ab"):
                pass
        except OSError as e:
            raise CrossplayError(f.name) from e
    for f in jars:
        f.unlink(missing_ok=True)
    shutil.rmtree(geyser_dir(server_dir), ignore_errors=True)
    return len(jars)


# ------------------------------------------------------------ configuration

def configure(server_dir: Path, java_port: int, accounts: str,
              proxy: bool = False) -> str:
    """Met à jour la config Geyser (port Java, authentification, clé
    Floodgate). Retourne l'auth-type utilisé. `proxy` : Geyser passe par
    ViaProxy, qui ne transmet pas l'identité Floodgate."""
    gdir = geyser_dir(server_dir)
    cfg = gdir / "config.yml"
    key = _floodgate_key(server_dir)
    if not proxy and key and _has_floodgate(server_dir):
        shutil.copy2(key, gdir / "key.pem")
        auth = "floodgate"
    elif accounts == "premium":
        auth = "online"               # Bedrock doit lier un compte Java
    else:
        auth = "offline"
    if cfg.exists():
        src = cfg.read_text(encoding="utf-8", errors="replace")
        new = re.sub(r"(?m)^(\s*auth-type:\s*)\S+", rf"\g<1>{auth}", src)
        # section java/remote : le port 25565 par défaut → port du serveur
        new = _set_java_port(new, java_port)
        new = re.sub(r"(?m)^(\s*passthrough-motd:\s*)\S+", r"\g<1>true", new)
        if new != src:
            cfg.write_text(new, encoding="utf-8")
    return auth


def _set_java_port(text: str, port: int) -> str:
    """Remplace `port:` dans la section `java:` (ou `remote:` anciens formats)."""
    out, section = [], None
    for line in text.splitlines(keepends=True):
        m = re.match(r"^(\w[\w-]*):\s*$", line)
        if m:
            section = m.group(1)
        if section in ("java", "remote"):
            line = re.sub(r"^(\s+port:\s*)\d+", rf"\g<1>{port}", line)
        out.append(line)
    return "".join(out)


def launch(server_dir: Path, java) -> subprocess.Popen:
    gdir = geyser_dir(server_dir)
    return subprocess.Popen(
        [str(java), "-Dfile.encoding=UTF-8", "-Dstdout.encoding=UTF-8",
         "-Dstderr.encoding=UTF-8", "-Xmx512M", "-jar", GEYSER_JAR, "--nogui"],
        cwd=str(gdir), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8",
        errors="replace", bufsize=1, creationflags=NO_WINDOW)


# ------------------------------------------------------------ mises à jour

def _geyser_build(jar: Path) -> int:
    try:
        with zipfile.ZipFile(jar) as z:
            m = re.search(r"git\.build\.number=(\d+)",
                          z.read("git.properties").decode("utf-8", "replace"))
        return int(m.group(1)) if m else 0
    except (OSError, KeyError, zipfile.BadZipFile):
        return 0


def update_geyser(server_dir: Path, log=print) -> bool:
    """Télécharge le dernier Geyser s'il a changé. Bedrock se met à jour
    tout seul sur les téléphones et consoles : un Geyser resté à l'ancienne
    version refuse alors les joueurs (« Outdated Geyser proxy »). Sans
    réseau, l'ancien fichier est gardé."""
    jar = geyser_dir(server_dir) / GEYSER_JAR
    try:
        r = requests.get(GEYSER_BUILD.format(p="geyser"), headers=_UA,
                         timeout=8)
        r.raise_for_status()
        latest = int(r.json().get("build") or 0)
        if not latest or latest <= _geyser_build(jar):
            return False
        log(f"── Cross-play : mise à jour de Geyser (build {latest})… ──")
        download_file(GEYSER_URL.format(p="geyser", plat="standalone"), jar)
        return True
    except (requests.RequestException, ValueError, OSError):
        return False


# ---------------------------------------------------------------- ViaProxy

def _viaproxy_home() -> Path:
    return java_mod.RUNTIMES_DIR / VIAPROXY_DIR


def ensure_viaproxy() -> Path:
    """Dernier ViaProxy (partagé par tous les serveurs). Il doit suivre
    Geyser : une version plus ancienne ne connaît pas son protocole. Sans
    réseau, la version déjà téléchargée est utilisée."""
    home = _viaproxy_home()
    local = sorted(home.glob("ViaProxy-*.jar"))
    try:
        r = requests.get(VIAPROXY_RELEASE, headers=_UA, timeout=8)
        r.raise_for_status()
        asset = next(a for a in r.json().get("assets", [])
                     if a["name"].endswith(".jar") and "+" not in a["name"])
        jar = home / asset["name"]
        if not jar.exists():
            download_file(asset["browser_download_url"], jar)
            for old in local:
                old.unlink(missing_ok=True)
        return jar
    except (requests.RequestException, ValueError, KeyError, StopIteration,
            OSError) as e:
        if local:
            return local[-1]
        raise CrossplayError(f"ViaProxy : {e}") from e


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def launch_viaproxy(server_dir: Path, java, java_port: int,
                    timeout: float = 60) -> tuple:
    """Lance ViaProxy devant le serveur et attend qu'il écoute.
    Retourne (process, port local auquel Geyser doit se connecter)."""
    jar = ensure_viaproxy()
    cwd = geyser_dir(server_dir) / VIAPROXY_DIR
    cwd.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    p = subprocess.Popen(
        [str(java), "-Xmx384M", "-jar", str(jar), "cli",
         "--bind-address", f"127.0.0.1:{port}",
         "--target-address", f"127.0.0.1:{java_port}"],
        cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
    end = time.time() + timeout
    while time.time() < end and p.poll() is None:
        try:
            socket.create_connection(("127.0.0.1", port), 0.5).close()
            return p, port
        except OSError:
            time.sleep(0.5)
    p.kill()
    raise CrossplayError(f"ViaProxy n'a pas démarré (voir {cwd / 'logs'})")


# ------------------------------------------------------ authentification

def install_auth(server_dir: Path, loader: str, mc_version: str,
                 log=print) -> Path | None:
    """Plugin/mod de mot de passe pour les comptes crack (mode « les deux »)."""
    try:
        if mods_mod.supports_plugins(loader):
            log("Sécurité : installation d'AuthMe (mot de passe crack)…")
            return mods_mod.install_modrinth(
                "authmereloaded", server_dir, loader, mc_version, "plugin",
                log=log)
        if loader == "fabric":
            log("Sécurité : installation d'EasyAuth…")
            return mods_mod.install_modrinth(
                "easyauth", server_dir, loader, mc_version, "mod", log=log)
        log("  ⚠ Aucun plugin de mot de passe disponible pour ce loader.")
    except (mods_mod.ModError, requests.RequestException) as e:
        log(f"  ⚠ Plugin d'authentification non installé : {e}")
    return None
