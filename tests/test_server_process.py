"""ServerProcess : fin de process, crash, envoi de commandes."""
from app.core import discord, playit
from app.core import server_manager as sm


def _events(monkeypatch):
    sent = []
    monkeypatch.setattr(discord, "notify",
                        lambda event, *a, **kw: sent.append(event))
    monkeypatch.setattr(playit, "release", lambda procs: None)
    return sent


def test_restart_is_not_reported_as_crash(running_proc, monkeypatch):
    """Redémarrage : start() remet stop_requested à False pendant que le
    thread de fin arrête Geyser — ce n'est pas un crash."""
    sent = _events(monkeypatch)
    proc = running_proc(crash_action="auto")
    fake = proc.proc
    fake.returncode = 0
    proc.stop_requested = True

    def slow_geyser_stop():           # le redémarrage a déjà relancé start()
        proc.stop_requested = False
        proc.ready = False
    monkeypatch.setattr(proc, "_stop_geyser", slow_geyser_stop)

    proc._waiter(fake)

    assert sent == ["stopped"]
    assert not proc.crash_prompt
    assert not proc.crashes


def test_unexpected_exit_is_a_crash(running_proc, monkeypatch):
    sent = _events(monkeypatch)
    proc = running_proc(crash_action="ask")
    fake = proc.proc
    fake.returncode = 1

    proc._waiter(fake)

    assert sent == ["crashed"]
    assert proc.crash_prompt
    assert proc.exit_code == 1


def test_playit_agent_kept_during_restart(running_proc, monkeypatch):
    stopped = []
    monkeypatch.setattr(playit, "stop_agent", lambda: stopped.append(1))
    proc = running_proc(playit_auto=True)
    proc.proc.returncode = 0          # arrêté…
    proc._starting = True             # …mais en cours de redémarrage

    playit.release([proc])
    assert not stopped

    proc._starting = False
    playit.release([proc])
    assert stopped
