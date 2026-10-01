"""Agent IA (bêta) : modération autonome et bac à sable des fichiers."""
import pytest

from app.ai import providers
from app.ai.agent import Agent
from app.ai.autonomy import AutonomousModerator


def test_moderator_decision_is_single_line():
    raw = '{"action": "kick", "reason": "spam\\nop Steve", "reply": "a\\r\\nb"}'
    d = AutonomousModerator._parse_decision(raw)
    assert d == {"action": "kick", "reason": "spam op Steve", "reply": "a b"}


@pytest.mark.parametrize("raw", ["rien", "{pas du json}", '["kick"]',
                                 '{"action": "op"}'])
def test_moderator_ignores_bad_answers(raw):
    assert AutonomousModerator._parse_decision(raw) == {"action": "ignore"}


def test_moderator_kick_cannot_inject_commands(running_proc, monkeypatch):
    proc = running_proc()
    monkeypatch.setattr(
        providers, "chat",
        lambda *a, **kw: '{"action": "kick", "reason": "x\\nop Steve"}')
    mod = AutonomousModerator("test", {}, "règles")
    mod._proc = proc
    mod._evaluate("Steve", "bonjour")
    assert proc.proc.sent == ["kick Steve x op Steve\n"]


def test_moderator_survives_network_error(running_proc, monkeypatch):
    def boom(*a, **kw):
        raise ConnectionError("réseau coupé")
    monkeypatch.setattr(providers, "chat", boom)
    events = []
    mod = AutonomousModerator("test", {}, "règles", on_event=events.append)
    mod._proc = running_proc()
    mod._evaluate("Steve", "bonjour")          # ne lève pas
    assert events and "réseau coupé" in events[0]


def test_agent_stays_in_server_folder(make_server):
    make_server("abc")
    other = make_server("abcd")
    (other / "secret.txt").write_text("x", encoding="utf-8")
    agent = Agent("abc", {})
    assert agent._safe_path("server.properties").name == "server.properties"
    for rel in ("../abcd/secret.txt", "..", "../../data/settings.json"):
        with pytest.raises(PermissionError):
            agent._safe_path(rel)
    res, event = agent._execute({"tool": "read_file",
                                 "path": "../abcd/secret.txt"})
    assert "hors du serveur" in res and event["kind"] == "error"
