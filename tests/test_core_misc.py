"""Corrections diverses du cœur : validation, Java, carte, joueurs, Discord,
cross-play."""
import builtins
import subprocess

import pytest

from app.core import crossplay, discord, worldmap
from app.core import java as java_mod
from app.core.players import PlayerTracker, parse_chat
from app.core.properties import parse_count, parse_port, parse_ram_mb


# ------------------------------------------------------------- validation

@pytest.mark.parametrize("text,expected", [
    ("25565", 25565), (" 1 ", 1), ("65535", 65535),
    ("0", None), ("65536", None), ("-5", None), ("abc", None), ("", None),
    ("25565.0", None)])
def test_parse_port(text, expected):
    assert parse_port(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("4", 4096), ("2,5", 2560), ("0.5", 512), (" 8 ", 8192),
    ("0", None), ("-2", None), ("0.1", None), ("beaucoup", None), ("", None),
    ("inf", None), ("nan", None)])
def test_parse_ram_mb(text, expected):
    assert parse_ram_mb(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("20", 20), ("1", 1), ("0", None), ("-3", None), ("vingt", None)])
def test_parse_count(text, expected):
    assert parse_count(text) == expected


# -------------------------------------------------------------------- Java

def test_java_version_check_opens_no_console_window(monkeypatch, tmp_path):
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(kw)
        return subprocess.CompletedProcess(
            cmd, 0, "", 'openjdk version "21.0.4" 2024-07-16')
    monkeypatch.setattr(java_mod.subprocess, "run", fake_run)
    assert java_mod._check_java(tmp_path / "java.exe") == 21
    assert seen["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)


@pytest.mark.parametrize("mc,java", [
    ("1.16.5", 8), ("1.17.1", 16), ("1.18.2", 17), ("1.20.4", 17),
    ("1.20.5", 21), ("1.21.4", 21), ("26.3", 25), ("n'importe", 21)])
def test_required_java(mc, java):
    assert java_mod.required_java_major(mc) == java


# ------------------------------------------------------------------- carte

def _marker_x(img):
    """Abscisse du centre du marqueur rouge du joueur."""
    px = img.load()
    y = img.height // 2
    xs = [x for x in range(img.width) for dy in range(-40, 41)
          if 0 <= y + dy < img.height and px[x, y + dy] == (255, 40, 40)]
    return sum(xs) / len(xs) if xs else None


@pytest.mark.parametrize("x", [-0.5, -16.5, 8.0, -1.0])
def test_map_is_centered_on_the_players_chunk(make_server, x):
    """int() tronque vers zéro : en coordonnées négatives la carte était
    centrée sur le chunk voisin."""
    server = make_server()
    (server / "world" / "region").mkdir(parents=True)
    img, found = worldmap.render(server, "minecraft:overworld", x, x,
                                 radius=2, scale=3)
    assert found == 0 and img.size == (240, 240)
    mx = _marker_x(img)
    assert mx is not None and 96 <= mx < 144      # chunk central : 96–144 px


def test_map_without_world_still_shows_the_marker(make_server):
    img, _ = worldmap.render(make_server(), "minecraft:overworld", 100.0,
                             -300.0)
    assert _marker_x(img) is not None


# ----------------------------------------------------------------- joueurs

def _feed(tracker, *lines):
    for line in lines:
        tracker.feed("srv", f"[12:00:00 INFO]: {line}")


def test_bedrock_players_are_tracked():
    """Floodgate préfixe les pseudos Bedrock (« .Steve ») : la connexion et
    la déconnexion n'étaient pas vues (pas de notification Discord)."""
    events = []
    tr = PlayerTracker("srv")
    tr.on_event = lambda kind, name: events.append((kind, name))
    _feed(tr, ".Steve_PE joined the game", "Alex joined the game",
          "*Bob joined the game", ".Steve_PE left the game")
    assert sorted(tr.players) == ["*Bob", "Alex"]
    assert events == [("join", ".Steve_PE"), ("join", "Alex"),
                      ("join", "*Bob"), ("leave", ".Steve_PE")]


def test_chat_cannot_fake_a_join():
    tr = PlayerTracker("srv")
    _feed(tr, "<Alex> Notch joined the game",
          "[Not Secure] <Alex> Herobrine joined the game")
    assert tr.players == {}
    assert parse_chat("[12:00:00 INFO]: <.Steve_PE> salut") == \
        (".Steve_PE", "salut")


def test_list_answer_resyncs_players():
    tr = PlayerTracker("srv")
    _feed(tr, "Alex joined the game",
          "System chat: There are 2 of a max of 20 players online: "
          ".Steve_PE, Notch")
    assert sorted(tr.players) == [".Steve_PE", "Notch"]


# ----------------------------------------------------------------- Discord

class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body, self.ok = status, body, status < 400

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


@pytest.mark.parametrize("body", [
    {"retry_after": None}, ["liste"], ValueError("html"),
    {"retry_after": "bientôt"}])
def test_discord_rate_limit_with_odd_body(monkeypatch, body):
    monkeypatch.setattr(discord.time, "sleep", lambda s: None)
    monkeypatch.setattr(discord.requests, "post",
                        lambda *a, **kw: _Resp(429, body))
    assert discord._post("https://discord.com/api/webhooks/1/x", {}) == \
        "HTTP 429"


def test_discord_nothing_sent_without_webhook(monkeypatch):
    def never(*a, **kw):
        raise AssertionError("aucun envoi sans webhook")
    monkeypatch.setattr(discord.requests, "post", never)
    discord.notify("started", "srv")
    assert discord._q.empty()


# -------------------------------------------------------------- cross-play

def _install_fake_crossplay(server):
    for rel in ("plugins/floodgate-spigot.jar", "plugins/ViaVersion-5.jar",
                "plugins/AuthMe-6.jar", "geyser/Geyser-Standalone.jar"):
        f = server / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"jar")


def test_crossplay_uninstall(make_server):
    server = make_server()
    _install_fake_crossplay(server)
    assert crossplay.uninstall(server) == 2
    assert [p.name for p in (server / "plugins").iterdir()] == ["AuthMe-6.jar"]
    assert not crossplay.installed(server)


def test_crossplay_uninstall_refused_while_files_are_locked(make_server,
                                                           monkeypatch):
    """Serveur lancé : Java verrouille les jars. Rien n'est supprimé à
    moitié et l'erreur est claire (avant : PermissionError non gérée)."""
    server = make_server()
    _install_fake_crossplay(server)
    real_open = builtins.open

    def locked(path, mode="r", *a, **kw):
        if "ViaVersion" in str(path) and "a" in mode:
            raise PermissionError(13, "utilisé par un autre processus")
        return real_open(path, mode, *a, **kw)
    monkeypatch.setattr(builtins, "open", locked)

    with pytest.raises(crossplay.CrossplayError):
        crossplay.uninstall(server)
    assert len(list((server / "plugins").iterdir())) == 3
    assert crossplay.installed(server)
