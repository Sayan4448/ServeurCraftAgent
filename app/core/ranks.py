"""Grades et catégories des joueurs, persistés par serveur (ranks.json).

Format : {"Steve": {"rank": "Admin", "category": "admin"},
          "Alex":  {"rank": "VIP",   "category": "player"}}
Catégories : "admin" (OP) | "player".
"""
import json
from pathlib import Path

FILE = "ranks.json"
CAT_ADMIN = "admin"
CAT_PLAYER = "player"


def _path(server_dir: Path) -> Path:
    return Path(server_dir) / FILE


def load(server_dir: Path) -> dict:
    p = _path(server_dir)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save(server_dir: Path, data: dict) -> None:
    _path(server_dir).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def set_rank(server_dir: Path, player: str, rank: str,
             category: str = None) -> dict:
    data = load(server_dir)
    entry = data.get(player, {"rank": "", "category": CAT_PLAYER})
    entry["rank"] = rank
    if category:
        entry["category"] = category
    data[player] = entry
    save(server_dir, data)
    return entry


def set_category(server_dir: Path, player: str, category: str) -> dict:
    data = load(server_dir)
    entry = data.get(player, {"rank": "", "category": CAT_PLAYER})
    entry["category"] = category
    data[player] = entry
    save(server_dir, data)
    return entry


def get(data: dict, player: str) -> dict:
    return data.get(player, {"rank": "", "category": CAT_PLAYER})


def remove(server_dir: Path, player: str) -> None:
    data = load(server_dir)
    if data.pop(player, None) is not None:
        save(server_dir, data)


def read_ops(server_dir: Path) -> set:
    """Pseudos OP lus depuis ops.json (écrit par le serveur)."""
    p = Path(server_dir) / "ops.json"
    try:
        return {e["name"] for e in json.loads(p.read_text(encoding="utf-8"))}
    except (json.JSONDecodeError, OSError, KeyError):
        return set()
