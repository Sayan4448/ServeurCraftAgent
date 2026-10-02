"""Fiches joueurs hors-ligne : lecture/écriture de `world/playerdata/<uuid>.dat`
(ou `world/players/data` sur les versions récentes) — position exacte, monde,
vie/faim/xp et inventaire complet sans que le joueur soit connecté.

- Serveur lancé ET joueur en ligne → on privilégie les commandes
  (`item replace`, `give`, `clear`) : le serveur écraserait sinon nos
  modifications à la prochaine sauvegarde.
- Sinon → édition directe du .dat NBT (sûr, le fichier n'est pas en mémoire).
"""
import json
import re
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


_ENTITY_DATA = "has the following entity data: "
_ENTITY_ANSWER = re.compile(r"has the following entity data: |"
                            r"No entity was found")


def load_live(proc, target: str, timeout: float = 3.0):
    """Données d'une entité en direct (`data get entity <target>`), même
    structure que le .dat. Le .dat d'un joueur connecté n'est réécrit qu'à
    la sauvegarde auto (~5 min) : il est périmé. Bloquant ; None si pas de
    réponse. `target` = pseudo ou sélecteur."""
    if not (proc and proc.is_running() and proc.ready):
        return None
    ln = proc.ask(f"data get entity {target}", _ENTITY_ANSWER, timeout)
    i = ln.find(_ENTITY_DATA) if ln else -1
    if i < 0:                         # pas de réponse, ou entité absente
        return None
    try:
        return nbtlib.parse_nbt(ln[i + len(_ENTITY_DATA):].strip())
    except Exception as e:  # noqa: BLE001 — SNBT inattendu
        raise PlayerDataError(f"SNBT illisible : {e}")


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

# 1.21.5+ : armure et main gauche sortent de Inventory -> `equipment`
_EQUIP_SLOTS = {"feet": 100, "legs": 101, "chest": 102, "head": 103,
                "offhand": SLOT_OFFHAND}
# durabilité max (vanilla) par matériau / item
_TIERS = {"wooden": 59, "stone": 131, "iron": 250, "golden": 32,
          "diamond": 1561, "netherite": 2031}
_ARMOR = {"leather": (55, 80, 75, 65), "chainmail": (165, 240, 225, 195),
          "iron": (165, 240, 225, 195), "golden": (77, 112, 105, 91),
          "diamond": (363, 528, 495, 429), "netherite": (407, 592, 555, 481),
          "turtle": (275, 0, 0, 0)}
_ARMOR_PIECES = ("helmet", "chestplate", "leggings", "boots")
_MAX_DAMAGE = {"bow": 384, "crossbow": 465, "trident": 250, "shield": 336,
               "elytra": 432, "fishing_rod": 64, "shears": 238,
               "flint_and_steel": 64, "carrot_on_a_stick": 25,
               "warped_fungus_on_a_stick": 100, "mace": 500, "brush": 64,
               "wolf_armor": 64}


def max_damage(item_id: str) -> int:
    name = item_id.split(":", 1)[-1]
    if name in _MAX_DAMAGE:
        return _MAX_DAMAGE[name]
    mat, _, kind = name.partition("_")
    if kind in ("sword", "pickaxe", "axe", "shovel", "hoe") and mat in _TIERS:
        return _TIERS[mat]
    if kind in _ARMOR_PIECES and mat in _ARMOR:
        return _ARMOR[mat][_ARMOR_PIECES.index(kind)]
    return 0


def _enchants(value) -> list:
    """[(id, niveau)] quel que soit le format (liste < 1.20.5, compound
    {levels:{…}} 1.20.5–1.21.4, compound direct 1.21.5+)."""
    out = []
    if value is None:
        return out
    if isinstance(value, list):
        for e in value:
            try:
                out.append((str(e.get("id", "?")), int(e.get("lvl", 1))))
            except (TypeError, ValueError):
                pass
        return out
    levels = value.get("levels", value) if hasattr(value, "get") else {}
    for k, v in levels.items():
        if k == "show_in_tooltip":
            continue
        try:
            out.append((str(k), int(v)))
        except (TypeError, ValueError):
            pass
    return out


def _custom_name(raw) -> str:
    if raw is None:
        return ""
    if hasattr(raw, "get"):                            # 1.21.5+ : compound
        return str(raw.get("text", ""))
    s = str(raw)
    try:
        j = json.loads(s)
        if isinstance(j, dict):
            return str(j.get("text", "")) + "".join(
                str(x.get("text", "")) if isinstance(x, dict) else str(x)
                for x in j.get("extra", []))
        return str(j)
    except ValueError:
        return s


def _entry(item, slot=None) -> dict:
    item_id = str(item.get("id", "minecraft:air"))
    comp = item.get("components") or {}
    tag = item.get("tag") or {}
    display = tag.get("display") or {}
    dmg = comp.get("minecraft:damage", tag.get("Damage", 0))
    mx = comp.get("minecraft:max_damage", 0) or max_damage(item_id)
    ench = _enchants(comp.get("minecraft:enchantments",
                              tag.get("Enchantments")))
    ench += _enchants(comp.get("minecraft:stored_enchantments",
                               tag.get("StoredEnchantments")))
    return {"id": item_id,
            "count": int(item.get("count", item.get("Count", 1))),
            "slot": int(item.get("Slot", 0)) if slot is None else slot,
            "damage": int(dmg or 0), "max_damage": int(mx or 0),
            "enchants": ench,
            "name": _custom_name(comp.get("minecraft:custom_name",
                                          display.get("Name")))}


def inventory(data) -> dict:
    """{slot:int -> entrée} pour l'inventaire + l'enderchest."""
    inv, ender = {}, {}
    if data is None:
        return {"inv": inv, "ender": ender}
    for item in data.get("Inventory", []):
        e = _entry(item)
        inv[e["slot"]] = e
    for key, slot in _EQUIP_SLOTS.items():
        item = (data.get("equipment") or {}).get(key)
        if item:
            inv[slot] = _entry(item, slot)
    for item in data.get("EnderItems", []):
        e = _entry(item)
        ender[e["slot"]] = e
    return {"inv": inv, "ender": ender}


def _count_type(data):
    """'count' (int) sur 1.20.5+, 'Count' (byte) avant."""
    for it in data.get("Inventory", []):
        return Int if "count" in it else Byte
    return Int


def _items(data, key: str):
    """Liste NBT `key` prête à recevoir des items. Une liste vide relue
    depuis le .dat n'a pas de type d'élément : nbtlib refuse d'y ajouter
    un Compound — elle est alors recréée typée."""
    lst = data.get(key)
    if not isinstance(lst, List[Compound]):
        lst = data[key] = List[Compound](lst or [])
    return lst


def set_item(data, slot: int, item_id: str, count: int = 1) -> None:
    """Pose un item dans un slot (écriture NBT hors-ligne). Sans espace de
    noms : objet de Minecraft ; ceux des mods gardent le leur."""
    if ":" not in item_id:
        item_id = "minecraft:" + item_id
    count = max(1, min(int(count), 99))
    inv_list = _items(data, "Inventory")
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
    equip = data.get("equipment")
    if not ender and equip:
        for k, s in _EQUIP_SLOTS.items():
            if s == slot and k in equip:
                del equip[k]
    lst = data.get(key)
    if not lst:
        return
    data[key] = List[Compound](
        [it for it in lst if int(it.get("Slot", 0)) != slot])


def clear_inventory(data, ender: bool = False) -> None:
    data["EnderItems" if ender else "Inventory"] = List[Compound]()
    equip = data.get("equipment")
    if not ender and equip:
        for k in _EQUIP_SLOTS:
            equip.pop(k, None)


# 1.21.5 (DataVersion 4325) : armure et main gauche dans `equipment`
_EQUIPMENT_DATA_VERSION = 4325


def _uses_equipment(data) -> bool:
    if "equipment" in data:
        return True
    try:
        return int(data.get("DataVersion", 0)) >= _EQUIPMENT_DATA_VERSION
    except (TypeError, ValueError):
        return False


def _equip_key(data, slot: int, ender: bool):
    """Clé `equipment` du slot s'il y est rangé dans ce fichier, sinon None."""
    if ender or not _uses_equipment(data):
        return None
    return next((k for k, s in _EQUIP_SLOTS.items() if s == slot), None)


def _pop(data, slot: int, ender: bool):
    """Retire l'item du slot et le retourne (sans balise Slot), ou None."""
    key = _equip_key(data, slot, ender)
    if key:
        return (data.get("equipment") or {}).pop(key, None)
    lst = data.get("EnderItems" if ender else "Inventory") or []
    for i, it in enumerate(lst):
        if int(it.get("Slot", 0)) == slot:
            item = Compound(it)
            item.pop("Slot", None)
            del lst[i]
            return item
    return None


def _put(data, slot: int, item, ender: bool) -> None:
    key = _equip_key(data, slot, ender)
    if key:
        data.setdefault("equipment", Compound())[key] = item
        return
    item = Compound(item)
    item["Slot"] = Byte(slot)
    _items(data, "EnderItems" if ender else "Inventory").append(item)


def move_item(data, src: int, dst: int, ender: bool = False) -> bool:
    """Déplace l'item de `src` vers `dst` (hors-ligne) ; si `dst` est
    occupé, les deux items sont échangés. False s'il n'y a rien à déplacer."""
    if src == dst:
        return False
    item = _pop(data, src, ender)
    if item is None:
        return False
    other = _pop(data, dst, ender)
    _put(data, dst, item, ender)
    if other is not None:
        _put(data, src, other, ender)
    return True


# ------------------------------------------------- commandes (joueur en ligne)

# slot NBT -> nom de slot des commandes pour l'équipement
_CMD_EQUIP = {SLOT_OFFHAND: "weapon.offhand", 100: "armor.feet",
              101: "armor.legs", 102: "armor.chest", 103: "armor.head"}


def mc_tuple(version) -> tuple:
    """'1.21.4' -> (1, 21, 4) ; '26.1-pre2' -> (26, 1)."""
    out = []
    for part in str(version or "").split("."):
        digits = ""
        for ch in part:
            if not ch.isdigit():
                break
            digits += ch
        if not digits:
            break
        out.append(int(digits))
    return tuple(out)


def has_item_command(mc_version) -> bool:
    """`/item` (avec copie « from entity ») existe depuis la 1.17 ; avant,
    seul `/replaceitem` existe. Version inconnue : on suppose récente."""
    v = mc_tuple(mc_version)
    return not v or v >= (1, 17)


def slot_name(slot: int, ender: bool = False) -> str:
    """Nom du slot pour `/item replace entity`. Le numéro NBT n'est pas le
    numéro de la commande : la barre d'accès (0–8) s'appelle `hotbar.N` et
    le reste de l'inventaire (9–35) `inventory.0` à `inventory.26`."""
    if ender:
        if 0 <= slot <= 26:
            return f"enderchest.{slot}"
    elif 0 <= slot <= 8:
        return f"hotbar.{slot}"
    elif 9 <= slot <= 35:
        return f"inventory.{slot - 9}"
    elif slot in _CMD_EQUIP:
        return _CMD_EQUIP[slot]
    raise PlayerDataError(f"slot inconnu : {slot}")


def remove_command(player: str, slot: int, ender: bool = False,
                   mc_version="") -> str:
    name = slot_name(slot, ender)
    if has_item_command(mc_version):
        return f"item replace entity {player} {name} with air"
    if mc_tuple(mc_version) < (1, 13):            # 1.8 – 1.12
        name = f"slot.{name}"
    return f"replaceitem entity {player} {name} minecraft:air"


def clear_commands(player: str, ender: bool = False, mc_version="") -> list:
    """Vide l'inventaire (une commande) ou l'Ender chest (27 slots)."""
    if not ender:
        return [f"clear {player}"]
    return [remove_command(player, s, True, mc_version) for s in range(27)]


def move_commands(player: str, src: int, dst: int, ender: bool,
                  inv: dict, ender_items: dict, mc_version="") -> list:
    """Commandes qui déplacent l'item de `src` vers `dst` chez un joueur
    connecté — objet copié tel quel (enchantements, nom, durabilité). Si
    `dst` est occupé, les deux sont échangés en passant par une case libre.
    `inv` / `ender_items` : cases occupées ({slot: …}, cf. `inventory()`).
    Lève PlayerDataError si c'est impossible."""
    from ..i18n import t
    if not has_item_command(mc_version):
        raise PlayerDataError(t("pc_move_old"))
    here = ender_items if ender else inv
    if src == dst or src not in here:
        return []
    a, b = slot_name(src, ender), slot_name(dst, ender)

    def copy(to, frm):
        return f"item replace entity {player} {to} from entity {player} {frm}"
    if dst not in here:
        return [copy(b, a), f"item replace entity {player} {a} with air"]
    free = next((slot_name(s) for s in (*SLOT_MAIN, *SLOT_HOTBAR)
                 if s not in inv and (ender or s not in (src, dst))), None) \
        or next((slot_name(s, True) for s in range(27)
                 if s not in ender_items
                 and (not ender or s not in (src, dst))), None)
    if free is None:
        raise PlayerDataError(t("pc_move_full"))
    return [copy(free, b), copy(b, a), copy(a, free),
            f"item replace entity {player} {free} with air"]


def give_item(data, item_id: str, count: int = 1) -> int:
    """Donne un item : premier slot libre, sinon pile existante (hors-ligne).
    Retourne le slot utilisé (-1 si inventaire plein)."""
    if ":" not in item_id:            # les objets de mods gardent leur préfixe
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
