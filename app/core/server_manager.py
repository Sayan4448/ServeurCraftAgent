"""Création, démarrage, arrêt et console des serveurs Minecraft."""
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from ..config import SERVERS_DIR
from . import downloader, java as java_mod, mods as mods_mod
from .properties import write_server_properties

META_FILE = "servercraft.json"
STOP_TIMEOUT = 30


class ServerError(Exception):
    pass


# ------------------------------------------------------------------ registre

def _slug(name: str) -> str:
    slug = re.sub(r"[^\w\- ]", "", name).strip().replace(" ", "-").lower()
    return slug or "serveur"


def server_dir(name_or_slug: str) -> Path:
    return SERVERS_DIR / name_or_slug


def load_meta(path: Path) -> dict:
    return json.loads((path / META_FILE).read_text(encoding="utf-8"))


def list_servers() -> list:
    out = []
    if not SERVERS_DIR.exists():
        return out
    for d in sorted(SERVERS_DIR.iterdir()):
        meta_file = d / META_FILE
        if d.is_dir() and meta_file.exists():
            try:
                meta = load_meta(d)
                meta["dir"] = str(d)
                meta["running"] = meta["name"] in PROCESSES and PROCESSES[meta["name"]].is_running()
                out.append(meta)
            except (json.JSONDecodeError, OSError):
                continue
    return out


def latest_log_path(path: Path) -> Path:
    return path / "logs" / "latest.log"


def read_log_tail(path: Path, lines: int = 400) -> str:
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(content[-lines:])


# ------------------------------------------------------------------ création

def create_server(options: dict, progress_cb=None, log=print) -> dict:
    """Crée un serveur complet. options : name, loader, mc_version, ram_mb,
    port, online_mode, motd, voice ('none'|'simple_voice_chat'|'plasmo_voice'),
    playit {address, tcp_port, udp_port}."""
    name = _slug(options["name"])
    loader = options["loader"]
    mc_version = options["mc_version"]
    path = SERVERS_DIR / name
    if path.exists():
        raise ServerError(f"Le serveur '{name}' existe déjà.")
    path.mkdir(parents=True)

    def pct(done, total):
        if progress_cb and total:
            progress_cb(done / total)

    try:
        # 1) Java
        log("— Vérification de Java —")
        java = java_mod.ensure_java(mc_version, log=log)

        # 2) server.jar / installeur
        log(f"— Résolution {loader} {mc_version} —")
        url, filename, kind = downloader.get_download(loader, mc_version)
        meta_jar = "server.jar"
        launch_args = ""
        if kind == "jar":
            log(f"Téléchargement : {filename}")
            downloader.download_file(url, path / "server.jar", pct)
        else:
            log(f"Téléchargement de l'installeur : {filename}")
            installer = downloader.download_file(url, path / filename, pct)
            log("Exécution de l'installeur (--installServer), patientez…")
            _run_installer(java, installer, path, log)
            launch_args = _find_args_file(path)
            if launch_args:
                log(f"Fichier d'arguments détecté : {launch_args}")
            else:
                jar = _find_forge_jar(path)
                if jar:
                    meta_jar = jar
                else:
                    raise ServerError(
                        "Installeur terminé mais aucun fichier de lancement trouvé."
                    )

        # 3) EULA
        (path / "eula.txt").write_text(
            "# Accepté automatiquement par ServerCraft Agent\neula=true\n",
            encoding="utf-8",
        )

        # 4) server.properties
        write_server_properties(
            path / "server.properties",
            port=options.get("port", 25565),
            online_mode=options.get("online_mode", False),
            motd=options.get("motd", f"{name} - ServerCraft"),
            max_players=options.get("max_players", 20),
            difficulty=options.get("difficulty", "normal"),
            gamemode=options.get("gamemode", "survival"),
        )
        log("server.properties généré (mode offline si non coché).")

        # 5) Voice chat
        voice = options.get("voice", "none")
        if voice != "none":
            log(f"— Installation de {mods_mod.VOICE_LABELS[voice]} —")
            mod_file = mods_mod.install_voice_mod(
                path, loader, mc_version, voice, progress_cb=pct
            )
            log(f"Installé : {mod_file.name}")
            mods_mod.write_voicechat_config(
                path, loader, mods_mod.DEFAULT_VOICE_PORT, ""
            )
            log("Config Voice Chat pré-générée (UDP 24454).")

        # 6) Playit.gg
        summary = ""
        playit = options.get("playit") or {}
        if playit.get("address"):
            log("— Configuration Playit.gg —")
            summary = mods_mod.configure_playit(
                path, loader,
                address=playit["address"],
                tcp_port=int(playit.get("tcp_port") or 25565),
                udp_port=int(playit.get("udp_port") or 0),
                local_server_port=options.get("port", 25565),
                voice_enabled=(voice != "none"),
            )
            log("PLAYIT-README.txt généré.")

        # 7) dossiers de contenu selon le loader (mods/, plugins/)
        for sub in ("mods", "plugins"):
            if (sub == "mods" and mods_mod.supports_mods(loader)) or \
               (sub == "plugins" and mods_mod.supports_plugins(loader)):
                (path / sub).mkdir(exist_ok=True)

        # 8) métadonnées
        meta = {
            "name": name,
            "loader": loader,
            "mc_version": mc_version,
            "ram_mb": int(options.get("ram_mb", 4096)),
            "port": int(options.get("port", 25565)),
            "online_mode": bool(options.get("online_mode", False)),
            "voice": voice,
            "jar": meta_jar,
            "launch_args": launch_args,
            "created": time.strftime("%Y-%m-%d %H:%M"),
        }
        (path / META_FILE).write_text(json.dumps(meta, indent=2), encoding="utf-8")
        meta["summary"] = summary
        log(f"✔ Serveur '{name}' prêt.")
        return meta
    except Exception:
        shutil.rmtree(path, ignore_errors=True)
        raise


def _run_installer(java: Path, installer: Path, cwd: Path, log) -> None:
    proc = subprocess.Popen(
        [str(java), "-jar", installer.name, "--installServer"],
        cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, errors="replace",
    )
    for line in proc.stdout:
        line = line.strip()
        if line:
            log(f"  {line}")
    code = proc.wait(timeout=600)
    if code != 0:
        raise ServerError(f"L'installeur a échoué (code {code}).")


def _find_args_file(path: Path) -> str:
    """Forge/NeoForge modernes : win_args.txt / unix_args.txt dans libraries/."""
    argname = "win_args.txt" if os.name == "nt" else "unix_args.txt"
    for pattern in (
        f"libraries/net/minecraftforge/forge/*/{argname}",
        f"libraries/net/neoforged/neoforge/*/{argname}",
        f"libraries/net/neoforged/forge/*/{argname}",
    ):
        for m in sorted(path.glob(pattern)):
            return str(m.relative_to(path))
    return ""


def _find_forge_jar(path: Path) -> str:
    """Forge ancien (<1.17) : forge-x.y.z-server.jar à la racine."""
    for jar in sorted(path.glob("forge-*.jar")):
        if "installer" not in jar.name:
            return jar.name
    return ""


# ------------------------------------------------------------------ processus

PROCESSES: dict = {}


def build_launch_command(path: Path, meta: dict) -> list:
    java, _ = java_mod.find_java()
    if not java:
        java = java_mod.ensure_java(meta["mc_version"])
    ram = int(meta.get("ram_mb", 4096))
    if meta.get("launch_args"):
        # Réplique run.bat : java @user_jvm_args.txt @.../win_args.txt nogui
        (path / "user_jvm_args.txt").write_text(
            f"-Xms{ram}M\n-Xmx{ram}M\n", encoding="utf-8"
        )
        return [
            str(java), "@user_jvm_args.txt",
            f"@{meta['launch_args']}", "nogui",
        ]
    return [
        str(java), f"-Xms{ram}M", f"-Xmx{ram}M",
        "-jar", meta.get("jar", "server.jar"), "nogui",
    ]


class ServerProcess:
    """Encapsule le process Java : lecture console + envoi de commandes."""

    def __init__(self, name: str):
        self.name = name
        self.path = server_dir(name)
        self.meta = load_meta(self.path)
        self.proc = None
        self.on_line = None
        self.on_exit = None
        self.listeners = []          # callbacks (name, line) -> joueurs/autonomie
        self.exit_listeners = []     # callbacks (name, code)

    def add_listener(self, on_line=None, on_exit=None) -> None:
        if on_line:
            self.listeners.append(on_line)
        if on_exit:
            self.exit_listeners.append(on_exit)

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, on_line=None, on_exit=None) -> None:
        if self.is_running():
            return
        self.on_line, self.on_exit = on_line, on_exit
        cmd = build_launch_command(self.path, self.meta)
        self.proc = subprocess.Popen(
            cmd, cwd=str(self.path),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, errors="replace",
            bufsize=1,
        )
        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(target=self._waiter, daemon=True).start()

    def _reader(self) -> None:
        for line in self.proc.stdout:
            line = line.rstrip("\n")
            if self.on_line:
                self.on_line(self.name, line)
            for cb in list(self.listeners):
                try:
                    cb(self.name, line)
                except Exception:
                    pass

    def _waiter(self) -> None:
        code = self.proc.wait()
        if self.on_exit:
            self.on_exit(self.name, code)
        for cb in list(self.exit_listeners):
            try:
                cb(self.name, code)
            except Exception:
                pass

    def send(self, command: str) -> bool:
        if not self.is_running():
            return False
        try:
            self.proc.stdin.write(command + "\n")
            self.proc.stdin.flush()
            return True
        except (OSError, ValueError):
            return False

    def stop(self) -> None:
        if not self.is_running():
            return
        self.send("stop")
        threading.Thread(target=self._kill_watchdog, daemon=True).start()

    def _kill_watchdog(self) -> None:
        proc = self.proc
        try:
            proc.wait(timeout=STOP_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()

    def restart(self) -> None:
        was_callbacks = (self.on_line, self.on_exit)
        self.stop()
        def _relauch():
            self.proc and self.proc.wait()
            self.start(*was_callbacks)
        threading.Thread(target=_relauch, daemon=True).start()


def get_process(name: str) -> ServerProcess:
    if name not in PROCESSES:
        PROCESSES[name] = ServerProcess(name)
    return PROCESSES[name]


def delete_server(name: str) -> None:
    proc = PROCESSES.get(name)
    if proc and proc.is_running():
        raise ServerError("Arrêtez le serveur avant de le supprimer.")
    shutil.rmtree(server_dir(name), ignore_errors=True)
    PROCESSES.pop(name, None)
