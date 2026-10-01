"""Création, démarrage, arrêt et console des serveurs Minecraft."""
import json
import os
import re
import shutil
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

from ..config import SERVERS_DIR
from ..i18n import t
from . import backups as backups_mod
from . import crossplay, discord, downloader, java as java_mod, mods as mods_mod
from . import playit, server_net
from . import tunnels as tunnels_mod
from .properties import write_server_properties

META_FILE = "servercraft.json"
STOP_TIMEOUT = 30
BACKUP_TIMEOUT = 600                 # gros mondes : zip de plusieurs Go
# Crash : arrêt sans « stop ». Redémarrage auto limité à `crash_max_restarts`
# tentatives par fenêtre de CRASH_WINDOW secondes (évite une boucle).
CRASH_ACTIONS = ("none", "ask", "auto")
CRASH_WINDOW = 600
CRASH_DELAY = 10
DEFAULT_CRASH_MAX = 3
# « /stop » tapé en jeu par un OP (vanilla, Paper, Forge, Fabric)
_STOP_LINE = re.compile(r"\]:\s*Stopping the server")

# Préfixe des lignes « internes » (réponses des commandes envoyées par
# l'app elle-même : list, data get, give, clear…). Le backlog les garde
# (lecture par player_card/tracker) mais les consoles les sautent.
QUIET_MARK = "\x01"

# Réponses typiques des commandes internes, à masquer de la console.
_QUIET_RESP = re.compile(
    r"players online|following entity data:|Can't get|"
    r"No entity was found|Unknown entity|"
    r"Gave |Can't give|Can't clear|"
    r"Cleared|Removed \d+ item|No items were found|Replaced|Could not|"
    r"Set the player's game mode|Set .*game mode|"
    r"That player isn't online|No player was found|"
    r"Nothing changed|That command does not exist|"
    r"Unknown item|Too many items|TPS from last")
# Monitoring : historique RAM/CPU (1 échantillon/s) et TPS (Paper/Purpur)
HISTORY = 120
TPS_LOADERS = ("paper", "purpur")
_TPS_LINE = re.compile(r"TPS from last 1m, 5m, 15m:\s*\*?([\d.]+)")
# Réponses de save-off / save-all / save-on, masquées pendant une sauvegarde
# (leur nombre varie selon le loader et les dimensions).
_SAVE_RESP = re.compile(
    r"Automatic saving is now|Saving the game|Saved the game|"
    r"Saving chunks|All chunks are saved|All dimensions are saved|"
    r"Saved the world|Saving is already")
# pas de fenêtre console noire pour java.exe quand l'app est packagée (GUI)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


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
                # fichier incomplet ou modifié à la main : dossier ignoré
                # plutôt que de faire planter toute la liste
                if not isinstance(meta, dict) or not all(
                        meta.get(k) for k in ("loader", "mc_version")):
                    continue
                meta["name"] = d.name       # le dossier fait foi
                meta["dir"] = str(d)
                meta["running"] = d.name in PROCESSES and \
                    PROCESSES[d.name].is_running()
                out.append(meta)
            except (ValueError, OSError):
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
        pinned = bool(options.get("loader_version")) and \
            loader in downloader.PINNABLE
        java = java_mod.ensure_java(mc_version, log=log, pinned=pinned)

        # 2) server.jar / installeur
        log(f"— Résolution {loader} {mc_version} —")
        loader_version = (options.get("loader_version")
                          if loader in downloader.PINNABLE else None)
        if loader_version:
            log(t("mpc_loader_ver", loader=loader, ver=loader_version))
        try:
            url, filename, kind = downloader.get_download(
                loader, mc_version, loader_version)
            target = path / ("server.jar" if kind == "jar" else filename)
            log(f"Téléchargement : {filename}")
            downloader.download_file(url, target, pct)
        except Exception:
            if not loader_version:
                raise
            log(t("mpc_pin_fallback", ver=loader_version))
            loader_version = None
            url, filename, kind = downloader.get_download(loader, mc_version)
            target = path / ("server.jar" if kind == "jar" else filename)
            log(f"Téléchargement : {filename}")
            downloader.download_file(url, target, pct)
        meta_jar = "server.jar"
        launch_args = ""
        if kind != "jar":
            installer = target
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
            extra=options.get("props"),
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
            # voicechat-server.properties est le fichier de Simple Voice
            # Chat : Plasmo Voice a sa propre config et l'ignore
            if voice == "simple_voice_chat":
                mods_mod.write_voicechat_config(
                    path, loader, mods_mod.DEFAULT_VOICE_PORT, ""
                )
                log("Config Voice Chat pré-générée (UDP 24454).")

        # 5b) Cross-play Bedrock + sécurité des comptes crack
        accounts = options.get("accounts",
                               "premium" if options.get("online_mode")
                               else "both")
        crossplay_on = bool(options.get("crossplay"))
        if crossplay_on:
            try:
                crossplay.install(path, loader, mc_version, java=java,
                                  log=log)
            except Exception as e:  # noqa: BLE001 — non bloquant
                log(f"⚠ Cross-play non installé : {e}")
                crossplay_on = False
        if accounts == "both":
            crossplay.install_auth(path, loader, mc_version, log=log)

        # 6) Playit.gg
        summary = ""
        tunnel_list = tunnels_mod.clean(options.get("tunnels"))
        if tunnel_list:
            log(f"— Playit.gg : {len(tunnel_list)} tunnel(s) —")
            summary = tunnels_mod.apply(path, loader, tunnel_list,
                                        java_port=options.get("port", 25565),
                                        voice=voice)
            log("PLAYIT-README.txt généré.")

        # 7) dossiers de contenu selon le loader (mods/, plugins/)
        for sub in ("mods", "plugins"):
            if (sub == "mods" and mods_mod.supports_mods(loader)) or \
               (sub == "plugins" and mods_mod.supports_plugins(loader)):
                (path / sub).mkdir(exist_ok=True)

        # 7b) modpack : mods serveur (les mods client sont ignorés) + configs
        pack = options.get("modpack")
        if pack:
            from . import modpack as modpack_mod
            log(t("mpc_log_install", name=pack.get("name", "")))
            plan = modpack_mod.plan(pack, cf_key=options.get("cf_key", ""),
                                    log=log)
            res = modpack_mod.apply_plan(plan, path, include_client=False,
                                         log=log)
            log(t("mp_done", n=res["installed"], c=res["client_skipped"],
                  f=res["configs"]))

        # 8) métadonnées
        meta = {
            "name": name,
            "loader": loader,
            "mc_version": mc_version,
            "ram_mb": int(options.get("ram_mb", 4096)),
            "port": int(options.get("port", 25565)),
            "online_mode": bool(options.get("online_mode", False)),
            "accounts": accounts,
            "crossplay": crossplay_on,
            "tunnels": tunnel_list,
            "playit_auto": bool(options.get("playit_auto")),
            "voice": voice,
            "jar": meta_jar,
            "launch_args": launch_args,
            "created": time.strftime("%Y-%m-%d %H:%M"),
        }
        if loader_version:
            meta["loader_version"] = loader_version
        if pack:
            meta["modpack"] = pack.get("name", "")
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
        text=True, errors="replace", creationflags=NO_WINDOW,
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


_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|[\ufffd\x1b]?\[[0-9;]*m")

# sortie console Java en UTF-8 (sinon cp1252 sous Windows → accents cassés)
_ENC_FLAGS = ["-Dfile.encoding=UTF-8", "-Dstdout.encoding=UTF-8",
              "-Dstderr.encoding=UTF-8"]


def build_launch_command(path: Path, meta: dict, log=print) -> list:
    # ensure_java vérifie la version requise et télécharge un JRE si besoin
    pinned = bool(meta.get("loader_version")) and \
        meta.get("loader") in downloader.PINNABLE
    java = java_mod.ensure_java(meta["mc_version"], log=log, pinned=pinned)
    ram = int(meta.get("ram_mb", 4096))
    if meta.get("launch_args"):
        # Réplique run.bat : java @user_jvm_args.txt @.../win_args.txt nogui
        (path / "user_jvm_args.txt").write_text(
            f"-Xms{ram}M\n-Xmx{ram}M\n" + "\n".join(_ENC_FLAGS) + "\n",
            encoding="utf-8"
        )
        return [
            str(java), "@user_jvm_args.txt",
            f"@{meta['launch_args']}", "nogui",
        ]
    return [
        str(java), f"-Xms{ram}M", f"-Xmx{ram}M", *_ENC_FLAGS,
        "-jar", meta.get("jar", "server.jar"), "nogui",
    ]


def find_orphans(path: Path) -> list:
    """Process Java qui tournent encore dans ce dossier serveur (app fermée
    brutalement) — ils verrouillent le monde et bloquent tout relancement."""
    try:
        import psutil
    except ImportError:
        return []
    target = os.path.normcase(str(Path(path).resolve()))
    out = []
    for p in psutil.process_iter(["name", "cwd"]):
        try:
            if (p.info["name"] or "").lower().startswith("java") and \
                    p.info["cwd"] and \
                    os.path.normcase(p.info["cwd"]) == target:
                out.append(p)
        except (psutil.Error, OSError):
            continue
    return out


def stop_all(timeout: float = 30.0) -> None:
    """Arrêt propre de tous les serveurs lancés (fermeture de l'app), avec
    la sauvegarde avant arrêt si elle est activée."""
    running = [p for p in PROCESSES.values() if p.is_running()]
    for p in running:
        p.stop()
    for p in running:
        th = p._stop_thread
        if th:
            th.join(timeout=BACKUP_TIMEOUT)
    deadline = time.time() + timeout
    for p in running:
        try:
            p.proc.wait(timeout=max(0.1, deadline - time.time()))
        except subprocess.TimeoutExpired:
            p.proc.kill()
    for p in PROCESSES.values():
        p._stop_geyser()
    playit.stop_agent()


class ServerProcess:
    """Encapsule le process Java : lecture console + envoi de commandes.

    La console (`backlog` + compteur `seq`) et les joueurs (`tracker`) sont
    stockés ici : l'UI les lit périodiquement depuis le thread principal —
    aucun appel Tkinter n'est fait depuis les threads de lecture.
    """

    def __init__(self, name: str):
        from .players import PlayerTracker
        self.name = name
        self.path = server_dir(name)
        self.meta = load_meta(self.path)
        self.proc = None
        self.on_line = None
        self.on_exit = None
        self.listeners = []          # callbacks (name, line) -> autonomie IA
        self.exit_listeners = []     # callbacks (name, code)
        self.backlog = deque(maxlen=4000)
        self.seq = 0                 # nb total de lignes ajoutées
        self._quiet = deque()        # commandes internes dont la réponse
                                     # est masquée de la console (FIFO)
        self.tracker = PlayerTracker(name)
        self.tracker.on_event = self._player_event
        self.exit_code = None
        self._starting = False       # démarrage en cours (Java, Popen…)
        self._geyser = None          # process Geyser Standalone
        self._java = None
        self.ready = False
        self._ps = None              # psutil.Process (stats)
        self.started_at = 0.0
        self.last_backup = 0.0
        self.backup_error = ""
        self.hide_saves_until = 0.0  # masque les réponses save-* (backups)
        self.stop_requested = False  # arrêt voulu (stop/redémarrage)
        self._stop_thread = None
        self._waiter_thread = None
        self.crashes = deque(maxlen=20)  # horodatages des crashs
        self.crash_prompt = False    # l'UI doit proposer un redémarrage
        self.history = deque(maxlen=HISTORY)  # (t, ram_mb, cpu, tps)
        self.tps = None
        self._tps_at = 0.0
        self.tps_wanted = 0.0        # graphique affiché -> /tps interrogé
        self._sample = None
        self._ps_lock = threading.Lock()
        self._lock = threading.Lock()
        self._stdin_lock = threading.Lock()

    def log(self, line: str, quiet: bool = False) -> None:
        """Ajoute une ligne à la console (thread-safe). Les lignes
        `quiet` (réponses de commandes internes) sont préfixées d'un
        marqueur et filtrées à l'affichage, mais restent dans le backlog
        pour les lecteurs internes (`lines_since`, tracker)."""
        with self._lock:
            self.backlog.append(QUIET_MARK + line if quiet else line)
            self.seq += 1

    def lines_since(self, seen: int):
        """Retourne (nouvelles lignes, nouveau compteur)."""
        with self._lock:
            n = min(self.seq - seen, len(self.backlog))
            new = list(self.backlog)[-n:] if n > 0 else []
            return new, self.seq

    def request_list(self, every: float = 10.0) -> None:
        """Rafraîchit la liste des joueurs (`list`), au plus toutes les
        `every` secondes, quel que soit le nombre de fenêtres ouvertes."""
        now = time.time()
        if self.ready and now - getattr(self, "_last_list", 0) >= every:
            self._last_list = now
            self.send_quiet("list")

    def stats(self) -> dict | None:
        """RAM (Mo) / CPU (% de la machine) / uptime / TPS du process Java.
        Renvoie le dernier échantillon du planificateur s'il est récent :
        cpu_percent() mesure depuis l'appel précédent, plusieurs lecteurs
        se voleraient la mesure."""
        s = self._sample
        if s and self.is_running() and time.time() - s["at"] < 2.5:
            return s
        return self.sample()

    def sample(self) -> dict | None:
        """Mesure et ajoute un point à `history` (appelé 1/s par le
        planificateur)."""
        with self._ps_lock:
            if not self.is_running():
                self._ps = self._sample = None
                return None
            try:
                import psutil
                if self._ps is None or self._ps.pid != self.proc.pid:
                    self._ps = psutil.Process(self.proc.pid)
                    self._ps.cpu_percent(None)       # amorce la mesure
                mem = self._ps.memory_info().rss / (1024 * 1024)
                cpu = self._ps.cpu_percent(None) / (psutil.cpu_count() or 1)
            except Exception:  # noqa: BLE001 — process en train de s'arrêter
                return None
            now = time.time()
            tps = self.tps if now - self._tps_at < 15 else None
            s = {"ram_mb": mem, "cpu": min(cpu, 100.0), "tps": tps,
                 "uptime": now - self.started_at, "at": now}
            self.history.append((now, mem, s["cpu"], tps))
            self._sample = s
            return s

    def reload_meta(self) -> None:
        try:
            self.meta = load_meta(self.path)
        except (OSError, json.JSONDecodeError):
            pass

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
        if on_line is not None:
            self.on_line = on_line
        if on_exit is not None:
            self.on_exit = on_exit
        self.reload_meta()           # RAM/port modifiés dans ⚙ Config
        for orphan in find_orphans(self.path):
            self.log(f"── Ancien processus du serveur encore actif "
                     f"(PID {orphan.pid}) : arrêt… ──")
            try:
                orphan.terminate()
                orphan.wait(15)
            except Exception:  # noqa: BLE001
                try:
                    orphan.kill()
                except Exception:  # noqa: BLE001
                    pass
            lock = self.path / "world" / "session.lock"
            try:
                lock.unlink(missing_ok=True)
            except OSError:
                pass
        # Port déjà pris (autre serveur, autre programme) : Java démarrerait
        # puis planterait sur « FAILED TO BIND TO PORT » — autant le dire
        # tout de suite, clairement.
        from .properties import load_properties, parse_port
        port = parse_port(load_properties(
            self.path / "server.properties").get("server-port", "")) \
            or int(self.meta.get("port", 25565))
        if server_net.port_in_use(port):
            owner = server_net.port_owner(port)
            raise ServerError(t("srv_port_busy", port=port,
                                by=f" ({owner})" if owner else ""))
        self.exit_code = None
        self.ready = False           # passe à True au « Done (…) »
        self.stop_requested = False
        self.tracker.players.clear()
        cmd = build_launch_command(self.path, self.meta, log=self.log)
        self._java = cmd[0]
        self.proc = subprocess.Popen(
            cmd, cwd=str(self.path),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, errors="replace",
            encoding="utf-8", bufsize=1,
            creationflags=NO_WINDOW,
        )
        self.started_at = time.time()
        self._ps = self._sample = self.tps = None
        self.history.clear()
        threading.Thread(target=self._reader, args=(self.proc,),
                         daemon=True).start()
        self._waiter_thread = threading.Thread(
            target=self._waiter, args=(self.proc,), daemon=True)
        self._waiter_thread.start()
        if self.meta.get("playit_auto") and playit.linked():
            threading.Thread(target=self._playit_up, daemon=True).start()

    # ------------------------------------------------ tunnels Playit
    def _playit_up(self) -> None:
        """Tunnels Playit retrouvés / créés + agent (thread, aucun Tk)."""
        def log(event, label, value):
            if event == "create":
                self.log(t("pl_log_create", name=label, port=value))
            elif event == "ready":
                self.log(t("pl_log_ready", name=label, addr=value))
        try:
            playit.setup_server(self.name, self.path, log)
            self.reload_meta()
            time.sleep(4)
            err = playit.agent_error()
            if err:
                self.log(f"✖ {t('pl_log_agent_err', e=err)}")
        except Exception as e:  # noqa: BLE001 — réseau, compte, API
            self.log(f"✖ {t('pl_log_err', e=playit.explain(e))}")

    def _reader(self, proc) -> None:
        for line in proc.stdout:
            line = _ANSI.sub("", line.rstrip("\r\n"))
            just_ready = not self.ready and "Done (" in line
            if just_ready:
                self.ready = True
            if _STOP_LINE.search(line):
                self.stop_requested = True
            m = _TPS_LINE.search(line)
            if m:
                self.tps, self._tps_at = min(float(m.group(1)), 20.0), \
                    time.time()
            quiet = self._consume_quiet(line) or (
                time.time() < self.hide_saves_until
                and bool(_SAVE_RESP.search(line)))
            self.log(line, quiet=quiet)
            try:
                self.tracker.feed(self.name, line)
            except Exception:
                pass
            if just_ready:
                discord.notify("started", self.name)
            if just_ready and crossplay.installed(self.path):
                threading.Thread(target=self._start_geyser,
                                 daemon=True).start()
            for cb in [self.on_line, *self.listeners]:
                if cb:
                    try:
                        cb(self.name, line)
                    except Exception:
                        pass

    # ------------------------------------------------ proxy Bedrock (Geyser)
    def _start_geyser(self) -> None:
        """Lance Geyser Standalone une fois le serveur prêt (clé Floodgate
        générée). Ses lignes arrivent dans la console préfixées [Bedrock]."""
        try:
            gdir = crossplay.geyser_dir(self.path)
            for orphan in find_orphans(gdir):
                orphan.kill()
            if not (gdir / "config.yml").exists():
                self.log("── Cross-play : première configuration de Geyser… ──")
                crossplay._generate_config(gdir, self._java)
            auth = crossplay.configure(self.path,
                                       int(self.meta.get("port", 25565)),
                                       self.meta.get("accounts", "both"))
            self.log(f"── Cross-play : démarrage du proxy Bedrock "
                     f"(UDP {crossplay.BEDROCK_PORT}, auth {auth}) ──")
            self._geyser = crossplay.launch(self.path, self._java)
            threading.Thread(target=self._geyser_reader,
                             args=(self._geyser,), daemon=True).start()
        except Exception as e:  # noqa: BLE001
            self.log(f"✖ Cross-play : Geyser n'a pas pu démarrer : {e}")

    def _geyser_reader(self, gp) -> None:
        for line in gp.stdout:
            line = _ANSI.sub("", line.rstrip("\r\n"))
            # bruit JVM sans intérêt pour l'utilisateur
            if not line.strip() or line.startswith("WARNING:") or \
                    "StatusConsoleListener" in line or line.endswith("INFO] "):
                continue
            self.log(f"[Bedrock] {line}")

    def _stop_geyser(self) -> None:
        gp, self._geyser = self._geyser, None
        if gp and gp.poll() is None:
            try:
                gp.stdin.write("geyser stop\n")
                gp.stdin.flush()
                gp.wait(8)
            except Exception:  # noqa: BLE001
                gp.kill()

    def _player_event(self, kind: str, player: str) -> None:
        discord.notify(kind, self.name, player=player)

    def _tail(self, n: int = 8) -> str:
        """Dernières lignes visibles de la console (détail d'un crash)."""
        with self._lock:
            lines = [ln for ln in self.backlog
                     if not ln.startswith(QUIET_MARK)][-n:]
        return "\n".join(lines)

    def _waiter(self, proc) -> None:
        code = proc.wait()
        # État figé tout de suite : pendant l'arrêt de Geyser (jusqu'à 8 s),
        # un redémarrage relance start() qui remet ces drapeaux à zéro — le
        # redémarrage était alors pris pour un crash.
        crashed = not self.stop_requested
        was_ready = self.ready
        self._stop_geyser()
        self.exit_code = code
        self.tracker.players.clear()
        if crashed:
            discord.notify("crashed", self.name, code=code,
                           detail=self._tail())
        else:
            discord.notify("stopped", self.name, code=code)
        for cb in [self.on_exit, *self.exit_listeners]:
            if cb:
                try:
                    cb(self.name, code)
                except Exception:
                    pass
        if crashed:
            self._on_crash(code, was_ready=was_ready)
        playit.release(list(PROCESSES.values()))

    # ------------------------------------------------ crash
    def _on_crash(self, code, was_ready: bool) -> None:
        """Appelé depuis le thread _waiter : aucun appel Tk ici."""
        now = time.time()
        self.crashes.append(now)
        self.log(t("cr_detected", code=code))
        self.reload_meta()
        action = self.meta.get("crash_action", "ask")
        if action not in CRASH_ACTIONS:
            action = "ask"
        if action == "none":
            return
        if action == "ask":
            self.crash_prompt = True
            return
        if not was_ready:
            self.log(t("cr_early"))
            return
        try:
            limit = max(1, int(self.meta.get("crash_max_restarts",
                                             DEFAULT_CRASH_MAX)))
        except (TypeError, ValueError):
            limit = DEFAULT_CRASH_MAX
        recent = sum(1 for c in self.crashes if now - c < CRASH_WINDOW)
        if recent > limit:
            self.log(t("cr_limit", n=recent, min=CRASH_WINDOW // 60))
            self.crash_prompt = True
            return
        self.log(t("cr_auto", sec=CRASH_DELAY, n=recent, max=limit))
        self._starting = True
        try:
            time.sleep(CRASH_DELAY)
            if not self.is_running():
                self.start()
        except Exception as e:  # noqa: BLE001
            self.log(f"✖ {t('srv_start_err')} : {e}")
        finally:
            self._starting = False

    def _consume_quiet(self, line: str) -> bool:
        """True si `line` est la réponse d'une commande interne (send_quiet).
        Les commandes sont dépilées dans l'ordre ; les entrées trop
        vieilles (>8 s, réponse jamais arrivée) sont purgées."""
        now = time.time()
        q = self._quiet
        while q and now - q[0] > 8.0:
            q.popleft()
        if q and _QUIET_RESP.search(line):
            q.popleft()
            return True
        return False

    def send_quiet(self, command: str) -> bool:
        """Comme send(), mais la réponse du serveur est masquée de la
        console (utilisé pour les commandes internes de l'app)."""
        self._quiet.append(time.time())
        return self.send(command)

    def ask(self, command: str, pattern, timeout: float = 2.5):
        """Envoie une commande interne et retourne la première ligne de
        réponse qui correspond à `pattern` (regex compilée), ou None si le
        serveur ne répond pas. Bloquant : à appeler depuis un thread."""
        with self._lock:
            seen = self.seq
        if not self.send_quiet(command):
            return None
        end = time.time() + timeout
        while time.time() < end:
            lines, seen = self.lines_since(seen)
            for line in lines:
                if pattern.search(line):
                    return line.lstrip(QUIET_MARK)
            if not self.is_running():
                return None
            time.sleep(0.05)
        return None

    def send(self, command: str) -> bool:
        if not self.is_running():
            return False
        # Une commande = une ligne : un retour à la ligne dans un texte
        # venu d'ailleurs (raison générée par l'IA, copier-coller) lancerait
        # une deuxième commande dans la console.
        command = " ".join(str(command).splitlines()).strip()
        if not command:
            return False
        if command.lstrip("/").lower() == "stop":
            self.stop_requested = True
        try:
            with self._stdin_lock:    # scheduler, UI et IA écrivent ici
                self.proc.stdin.write(command + "\n")
                self.proc.stdin.flush()
            return True
        except (OSError, ValueError):
            return False

    # ------------------------------------------------ sauvegardes
    def backup(self, reason: str = "manual"):
        """Sauvegarde du monde (bloquant — à appeler depuis un thread).
        Retourne le chemin du zip, ou None en cas d'échec (erreur loggée)."""
        try:
            path = backups_mod.create(
                self.name, self.path, reason,
                keep=int(self.meta.get("backup_keep",
                                       backups_mod.DEFAULT_KEEP)),
                proc=self, log=self.log)
            self.last_backup = time.time()
            return path
        except Exception as e:  # noqa: BLE001
            self.backup_error = str(e)
            self.log(t("bk_error", e=e))
            return None

    def is_stopping(self) -> bool:
        th = self._stop_thread
        return bool(th and th.is_alive())

    def stop(self, reason: str = "stop") -> None:
        """Arrêt propre : sauvegarde (si activée), `stop`, puis kill si le
        serveur ne s'est pas arrêté après STOP_TIMEOUT."""
        if not self.is_running() or self.is_stopping():
            return
        self.stop_requested = True
        self._stop_thread = threading.Thread(
            target=self._stop_work, args=(reason,), daemon=True)
        self._stop_thread.start()

    def _stop_work(self, reason: str) -> None:
        if self.ready and self.meta.get("backup_on_stop", True):
            self.backup(reason)
        self.send("stop")
        self._kill_watchdog()

    def _kill_watchdog(self) -> None:
        proc = self.proc
        try:
            proc.wait(timeout=STOP_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()

    def restart(self) -> None:
        old = self.proc
        waiter = self._waiter_thread
        self.stop("restart")
        self._starting = True

        def _relaunch():
            try:
                if old:
                    old.wait()
                # fin de l'ancien process entièrement traitée (Geyser,
                # notifications) avant de relancer
                if waiter and waiter is not threading.current_thread():
                    waiter.join(timeout=30)
                self.start()
            except Exception as e:  # noqa: BLE001
                self.log(f"✖ Redémarrage impossible : {e}")
            finally:
                self._starting = False
        threading.Thread(target=_relaunch, daemon=True).start()


def get_process(name: str) -> ServerProcess:
    if name not in PROCESSES:
        PROCESSES[name] = ServerProcess(name)
    return PROCESSES[name]


def free_port(start: int = 25565) -> int:
    """Premier port ≥ `start` qu'aucun serveur de la liste n'utilise."""
    used = {int(m.get("port", 25565)) for m in list_servers()}
    port = start
    while port in used and port < 65535:
        port += 1
    return port


# jamais copiés : verrou du monde, journaux et sauvegardes de l'original
_DUP_SKIP = shutil.ignore_patterns("session.lock", "logs", "crash-reports",
                                   "PLAYIT-README.txt")


def duplicate_server(name: str, new_name: str) -> dict:
    """Copie complète d'un serveur arrêté (monde, mods, configs) sous un
    autre nom, sur un port libre — pour tester une mise à jour ou un mod
    sans toucher à l'original. Les tunnels Playit ne sont pas repris (ils
    pointent vers l'original). Bloquant : à appeler depuis un thread."""
    src = server_dir(name)
    slug = _slug(new_name)
    dst = server_dir(slug)
    proc = PROCESSES.get(name)
    if proc and (proc.is_running() or proc._starting):
        raise ServerError(t("dup_running"))
    if not (src / META_FILE).exists():
        raise ServerError(t("dup_missing", name=name))
    if dst.exists():
        raise ServerError(t("dup_exists", name=slug))
    port = free_port()
    try:
        shutil.copytree(src, dst, ignore=_DUP_SKIP)
        meta = load_meta(dst)
        meta.update(name=slug, port=port, tunnels=[], playit_auto=False,
                    created=time.strftime("%Y-%m-%d %H:%M"))
        (dst / META_FILE).write_text(json.dumps(meta, indent=2),
                                     encoding="utf-8")
        from .properties import update_properties
        props = dst / "server.properties"
        if props.exists():
            update_properties(props, {"server-port": port})
        voice = mods_mod.voicechat_config_path(dst, meta.get("loader", ""))
        if voice.exists():            # adresse du tunnel de l'original
            update_properties(voice, {"voice_host": ""})
    except Exception:
        shutil.rmtree(dst, ignore_errors=True)
        raise
    meta["dir"] = str(dst)
    return meta


def delete_server(name: str) -> None:
    proc = PROCESSES.get(name)
    if proc and proc.is_running():
        raise ServerError("Arrêtez le serveur avant de le supprimer.")
    shutil.rmtree(server_dir(name), ignore_errors=True)
    PROCESSES.pop(name, None)
