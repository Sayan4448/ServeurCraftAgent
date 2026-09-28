"""Fiches joueurs hors-ligne : lecture/écriture de `world/playerdata/<uuid>.dat`
(ou `world/players/data` sur les versions récentes) — position exacte, monde,
vie/faim/xp et inventaire complet sans que le joueur soit connecté.

- Serveur lancé ET joueur en ligne → on privilégie les commandes
  (`item replace`, `give`, `clear`) : le serveur écraserait sinon nos
  modifications à la prochaine sauvegarde.
- Sinon → édition directe du .dat NBT (sûr, le fichier n'est pas en mémoire).
"""
import gzip
import json
from pathlib import Path

import nbtlib
from nbtlib import Byte, Compound, Int, List, String

from .banlist import offline_uuid

# dossiers possibles selon la version du serveur
_PDATA_DIRS = ("playerdata", "players/data")
_DIMS = {"minecraft:overworld": "Surface", "minecraft:the_nether": "Nether",
         "minecraft:the_end": "End"}
# slots de l'inventaire (balise Slot de chaque item)
SLOT_OFFHAND = -106
SLOT_ARMOR = (100, 101, 102, 103)          # pieds, jambes, torse, tête
SLOT_MAIN = range(9, 36)                   # 3 lignes de 9
SLOT_HOTBAR = range(0, 9)                  # barre d'accès


class PlayerDataError(Exception):
    pass


def data_dir(server_dir: Path) -> Path:
    """Dossier des .dat joueurs (gère l'ancien et le nouveau layout)."""
    world = Path(server_dir) / "world"
    for rel in _PDATA_DIRS:
        d = world / rel
        if d.exists():
            return d
    return world / _PDATA_DIRS[0]


def _usercache(server_dir: Path) -> dict:
    """name -> uuid d'après usercache.json (joueurs déjà connectés)."""
    try:
        data = json.loads((Path(server_dir) / "usercache.json")
                          .read_text(encoding="utf-8"))
        return {e["name"]: e["uuid"] for e in data
                if "name" in e and "uuid" in e}
    except (OSError, ValueError):
        return {}


_UUID_RE = None


def uuid_for(server_dir: Path, name: str) -> str:
    """uuid d'un joueur : usercache d'abord, sinon uuid hors-ligne."""
    global _UUID_RE
    uc = _usercache(server_dir)
    for n, u in uc.items():
        if n.lower() == name.lower():
            return u
    if _UUID_RE is None:
        import re
        _UUID_RE = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-"
            r"[0-9a-f]{12}$", re.I)
    if _UUID_RE.match(name):            # on a déjà reçu l'uuid
        return name
    return offline_uuid(name)


def file_for(server_dir: Path, name: str) -> Path:
    return data_dir(server_dir) / f"{uuid_for(server_dir, name)}.dat"


def known_players(server_dir: Path) -> list:
    """Pseudos ayant déjà joué (usercache ∪ fichiers .dat)."""
    d = Path(server_dir)
    names = set(_usercache(d))
    pd = data_dir(d)
    if pd.exists():
        uuids = {p.stem for p in pd.glob("*.dat")}
        inv = {u: n for n, u in _usercache(d).items()}
        names.update(inv.get(u, u) for u in uuids)
    return sorted(names, key=str.lower)


def load(server_dir: Path, name: str):
    """Compound NBT du joueur, ou None s'il n'a jamais joué."""
    f = file_for(server_dir, name)
    if not f.exists():
        return None
    try:
        return nbtlib.load(f)
    except (OSError, EOFError, Exception) as e:  # nbtlib lève divers erreurs
        raise PlayerDataError(f"playerdata illisible : {e}")


def save(server_dir: Path, name: str, data) -> Path:
    """Réécrit le .dat gzip (format attendu par le serveur)."""
    f = file_for(server_dir, name)
    f.parent.mkdir(parents=True, exist_ok=True)
    (data if isinstance(data, nbtlib.File)
     else nbtlib.File(data)).save(f, gzipped=True)
    return f


# ------------------------------------------------------------------- infos

def info(data) -> dict:
    """Position, monde, vie… d'un joueur (None si pas de données)."""
    if data is None:
        return {}
    pos = [float(v) for v in data.get("Pos", [])]
    rot = [float(v) for v in data.get("Rotation", [])]
    return {
        "x": pos[0] if len(pos) > 0 else 0.0,
        "y": pos[1] if len(pos) > 1 else 64.0,
        "z": pos[2] if len(pos) > 2 else 0.0,
        "yaw": rot[0] if rot else 0.0,
        "dimension": str(data.get("Dimension", "minecraft:overworld")),
        "dim_label": _DIMS.get(str(data.get("Dimension", "")),
                               str(data.get("Dimension", "?")).split(":")[-1]),
        "health": float(data.get("Health", 20)),
        "food": int(data.get("foodLevel", 20)),
        "xp_level": int(data.get("XpLevel", 0)),
        "gamemode": int(data.get("playerGameType", 0)),
    }


GAMEMODES = {0: "Survie", 1: "Créatif", 2: "Aventure", 3: "Spectateur"}


# --------------------------------------------------------------- inventaire

def _entry(item) -> dict:
    return {"id": str(item.get("id", "minecraft:air")),
            "count": int(item.get("count", item.get("Count", 1))),
            "slot": int(item.get("Slot", 0))}


def inventory(data) -> dict:
    """{slot:int -> {id,count}} pour l'inventaire + l'enderchest."""
    inv, ender = {}, {}
    if data is None:
        return {"inv": inv, "ender": ender}
    for item in data.get("Inventory", []):
        e = _entry(item)
        inv[e["slot"]] = e
    for item in data.get("EnderItems", []):
        e = _entry(item)
        ender[e["slot"]] = e
    return {"inv": inv, "ender": ender}


def _count_type(data):
    """'count' (int) sur 1.20.5+, 'Count' (byte) avant."""
    for it in data.get("Inventory", []):
        return Int if "count" in it else Byte
    return Int


def set_item(data, slot: int, item_id: str, count: int = 1) -> None:
    """Pose un item dans un slot (écriture NBT hors-ligne)."""
    if not item_id.startswith("minecraft:"):
        item_id = "minecraft:" + item_id
    count = max(1, min(int(count), 99))
    inv_list = data.setdefault("Inventory", List[Compound]())
    ct = _count_type(data)
    for item in inv_list:
        if int(item.get("Slot", 0)) == slot:
            item["id"] = String(item_id)
            if "count" in item:
                item["count"] = Int(count)
            else:
                item["Count"] = Byte(count)
            return
    entry = Compound({"Slot": Byte(slot), "id": String(item_id)})
    entry["count" if ct is Int else "Count"] = ct(count)
    inv_list.append(entry)


def remove_item(data, slot: int, ender: bool = False) -> None:
    """Vide un slot."""
    key = "EnderItems" if ender else "Inventory"
    lst = data.get(key)
    if not lst:
        return
    data[key] = List[Compound](
        [it for it in lst if int(it.get("Slot", 0)) != slot])


def clear_inventory(data, ender: bool = False) -> None:
    data["EnderItems" if ender else "Inventory"] = List[Compound]()


def give_item(data, item_id: str, count: int = 1) -> int:
    """Donne un item : premier slot libre, sinon pile existante (hors-ligne).
    Retourne le slot utilisé (-1 si inventaire plein)."""
    if not item_id.startswith("minecraft:"):
        item_id = "minecraft:" + item_id
    inv = inventory(data)["inv"]
    free = next((s for s in range(36) if s not in inv), None)
    if free is None:
        return -1
    set_item(data, free, item_id, count)
    return free


def pretty_name(item_id: str) -> str:
    """minecraft:diamond_sword -> Diamond Sword."""
    return item_id.split(":", 1)[-1].replace("_", " ").title()


def is_online(proc, name: str) -> bool:
    return bool(proc and proc.is_running()
                and name.lower() in {p.lower()
                                     for p in proc.tracker.players})
