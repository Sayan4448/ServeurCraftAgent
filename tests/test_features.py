"""Nouveautés 1.30 : historique des commandes, port occupé, duplication,
whitelist."""
import json
import socket

import pytest

from app.core import banlist, server_net
from app.core import server_manager as sm
from app.core.properties import load_properties
from app.ui.cmd_history import CommandHistory


# ------------------------------------------------------------- historique

def test_history_walks_back_and_forth():
    h = CommandHistory()
    for cmd in ("say a", "op Steve", "list"):
        h.add(cmd)
    assert h.previous("brouillon") == "list"
    assert h.previous() == "op Steve"
    assert h.previous() == "say a"
    assert h.previous() == "say a"            # reste sur la plus ancienne
    assert h.next() == "op Steve"
    assert h.next() == "list"
    assert h.next() == "brouillon"            # retour au texte en cours
    assert h.next("x") == "x"


def test_history_ignores_blanks_and_moves_repeats_to_the_end():
    h = CommandHistory(limit=3)
    assert h.previous("vide") == "vide"
    for cmd in ("a", " ", "b", "a", "c", "d"):
        h.add(cmd)
    assert [h.previous(), h.previous(), h.previous()] == ["d", "c", "a"]
    assert h.previous() == "a"                # « b » est sorti (limite 3)


# -------------------------------------------------------------------- port

def test_port_in_use_detects_a_listener():
    # écoute sur la boucle locale seulement : une écoute sur 0.0.0.0 fait
    # apparaître la fenêtre du pare-feu Windows
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        assert server_net.port_in_use(port)
        assert "PID" in server_net.port_owner(port)
    assert not server_net.port_in_use(port)


def test_port_check_without_psutil(monkeypatch):
    """Repli : simple tentative de liaison, sans écoute."""
    def no_psutil(port):
        raise ImportError("psutil")
    monkeypatch.setattr(server_net, "_listeners", no_psutil)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("0.0.0.0", 0))
        port = s.getsockname()[1]
        assert server_net.port_in_use(port)
    assert not server_net.port_in_use(port)
    assert server_net.port_owner(port) == ""


def test_start_refuses_a_busy_port(make_server, monkeypatch):
    make_server("srv", port=25570)
    (sm.server_dir("srv") / "server.properties").write_text(
        "server-port=25571\n", encoding="utf-8")
    checked = []
    monkeypatch.setattr(sm, "find_orphans", lambda path: [])
    monkeypatch.setattr(sm.server_net, "port_in_use",
                        lambda port: checked.append(port) or True)
    monkeypatch.setattr(sm.server_net, "port_owner",
                        lambda port: "java.exe (PID 42)")

    def no_java(*a, **kw):
        raise AssertionError("Java ne doit pas être lancé")
    monkeypatch.setattr(sm, "build_launch_command", no_java)

    proc = sm.get_process("srv")
    with pytest.raises(sm.ServerError) as e:
        proc.start()
    assert checked == [25571]                 # server.properties fait foi
    assert "25571" in str(e.value) and "java.exe (PID 42)" in str(e.value)
    assert not proc.is_running()


# ------------------------------------------------------------- duplication

@pytest.fixture
def original(make_server):
    path = make_server("survie", port=25565, playit_auto=True,
                       tunnels=[{"name": "Java", "proto": "tcp",
                                 "address": "x.joinmc.link", "local": 25565}])
    (path / "server.properties").write_text(
        "server-port=25565\nmotd=Survie\n", encoding="utf-8")
    (path / "world" / "region").mkdir(parents=True)
    (path / "world" / "level.dat").write_bytes(b"monde")
    (path / "world" / "session.lock").write_bytes(b"x")
    (path / "logs").mkdir()
    (path / "logs" / "latest.log").write_text("log", encoding="utf-8")
    (path / "plugins").mkdir()
    (path / "plugins" / "AuthMe.jar").write_bytes(b"jar")
    return path


def test_duplicate_server(original):
    meta = sm.duplicate_server("survie", "Survie Test")
    copy = sm.server_dir("survie-test")
    assert meta["name"] == "survie-test" and meta["port"] == 25566
    assert (copy / "world" / "level.dat").read_bytes() == b"monde"
    assert (copy / "plugins" / "AuthMe.jar").exists()
    assert not (copy / "world" / "session.lock").exists()
    assert not (copy / "logs").exists()
    disk = json.loads((copy / sm.META_FILE).read_text("utf-8"))
    assert disk["tunnels"] == [] and disk["playit_auto"] is False
    props = load_properties(copy / "server.properties")
    assert props == {"server-port": "25566", "motd": "Survie"}
    # l'original n'a pas bougé
    assert load_properties(original / "server.properties")["server-port"] \
        == "25565"
    assert sorted(m["name"] for m in sm.list_servers()) == \
        ["survie", "survie-test"]


def test_duplicate_refused_when_name_taken_or_running(original, running_proc):
    sm.duplicate_server("survie", "copie")
    with pytest.raises(sm.ServerError):
        sm.duplicate_server("survie", "copie")
    with pytest.raises(sm.ServerError):
        sm.duplicate_server("inconnu", "autre")
    running_proc("survie")
    with pytest.raises(sm.ServerError):
        sm.duplicate_server("survie", "encore")
    assert not sm.server_dir("encore").exists()


def test_free_port_skips_used_ones(make_server):
    assert sm.free_port() == 25565
    make_server("a", port=25565)
    make_server("b", port=25566)
    make_server("c", port=25568)
    assert sm.free_port() == 25567


# --------------------------------------------------------------- whitelist

def test_whitelist_offline(make_server):
    server = make_server("srv")
    assert banlist.list_whitelist(server) == []
    assert not banlist.whitelist_enabled(server)
    banlist.whitelist_add(server, "Steve")
    banlist.whitelist_add(server, "Alex")
    banlist.whitelist_add(server, "steve")            # pas de doublon
    entries = banlist.list_whitelist(server)
    assert [e["name"] for e in entries] == ["Alex", "steve"]
    assert entries[0]["uuid"] == banlist.offline_uuid("Alex")
    banlist.whitelist_remove(server, "ALEX")
    assert [e["name"] for e in banlist.list_whitelist(server)] == ["steve"]
    banlist.set_whitelist(server, True)
    assert banlist.whitelist_enabled(server)
    assert load_properties(server / "server.properties")["white-list"] \
        == "true"


def test_whitelist_online_uses_commands(running_proc):
    proc = running_proc("srv")
    banlist.whitelist_add(proc.path, "Steve", proc=proc)
    banlist.whitelist_remove(proc.path, "Alex", proc=proc)
    banlist.set_whitelist(proc.path, True, proc=proc)
    banlist.set_whitelist(proc.path, False, proc=proc)
    assert proc.proc.sent == ["whitelist add Steve\n",
                              "whitelist remove Alex\n",
                              "whitelist on\n", "whitelist off\n"]
    assert banlist.list_whitelist(proc.path) == []    # le serveur écrit
    assert not banlist.whitelist_enabled(proc.path)


# ------------------------------------------------------------------ Playit

def test_playit_tunnels_created_once_agent_is_known(monkeypatch):
    """L'agent est lancé avant la création, et un refus AgentVersionTooOld
    (agent pas encore connecté) est retenté au lieu d'échouer."""
    from app.core import playit
    calls, state = [], {"refused": 1, "tunnels": []}

    def fake_call(path, body=None, secret=None, timeout=15):
        calls.append(path)
        if path == "/v1/agents/rundata":
            return {"agent_id": "a1", "tunnels": state["tunnels"],
                    "pending": []}
        assert path == "/tunnels/create" and "start" in calls
        if state["refused"]:
            state["refused"] -= 1
            raise playit.PlayitError("AgentVersionTooOld")
        assert body["origin"]["data"] == {
            "agent_id": "a1", "local_ip": "127.0.0.1", "local_port": 25565}
        state["tunnels"] = [{
            "port_type": body["port_type"], "tunnel_type": body["tunnel_type"],
            "display_address": "x.tun.ply.gg",
            "agent_config": {"fields": [
                {"name": "local_port", "value": "25565"}]}}]

    monkeypatch.setattr(playit, "_call", fake_call)
    monkeypatch.setattr(playit, "secret", lambda: "k")
    monkeypatch.setattr(playit, "start_agent", lambda: calls.append("start"))
    monkeypatch.setattr(playit.time, "sleep", lambda s: None)
    found = playit.ensure_tunnels("survie", [("java", 25565)])
    assert [(f["proto"], f["address"]) for f in found] == [
        ("tcp", "x.tun.ply.gg")]
    assert calls.count("/tunnels/create") == 2


# ------------------------------------------------- anciennes versions, Java

def test_old_versions_get_a_java_they_can_run_on(monkeypatch):
    """Paper 1.16.5 refuse Java 17+, Forge ≤ 1.16.5 plante au-delà de Java 8 :
    le premier Java trouvé (souvent le plus récent) ne convient pas."""
    from app.core import java
    assert java.pinned_java_range("1.12.2") == (8, 8)
    assert java.pinned_java_range("1.16.5") == (8, 8)
    assert java.pinned_java_range("1.17.1") == (16, 17)
    assert java.pinned_java_range("1.20.1") == (17, 21)
    asked = []
    monkeypatch.setattr(java, "find_java",
                        lambda lo=None, hi=None: asked.append((lo, hi))
                        or ("java", lo or 25))
    java.ensure_java("1.16.5", log=lambda m: None)
    java.ensure_java("1.21.4", log=lambda m: None)
    assert asked == [(8, 8), (None, None)]
    # 1.17 : pas de JRE Temurin 16, c'est un 17 qui est téléchargé
    got = []
    monkeypatch.setattr(java, "find_java", lambda lo=None, hi=None:
                        (None, None))
    monkeypatch.setattr(java, "download_jre",
                        lambda major, log=print: got.append(major) or "jre")
    java.ensure_java("1.17.1", log=lambda m: None)
    assert got == [17]


# ---------------------------------------------------------------- cross-play

def test_crossplay_goes_through_viaproxy_when_server_cannot_translate(
        make_server):
    """Geyser parle la dernière version de Java. Un serveur sans ViaVersion
    (Forge, anciennes versions, mods Via retirés) répond « Client
    incompatible » : il faut ViaProxy entre les deux."""
    from app.core import crossplay
    paper = make_server("p", loader="paper", mc_version="1.21.4")
    (paper / "plugins").mkdir()
    assert crossplay.needs_proxy(paper, "paper", "1.21.4")       # pas de Via
    (paper / "plugins" / "ViaVersion-5.jar").write_bytes(b"x")
    assert not crossplay.needs_proxy(paper, "paper", "1.21.4")
    assert crossplay.needs_proxy(paper, "paper", "1.16.5")       # Java 8
    assert crossplay.needs_proxy(paper, "forge", "1.20.1")
    assert crossplay.needs_proxy(paper, "neoforge", "1.21.1")
    fabric = make_server("f", loader="fabric", mc_version="1.21.4")
    (fabric / "mods").mkdir()
    (fabric / "mods" / "ViaFabric-0.4.jar").write_bytes(b"x")
    assert not crossplay.needs_proxy(fabric, "fabric", "1.21.4")


def test_crossplay_config_behind_proxy_uses_offline_auth(make_server):
    """ViaProxy ne transmet pas l'identité Floodgate : derrière lui, Geyser
    doit se connecter en mode hors-ligne, sur le port du proxy."""
    from app.core import crossplay
    server = make_server()
    gdir = crossplay.geyser_dir(server)
    gdir.mkdir()
    (gdir / "config.yml").write_text(
        "bedrock:\n  port: 19132\njava:\n  address: 127.0.0.1\n"
        "  port: 25565\n  auth-type: online\n", encoding="utf-8")
    (server / "plugins" / "floodgate").mkdir(parents=True)
    (server / "plugins" / "floodgate" / "key.pem").write_bytes(b"k")
    (server / "plugins" / "Floodgate-Spigot.jar").write_bytes(b"x")
    assert crossplay.configure(server, 25565, "both") == "floodgate"
    assert crossplay.configure(server, 40123, "both", proxy=True) == "offline"
    text = (gdir / "config.yml").read_text("utf-8")
    assert "port: 40123" in text and "port: 19132" in text
    assert "auth-type: offline" in text


def test_geyser_updated_only_when_a_newer_build_exists(make_server,
                                                        monkeypatch):
    import zipfile
    from app.core import crossplay
    server = make_server()
    jar = crossplay.geyser_dir(server) / crossplay.GEYSER_JAR
    jar.parent.mkdir()
    with zipfile.ZipFile(jar, "w") as z:
        z.writestr("git.properties", "git.build.number=1247\n")

    class R:
        def __init__(self, build):
            self.build = build

        def raise_for_status(self):
            pass

        def json(self):
            return {"build": self.build}
    got = []
    monkeypatch.setattr(crossplay, "download_file",
                        lambda url, dest: got.append(dest))
    monkeypatch.setattr(crossplay.requests, "get", lambda *a, **k: R(1247))
    assert not crossplay.update_geyser(server, log=lambda m: None)
    monkeypatch.setattr(crossplay.requests, "get", lambda *a, **k: R(1250))
    assert crossplay.update_geyser(server, log=lambda m: None)
    assert got == [jar]
