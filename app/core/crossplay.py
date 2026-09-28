"""Cross-play Java ⇄ Bedrock et authentification premium/crack.

Architecture (automatique, rien à configurer) :
- **Geyser Standalone** : proxy Bedrock → Java lancé à côté du serveur
  (dossier `geyser/`), démarré au « Done » du serveur et arrêté avec lui.
  Indépendant de l'API Paper/Fabric → fonctionne sur toutes les versions
  et tous les loaders.
- **Floodgate** (plugin/mod sur le serveur quand disponible) : les joueurs
  Bedrock entrent sans compte Java, même en mode Premium. Sa clé `key.pem`
  est copiée automatiquement vers Geyser.
- **ViaVersion + ViaBackwards** : permettent à Geyser de rejoindre un
  serveur plus récent que lui.
- **AuthMe** (plugins) / **EasyAuth** (Fabric) : mot de passe pour les
  comptes crack quand le serveur accepte premium ET crack.
"""
import re
import shutil
import subprocess
import time
from pathlib import Path

import requests

from . import mods as mods_mod
from .downloader import download_file

GEYSER_URL = ("https://download.geysermc.org/v2/projects/{p}/versions/latest/"
              "builds/latest/downloads/{plat}")
BEDROCK_PORT = 19132
GEYSER_DIR = "geyser"
GEYSER_JAR = "Geyser-Standalone.jar"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# fichiers ajoutés par le cross-play (pour la désinstallation)
_OURS = ("geyser", "floodgate", "viaversion", "viabackwards")


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
    server_dir = Path(server_dir)
    gdir = geyser_dir(server_dir)
    gdir.mkdir(parents=True, exist_ok=True)
    _remove_plugin_geyser(server_dir)

    log("Cross-play : téléchargement de Geyser (proxy Bedrock)…")
    download_file(GEYSER_URL.format(p="geyser", plat="standalone"),
                  gdir / GEYSER_JAR)

    # Floodgate côté serveur : Bedrock sans compte Java
    try:
        if mods_mod.supports_plugins(loader):
            log("Cross-play : Floodgate…")
            download_file(GEYSER_URL.format(p="floodgate", plat="spigot"),
                          server_dir / "plugins" / "Floodgate-Spigot.jar")
        elif loader in ("fabric", "neoforge"):
            log("Cross-play : Floodgate…")
            mods_mod.install_modrinth("floodgate", server_dir, loader,
                                      mc_version, "mod")
            if loader == "fabric":
                mods_mod.install_modrinth("fabric-api", server_dir, loader,
                                          mc_version, "mod")
    except (mods_mod.ModError, requests.RequestException) as e:
        log(f"  ⚠ Floodgate non installé ({e}) — les joueurs Bedrock "
            "utiliseront leur pseudo Xbox en mode hors-ligne.")

    # ViaVersion + ViaBackwards : Geyser peut viser une version plus ancienne
    if mods_mod.supports_plugins(loader) or loader == "fabric":
        kind = "plugin" if mods_mod.supports_plugins(loader) else "mod"
        for slug in ("viaversion", "viabackwards"):
            try:
                mods_mod.install_modrinth(slug, server_dir, loader,
                                          mc_version, kind)
            except (mods_mod.ModError, requests.RequestException) as e:
                log(f"  ⚠ {slug} non installé : {e}")

    if java:
        log("Cross-play : génération de la configuration Geyser…")
        _generate_config(gdir, java)
    log(f"✔ Cross-play installé — Bedrock : port UDP {BEDROCK_PORT}")


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
    n = 0
    for sub in ("plugins", "mods"):
        d = Path(server_dir) / sub
        if d.exists():
            for f in d.glob("*.jar"):
                if f.name.lower().startswith(_OURS):
                    f.unlink(missing_ok=True)
                    n += 1
    shutil.rmtree(geyser_dir(server_dir), ignore_errors=True)
    return n


# ------------------------------------------------------------ configuration

def configure(server_dir: Path, java_port: int, accounts: str) -> str:
    """Met à jour la config Geyser (port Java, authentification, clé
    Floodgate). Retourne l'auth-type utilisé."""
    gdir = geyser_dir(server_dir)
    cfg = gdir / "config.yml"
    key = _floodgate_key(server_dir)
    if key and _has_floodgate(server_dir):
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


# ------------------------------------------------------ authentification

def install_auth(server_dir: Path, loader: str, mc_version: str,
                 log=print) -> Path | None:
    """Plugin/mod de mot de passe pour les comptes crack (mode « les deux »)."""
    try:
        if mods_mod.supports_plugins(loader):
            log("Sécurité : installation d'AuthMe (mot de passe crack)…")
            return mods_mod.install_modrinth(
                "authmereloaded", server_dir, loader, mc_version, "plugin")
        if loader == "fabric":
            log("Sécurité : installation d'EasyAuth…")
            return mods_mod.install_modrinth(
                "easyauth", server_dir, loader, mc_version, "mod")
        log("  ⚠ Aucun plugin de mot de passe disponible pour ce loader.")
    except (mods_mod.ModError, requests.RequestException) as e:
        log(f"  ⚠ Plugin d'authentification non installé : {e}")
    return None
