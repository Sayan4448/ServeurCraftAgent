"""Suivi des joueurs connectés et actions d'administration via la console."""
import re
import time

# Formats de log Minecraft :
#   [12:34:56] [Server thread/INFO]: <Steve> message
#   [12:34:56] [Server thread/INFO]: Steve joined the game
#   [12:34:56] [Server thread/INFO]: Steve left the game / lost connection
#   [12:34:56] [Server thread/INFO]: There are 2 of a max of 20 players online: Steve, Alex
_NAME = r"([A-Za-z0-9_]{3,16})"
CHAT_RE = re.compile(rf"\]:\s*(?:\[Not Secure\]\s*)?<{_NAME}>\s*(.*)$")
JOIN_RE = re.compile(rf"\]:\s*{_NAME} joined the game")
LEAVE_RE = re.compile(rf"\]:\s*{_NAME} (?:left the game|lost connection)")
LIST_RE = re.compile(r"players online:\s*(.*)$")


def parse_chat(line: str):
    """Retourne (pseudo, message) si la ligne est un message de chat."""
    m = CHAT_RE.search(line)
    if m:
        return m.group(1), m.group(2).strip()
    return None


class PlayerTracker:
    """Maintient la liste des joueurs connectés à partir du flux console."""

    def __init__(self, server_name: str):
        self.server_name = server_name
        self.players = {}          # pseudo -> timestamp de connexion
        self.on_change = None      # callback(set de pseudos)

    def feed(self, name: str, line: str) -> None:
        if name != self.server_name:
            return
        changed = False
        m = JOIN_RE.search(line)
        if m:
            self.players[m.group(1)] = time.time()
            changed = True
        m = LEAVE_RE.search(line)
        if m and self.players.pop(m.group(1), None) is not None:
            changed = True
        m = LIST_RE.search(line)
        if m:
            names = {n.strip() for n in m.group(1).split(",") if n.strip()}
            merged = {}
            now = time.time()
            for n in names:
                merged[n] = self.players.get(n, now)
            if set(merged) != set(self.players):
                self.players = merged
                changed = True
        if changed and self.on_change:
            self.on_change(set(self.players))

    def reset(self):
        self.players.clear()
        if self.on_change:
            self.on_change(set())


# ------------------------------------------------------------- actions admin

def kick(proc, name: str, reason: str = "Expulsé") -> bool:
    return proc.send(f"kick {name} {reason}")


def ban(proc, name: str, reason: str = "Banni") -> bool:
    return proc.send(f"ban {name} {reason}")


def pardon(proc, name: str) -> bool:
    return proc.send(f"pardon {name}")


def ban_ip(proc, name: str) -> bool:
    return proc.send(f"ban-ip {name}")


def op(proc, name: str) -> bool:
    return proc.send(f"op {name}")


def deop(proc, name: str) -> bool:
    return proc.send(f"deop {name}")


def message(proc, name: str, text: str) -> bool:
    return proc.send(f"msg {name} {text}")


def gamemode(proc, name: str, mode: str) -> bool:
    return proc.send(f"gamemode {mode} {name}")


def teleport_here(proc, name: str, target: str) -> bool:
    return proc.send(f"tp {name} {target}")


def kill(proc, name: str) -> bool:
    return proc.send(f"kill {name}")
