"""Pont MCP local : expose les outils de l'agent intégré (fichiers, mods,
commandes, constructions) et ceux du serveur (démarrage, tunnels Playit) à un
client MCP — OpenCode ici.

Transport « streamable HTTP » minimal : JSON-RPC en POST, réponses JSON,
écoute sur 127.0.0.1 uniquement, jeton aléatoire exigé (en-tête
Authorization). Les outils agissent sur UN serveur : `Bridge.server`, choisi
dans le terminal. Aucun appel Tk ici (threads du serveur HTTP).
"""
import hmac
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .. import __version__
from ..core import playit
from ..core import server_manager as sm
from ..core import tunnels as tunnels_mod
from .agent import Agent

INSTRUCTIONS = """You are running inside ServerCraft Agent, a local Minecraft server manager.
The working directory is the folder of the Minecraft server the user picked.
Manage it with the `servercraft` MCP tools: they act on that server.
- server_status / start_server / stop_server, send_command (console, in-game)
- read_errors, read_file, list_files, write_file, edit_properties (configs)
- search_mods / install_mod / list_mods / remove_mod (Modrinth, no key needed)
- list_tunnels / setup_playit_tunnels (free public address via Playit.gg)
- build_structure (prison, cage, maison, mur, arene, fontaine, tour)
Check the real state with the tools before changing anything, and say what you changed.
RAM is `ram_mb` in servercraft.json, not server.properties.
Never delete the world or backups unless the user explicitly asks.
Reply in the user's language, briefly."""

_S, _I = {"type": "string"}, {"type": "integer"}
_KIND = {"type": "string", "enum": ["mod", "plugin"]}

# nom -> (description, propriétés, requis) ; outils de l'Agent puis du serveur
AGENT_TOOLS = {
    "server_info": ("Server metadata: loader, Minecraft version, RAM, port, "
                    "running or not.", {}, []),
    "list_files": ("List files of a sub-folder of the server ('' = root).",
                   {"subdir": _S}, []),
    "read_file": ("Read a server file (tail = last N lines).",
                  {"path": _S, "tail": _I}, ["path"]),
    "read_errors": ("Errors and warnings from logs/latest.log.",
                    {"tail": _I}, []),
    "write_file": ("Rewrite a config file (.properties .yml .json .txt "
                   ".cfg .toml .md).", {"path": _S, "content": _S},
                   ["path", "content"]),
    "edit_properties": ("Change keys of a .properties/.yml file.",
                        {"path": _S, "changes": {"type": "object"}},
                        ["path", "changes"]),
    "send_command": ("Send a console command to the running server "
                     "(no leading slash).", {"cmd": _S}, ["cmd"]),
    "search_mods": ("Search Modrinth for this server's loader/version.",
                    {"query": _S, "kind": _KIND},
                    ["query"]),
    "install_mod": ("Install a Modrinth mod/plugin by slug or name.",
                    {"name": _S, "kind": _KIND},
                    ["name"]),
    "list_mods": ("Installed mods and plugins.", {}, []),
    "remove_mod": ("Delete a file from mods/ or plugins/.",
                   {"filename": _S}, ["filename"]),
    "build_structure": ("Build a structure in game (server running): prison, "
                        "cage, maison, mur, arene, fontaine, tour.",
                        {"type": _S, "x": _I, "y": _I, "z": _I, "size": _I},
                        ["type"]),
}
SERVER_TOOLS = {
    "server_status": ("Running state, players online, RAM/CPU/TPS.", {}, []),
    "start_server": ("Start the Minecraft server (returns once launched; "
                     "watch server_status / read_errors).", {}, []),
    "stop_server": ("Stop the server cleanly (backup if enabled).", {}, []),
    "list_tunnels": ("Public addresses (Playit.gg tunnels) of the server.",
                     {}, []),
    "setup_playit_tunnels": ("Create/find the Playit.gg tunnels (Java, "
                             "Bedrock, Voice Chat) and save their addresses. "
                             "The Playit account must be linked in ServerCraft "
                             "settings. Can take a minute.", {}, []),
}


def tool_list() -> list:
    return [{"name": name, "description": desc,
             "inputSchema": {"type": "object", "properties": props,
                             "required": req}}
            for name, (desc, props, req) in {**AGENT_TOOLS,
                                             **SERVER_TOOLS}.items()]


class Bridge:
    """Serveur MCP en arrière-plan ; `close()` l'arrête."""

    def __init__(self, server: str = ""):
        self.server = server          # nom du serveur ciblé (écrit par l'UI)
        self.token = secrets.token_urlsafe(24)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.httpd.daemon_threads = True
        self.httpd.bridge = self
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/mcp"
        threading.Thread(target=self.httpd.serve_forever, daemon=True,
                         name="mcp-bridge").start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    # ------------------------------------------------------------ JSON-RPC
    def handle(self, msg: dict) -> dict:
        mid, method = msg.get("id"), msg.get("method")
        params = msg.get("params")
        if not isinstance(params, dict):
            params = {}
        if method == "initialize":
            result = {"protocolVersion": params.get("protocolVersion",
                                                    "2025-06-18"),
                      "capabilities": {"tools": {}},
                      "serverInfo": {"name": "servercraft",
                                     "version": __version__},
                      "instructions": INSTRUCTIONS}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": tool_list()}
        elif method == "tools/call":
            text, err = self.call(params.get("name", ""),
                                  params.get("arguments") or {})
            result = {"content": [{"type": "text", "text": text}],
                      "isError": err}
        else:
            return {"jsonrpc": "2.0", "id": mid,
                    "error": {"code": -32601,
                              "message": f"Method not found: {method}"}}
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def call(self, name: str, args) -> tuple:
        """Exécute un outil -> (texte, erreur ?). Ne lève jamais."""
        server = self.server
        if not server:
            return "No server selected in ServerCraft.", True
        if not isinstance(args, dict):
            args = {}
        try:
            if name in SERVER_TOOLS:
                return getattr(self, f"_{name}")(server), False
            if name in AGENT_TOOLS:
                res, ev = Agent(server, {})._execute({**args, "tool": name})
                return res, ev["kind"] == "error"
            return f"Unknown tool: {name}", True
        except Exception as e:  # noqa: BLE001 — renvoyé au modèle
            return f"{name}: {playit.explain(e)}", True

    # ------------------------------------------------------ outils serveur
    @staticmethod
    def _server_status(server: str) -> str:
        proc = sm.PROCESSES.get(server)
        running = bool(proc and proc.is_running())
        out = {"server": server, "running": running,
               "starting": bool(proc and proc._starting),
               "ready": bool(running and proc.ready),
               "stopping": bool(proc and proc.is_stopping()),
               "players": sorted(proc.tracker.players) if proc else []}
        st = proc.stats() if running else None
        if st:
            out.update(ram_mb=round(st["ram_mb"]), cpu_percent=round(st["cpu"]),
                       tps=st["tps"], uptime_s=round(st["uptime"]))
        return json.dumps(out, ensure_ascii=False)

    @staticmethod
    def _start_server(server: str) -> str:
        from ..i18n import t
        proc = sm.get_process(server)
        if proc.is_running() or proc._starting:
            return "Already running or starting."
        proc._starting = True               # même déroulé que l'onglet serveurs
        proc.log(t("srv_starting", name=server))
        try:
            proc.start()
        except Exception as e:
            proc.log(f"✖ {t('srv_start_err')} : {e}")
            raise
        finally:
            proc._starting = False
        return "Server process launched; it is ready when server_status says ready."

    @staticmethod
    def _stop_server(server: str) -> str:
        from ..i18n import t
        proc = sm.PROCESSES.get(server)
        if not proc or not proc.is_running():
            return "Server is not running."
        proc.log(t("srv_stop_req"))
        proc.stop()
        return "Stop requested."

    @staticmethod
    def _list_tunnels(server: str) -> str:
        meta = sm.load_meta(sm.server_dir(server))
        return json.dumps({"playit_linked": playit.linked(),
                           "playit_auto": bool(meta.get("playit_auto")),
                           "port": meta.get("port", 25565),
                           "tunnels": tunnels_mod.clean(meta.get("tunnels"))},
                          ensure_ascii=False)

    @staticmethod
    def _setup_playit_tunnels(server: str) -> str:
        found = playit.setup_server(server, sm.server_dir(server))
        proc = sm.PROCESSES.get(server)
        if proc:
            proc.reload_meta()
        return "\n".join(f"{tn['name']} {tn['proto'].upper()} "
                         f"{tn['address']} -> localhost:{tn['local']}"
                         for tn in found) or "No tunnel."


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):   # pas de sortie console (app fenêtrée)
        pass

    def _send(self, code: int, obj=None) -> None:
        body = b"" if obj is None else json.dumps(obj).encode("utf-8")
        self.send_response(code)
        if obj is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):                # pas de flux SSE : le client s'en passe
        self._send(405)

    do_DELETE = do_GET

    def do_POST(self):
        bridge = self.server.bridge
        auth = self.headers.get("Authorization", "")
        if not hmac.compare_digest(auth.encode(),
                                   f"Bearer {bridge.token}".encode()):
            return self._send(401, {"error": "unauthorized"})
        try:
            size = int(self.headers.get("Content-Length") or 0)
            msg = json.loads(self.rfile.read(size) or b"null")
        except ValueError:
            msg = None
        if not isinstance(msg, dict):
            return self._send(400, {"jsonrpc": "2.0", "id": None, "error": {
                "code": -32700, "message": "Parse error"}})
        if "id" not in msg:          # notification (initialized…)
            return self._send(202)
        self._send(200, bridge.handle(msg))
