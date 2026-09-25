"""Détection de Java et téléchargement automatique d'un JRE (Adoptium Temurin)."""
import os
import platform
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import requests

from ..config import RUNTIMES_DIR, load_settings

_JAVA_EXE = "java.exe" if os.name == "nt" else "java"

_OS_MAP = {"Windows": "windows", "Darwin": "mac", "Linux": "linux"}
_ARCH_MAP = {"AMD64": "x64", "x86_64": "x64", "arm64": "aarch64", "aarch64": "aarch64"}


def java_binary_name() -> str:
    return _JAVA_EXE


def _parse_major(version_output: str):
    m = re.search(r'version "(\d+)(?:\.(\d+))?', version_output)
    if not m:
        return None
    major = int(m.group(1))
    if major == 1 and m.group(2):  # format ancien "1.8.0_xxx" -> Java 8
        return int(m.group(2))
    return major


def _check_java(java_path: Path):
    """Retourne la version majeure de java, ou None si inexécutable."""
    try:
        proc = subprocess.run(
            [str(java_path), "-version"],
            capture_output=True, text=True, timeout=15,
        )
        return _parse_major(proc.stderr + proc.stdout)
    except (OSError, subprocess.SubprocessError):
        return None


def find_java():
    """Cherche un Java utilisable : réglage utilisateur, JAVA_HOME, PATH, runtimes locaux.

    Retourne (chemin, version_majeure) ou (None, None).
    """
    candidates = []

    custom = load_settings().get("java_path", "").strip()
    if custom:
        candidates.append(Path(custom))

    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        candidates.append(Path(java_home) / "bin" / _JAVA_EXE)

    which = shutil.which("java")
    if which:
        candidates.append(Path(which))

    if RUNTIMES_DIR.exists():
        for rt in sorted(RUNTIMES_DIR.iterdir()):
            candidates.append(rt / "bin" / _JAVA_EXE)

    for cand in candidates:
        if cand.exists():
            major = _check_java(cand)
            if major:
                return cand, major
    return None, None


def required_java_major(mc_version: str) -> int:
    """Version majeure de Java minimale selon la version de Minecraft."""
    try:
        parts = [int(p) for p in mc_version.split(".")[:2]]
    except ValueError:
        return 21
    if parts[0] != 1 or len(parts) < 2:
        return 21
    minor = parts[1]
    if minor >= 20:
        # 1.20.5+ -> 21, 1.20.0-1.20.4 -> 17
        try:
            patch = int(mc_version.split(".")[2])
        except (IndexError, ValueError):
            patch = 0
        return 21 if minor > 20 or patch >= 5 else 17
    if minor >= 18:
        return 17
    if minor >= 17:
        return 16  # 1.17 demande Java 16 (Java 17 convient aussi)
    return 8


def ensure_java(mc_version: str = "1.21", log=print) -> Path:
    """Retourne un java compatible, en téléchargeant un JRE Temurin si besoin."""
    found, major = find_java()
    need = required_java_major(mc_version)
    if found and major >= need:
        log(f"Java détecté : {found} (version {major})")
        return found
    if found:
        log(f"Java {major} trouvé mais Minecraft {mc_version} requiert Java {need}+. Téléchargement d'un JRE…")
    else:
        log("Aucun Java trouvé. Téléchargement d'un JRE Temurin…")
    target = 21 if need <= 21 else need
    return download_jre(target, log=log)


def download_jre(major: int = 21, progress_cb=None, log=print) -> Path:
    """Télécharge et extrait un JRE Temurin via l'API Adoptium."""
    os_name = _OS_MAP.get(platform.system(), "windows")
    arch = _ARCH_MAP.get(platform.machine(), "x64")
    url = (
        f"https://api.adoptium.net/v3/binary/latest/{major}/ga/"
        f"{os_name}/{arch}/jre/hotspot/normal/eclipse"
    )
    dest_dir = RUNTIMES_DIR / f"jre-{major}"
    java_path = dest_dir / "bin" / _JAVA_EXE
    if java_path.exists():
        return java_path

    log(f"Téléchargement du JRE {major} ({os_name}/{arch})…")
    RUNTIMES_DIR.mkdir(parents=True, exist_ok=True)
    archive = RUNTIMES_DIR / f"jre-{major}.zip"
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done = 0
        with open(archive, "wb") as f:
            for chunk in r.iter_content(1024 * 256):
                f.write(chunk)
                done += len(chunk)
                if progress_cb:
                    progress_cb(done, total)

    log("Extraction du JRE…")
    tmp = RUNTIMES_DIR / f"_extract_{major}"
    if tmp.exists():
        shutil.rmtree(tmp)
    with zipfile.ZipFile(archive) as z:
        z.extractall(tmp)
    archive.unlink(missing_ok=True)

    # L'archive contient un dossier racine type "jdk-21.0.x+y-jre"
    roots = [p for p in tmp.iterdir() if p.is_dir()]
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    shutil.move(str(roots[0]), str(dest_dir))
    shutil.rmtree(tmp, ignore_errors=True)
    if not java_path.exists():
        raise RuntimeError("JRE extrait mais binaire java introuvable.")
    log(f"JRE {major} installé : {java_path}")
    return java_path
