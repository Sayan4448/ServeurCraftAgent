"""Création d'un serveur avec les paramètres par défaut (réseau simulé)."""
import json

import pytest
import requests

from app.core import crossplay, downloader, mods
from app.core import java as java_mod
from app.core import server_manager as sm
from app.core.properties import load_properties

DEFAULTS = {"name": "Mon Serveur", "loader": "paper", "mc_version": "26.3",
            "ram_mb": 4096, "port": 25565, "online_mode": False,
            "accounts": "both", "crossplay": False,
            "props": {"pvp": "true", "spawn-monsters": "true"},
            "voice": "none", "tunnels": [], "playit_auto": False}


@pytest.fixture
def fake_network(monkeypatch, tmp_path):
    """Java, Paper et Modrinth simulés ; toute autre requête fait échouer."""
    calls = {"modrinth": [], "downloads": []}

    def fake_download(url, dest, progress_cb=None):
        calls["downloads"].append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"jar")
        return dest

    def fake_versions(project, loaders, mc_version):
        calls["modrinth"].append((project, tuple(loaders), mc_version))
        return [{"version_type": "release", "project_id": f"id-{project}",
                 "files": [{"primary": True, "url": f"https://cdn/{project}",
                            "filename": f"{project}-1.0.jar"}]}]

    def no_request(*a, **kw):
        raise AssertionError("requête réseau inattendue")

    monkeypatch.setattr(java_mod, "ensure_java",
                        lambda *a, **kw: tmp_path / "java.exe")
    monkeypatch.setattr(downloader, "get_download",
                        lambda *a: ("https://paper/x.jar", "paper.jar", "jar"))
    monkeypatch.setattr(downloader, "download_file", fake_download)
    monkeypatch.setattr(mods, "download_file", fake_download)
    monkeypatch.setattr(crossplay, "download_file", fake_download)
    monkeypatch.setattr(mods, "_modrinth_versions", fake_versions)
    monkeypatch.setattr(mods, "_identify_modrinth", lambda *a: {})
    for name in ("get", "post", "request"):
        monkeypatch.setattr(requests, name, no_request)
    return calls


def test_default_creation(fake_network):
    logs = []
    meta = sm.create_server(dict(DEFAULTS), log=logs.append)
    path = sm.server_dir("mon-serveur")

    assert meta["name"] == "mon-serveur" and meta["accounts"] == "both"
    assert (path / "server.jar").exists()
    assert "eula=true" in (path / "eula.txt").read_text("utf-8")
    props = load_properties(path / "server.properties")
    assert props["online-mode"] == "false" and props["server-port"] == "25565"
    # un seul plugin d'authentification, dans plugins/, pour la bonne version
    assert [p.name for p in (path / "plugins").iterdir()] == \
        ["authmereloaded-1.0.jar"]
    assert fake_network["modrinth"] == [
        ("authmereloaded", ("paper", "spigot", "bukkit"), "26.3")]
    assert not (path / "mods").exists()
    # métadonnées sur disque, sans champ volatil
    disk = json.loads((path / sm.META_FILE).read_text("utf-8"))
    assert disk["loader"] == "paper" and "summary" not in disk
    assert [m["name"] for m in sm.list_servers()] == ["mon-serveur"]


def test_default_creation_needs_no_curseforge_key(fake_network, monkeypatch):
    """Aucune clé n'est fournie, lue ou écrite pendant la création."""
    from app import config
    monkeypatch.delenv(config.CF_KEY_ENV, raising=False)
    sm.create_server(dict(DEFAULTS))
    assert config.curseforge_key() == ""
    assert not config.SETTINGS_FILE.exists()


def test_premium_server_gets_no_auth_plugin(fake_network):
    sm.create_server({**DEFAULTS, "accounts": "premium", "online_mode": True})
    path = sm.server_dir("mon-serveur")
    assert list((path / "plugins").iterdir()) == []
    assert load_properties(path / "server.properties")["online-mode"] == "true"


def test_auth_plugin_failure_does_not_block_creation(fake_network,
                                                     monkeypatch):
    def none_found(*a):
        return []
    monkeypatch.setattr(mods, "_modrinth_versions", none_found)
    logs = []
    sm.create_server(dict(DEFAULTS), log=logs.append)
    assert sm.server_dir("mon-serveur").exists()
    assert any("non installé" in line for line in logs)


def test_failed_download_leaves_nothing_behind(fake_network, monkeypatch):
    def boom(*a, **kw):
        raise requests.ConnectionError("hors ligne")
    monkeypatch.setattr(downloader, "download_file", boom)
    with pytest.raises(requests.ConnectionError):
        sm.create_server(dict(DEFAULTS))
    assert not sm.server_dir("mon-serveur").exists()
    assert sm.list_servers() == []


def test_same_name_twice_is_refused_and_keeps_the_first(fake_network):
    sm.create_server(dict(DEFAULTS))
    with pytest.raises(sm.ServerError):
        sm.create_server(dict(DEFAULTS))
    assert (sm.server_dir("mon-serveur") / "server.jar").exists()


def test_plasmo_voice_gets_no_simple_voice_chat_config(fake_network):
    sm.create_server({**DEFAULTS, "voice": "plasmo_voice"})
    path = sm.server_dir("mon-serveur")
    assert sorted(p.name for p in (path / "plugins").glob("*.jar")) == \
        ["authmereloaded-1.0.jar", "plasmo-voice-1.0.jar"]
    assert not (path / "plugins" / "voicechat").exists()


def test_simple_voice_chat_config_is_written(fake_network):
    sm.create_server({**DEFAULTS, "voice": "simple_voice_chat"})
    cfg = sm.server_dir("mon-serveur") / "plugins" / "voicechat" / \
        "voicechat-server.properties"
    assert load_properties(cfg)["port"] == "24454"


def test_broken_server_folder_does_not_break_the_list(fake_network, app_dirs):
    sm.create_server(dict(DEFAULTS))
    for name, content in (("sans-nom", '{"port": 25565}'),
                          ("casse", "{pas du json"), ("liste", "[1]")):
        d = app_dirs["servers"] / name
        d.mkdir()
        (d / sm.META_FILE).write_text(content, encoding="utf-8")
    assert [m["name"] for m in sm.list_servers()] == ["mon-serveur"]
