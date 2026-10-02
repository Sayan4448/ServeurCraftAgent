"""Inventaire d'un joueur : commandes (en ligne) et édition du .dat."""
import re

import nbtlib
import pytest
from nbtlib import Byte, Compound, End, Int, List, String

from app.core import playerdata as pd


def _item(slot, name, count=1, **components):
    it = Compound({"Slot": Byte(slot), "id": String(f"minecraft:{name}"),
                   "count": Int(count)})
    if components:
        it["components"] = Compound(components)
    return it


@pytest.fixture
def player(make_server):
    """Serveur + .dat de Steve (format 1.21.5+ : armure dans `equipment`)."""
    server = make_server("srv")
    data = Compound({
        "DataVersion": Int(4440),
        "Inventory": List[Compound]([
            _item(0, "diamond_sword",
                  **{"minecraft:enchantments":
                     Compound({"minecraft:sharpness": Int(5)})}),
            _item(9, "oak_log", 64), _item(35, "elytra")]),
        "EnderItems": List[Compound]([_item(0, "diamond_block", 12)]),
        "equipment": Compound({
            "head": Compound({"id": String("minecraft:diamond_helmet"),
                              "count": Int(1)})}),
    })
    pd.save(server, "Steve", nbtlib.File(data))
    return server


def _slots(server):
    inv = pd.inventory(pd.load(server, "Steve"))
    return ({s: e["id"].split(":")[1] for s, e in inv["inv"].items()},
            {s: e["id"].split(":")[1] for s, e in inv["ender"].items()})


# ---------------------------------------------------------------- commandes

@pytest.mark.parametrize("slot,ender,expected", [
    (0, False, "hotbar.0"), (8, False, "hotbar.8"),
    (9, False, "inventory.0"), (18, False, "inventory.9"),
    (35, False, "inventory.26"),
    (100, False, "armor.feet"), (103, False, "armor.head"),
    (-106, False, "weapon.offhand"),
    (0, True, "enderchest.0"), (26, True, "enderchest.26"),
])
def test_slot_name(slot, ender, expected):
    """Le numéro NBT n'est pas celui de la commande (validé sur Paper 26.3 :
    `inventory.27` et plus sont refusés par le serveur)."""
    assert pd.slot_name(slot, ender) == expected


@pytest.mark.parametrize("slot,ender", [(36, False), (27, True), (-1, False)])
def test_slot_name_rejects_unknown(slot, ender):
    with pytest.raises(pd.PlayerDataError):
        pd.slot_name(slot, ender)


def test_remove_command_targets_the_selected_slot():
    assert pd.remove_command("Steve", 9, mc_version="1.21.4") == \
        "item replace entity Steve inventory.0 with air"
    assert pd.remove_command("Steve", 0, mc_version="26.3") == \
        "item replace entity Steve hotbar.0 with air"
    assert pd.remove_command("Steve", 5, True, "1.21.4") == \
        "item replace entity Steve enderchest.5 with air"


def test_remove_command_before_1_17():
    assert pd.remove_command("Steve", 9, mc_version="1.16.5") == \
        "replaceitem entity Steve inventory.0 minecraft:air"
    assert pd.remove_command("Steve", 0, mc_version="1.12.2") == \
        "replaceitem entity Steve slot.hotbar.0 minecraft:air"


def test_move_to_empty_slot_copies_then_clears():
    cmds = pd.move_commands("Steve", 0, 10, False, {0: {}}, {}, "1.21.4")
    assert cmds == [
        "item replace entity Steve inventory.1 from entity Steve hotbar.0",
        "item replace entity Steve hotbar.0 with air"]


def test_move_to_occupied_slot_swaps_through_a_free_slot():
    cmds = pd.move_commands("Steve", 0, 9, False, {0: {}, 9: {}}, {}, "1.21.4")
    assert cmds == [
        "item replace entity Steve inventory.1 from entity Steve inventory.0",
        "item replace entity Steve inventory.0 from entity Steve hotbar.0",
        "item replace entity Steve hotbar.0 from entity Steve inventory.1",
        "item replace entity Steve inventory.1 with air"]


def test_swap_uses_ender_chest_when_inventory_is_full():
    full = {s: {} for s in range(36)}
    cmds = pd.move_commands("Steve", 0, 1, False, full, {0: {}}, "1.21.4")
    assert cmds[0].startswith("item replace entity Steve enderchest.1 from")
    with pytest.raises(pd.PlayerDataError):
        pd.move_commands("Steve", 0, 1, False, full,
                         {s: {} for s in range(27)}, "1.21.4")


def test_move_nothing_or_old_server():
    assert pd.move_commands("Steve", 3, 4, False, {0: {}}, {}, "1.21") == []
    assert pd.move_commands("Steve", 0, 0, False, {0: {}}, {}, "1.21") == []
    with pytest.raises(pd.PlayerDataError):
        pd.move_commands("Steve", 0, 1, False, {0: {}}, {}, "1.16.5")


def test_clear_commands():
    assert pd.clear_commands("Steve") == ["clear Steve"]
    ender = pd.clear_commands("Steve", True, "1.21.4")
    assert len(ender) == 27 and ender[26].endswith("enderchest.26 with air")


@pytest.mark.parametrize("version,expected", [
    ("1.21.4", (1, 21, 4)), ("26.3", (26, 3)), ("26.1-pre2", (26, 1)),
    ("", ()), (None, ())])
def test_mc_tuple(version, expected):
    assert pd.mc_tuple(version) == expected


# ------------------------------------------------------------ fichier .dat

def test_offline_move_keeps_the_item_intact(player):
    data = pd.load(player, "Steve")
    assert pd.move_item(data, 0, 20)
    pd.save(player, "Steve", data)
    inv, _ = _slots(player)
    assert 0 not in inv and inv[20] == "diamond_sword"
    moved = pd.inventory(pd.load(player, "Steve"))["inv"][20]
    assert moved["enchants"] == [("minecraft:sharpness", 5)]


def test_offline_move_swaps_occupied_slots(player):
    data = pd.load(player, "Steve")
    assert pd.move_item(data, 0, 9)
    pd.save(player, "Steve", data)
    inv, _ = _slots(player)
    assert inv[0] == "oak_log" and inv[9] == "diamond_sword"
    assert pd.inventory(pd.load(player, "Steve"))["inv"][0]["count"] == 64


def test_offline_move_between_inventory_and_armor(player):
    data = pd.load(player, "Steve")
    assert pd.move_item(data, 103, 5)             # casque -> barre
    assert pd.move_item(data, 35, 102)            # élytres -> torse
    pd.save(player, "Steve", data)
    inv, _ = _slots(player)
    assert inv[5] == "diamond_helmet" and inv[102] == "elytra"
    assert 103 not in inv and 35 not in inv
    raw = pd.load(player, "Steve")
    assert "chest" in raw["equipment"] and "head" not in raw["equipment"]
    assert "Slot" not in raw["equipment"]["chest"]


def test_offline_move_in_ender_chest(player):
    data = pd.load(player, "Steve")
    assert pd.move_item(data, 0, 26, ender=True)
    pd.save(player, "Steve", data)
    _, ender = _slots(player)
    assert ender == {26: "diamond_block"}


def test_offline_move_from_empty_slot_changes_nothing(player):
    data = pd.load(player, "Steve")
    assert not pd.move_item(data, 4, 5)
    assert not pd.move_item(data, 0, 0)


def test_legacy_armor_stays_in_inventory_list(make_server):
    server = make_server("old")
    data = Compound({"DataVersion": Int(3953), "Inventory": List[Compound]([
        Compound({"Slot": Byte(103), "id": String("minecraft:iron_helmet"),
                  "Count": Byte(1)})])})
    assert pd.move_item(data, 103, 0)
    assert "equipment" not in data
    assert int(data["Inventory"][0]["Slot"]) == 0


def test_offline_remove_and_clear(player):
    data = pd.load(player, "Steve")
    pd.remove_item(data, 9)
    pd.remove_item(data, 103)
    pd.save(player, "Steve", data)
    inv, ender = _slots(player)
    assert set(inv) == {0, 35} and ender == {0: "diamond_block"}
    data = pd.load(player, "Steve")
    pd.clear_inventory(data)
    pd.save(player, "Steve", data)
    assert _slots(player) == ({}, {0: "diamond_block"})


def test_give_after_inventory_was_emptied(player):
    """Le jeu écrit une liste vide sans type d'élément (End) : nbtlib
    refusait d'y ajouter un objet (IncompatibleItemType)."""
    data = pd.load(player, "Steve")
    data["Inventory"] = List[End]()
    data["EnderItems"] = List[End]()
    pd.save(player, "Steve", data)
    data = pd.load(player, "Steve")
    assert pd.move_item(data, 103, 4)             # casque -> liste vide
    assert pd.give_item(data, "diamond", 3) == 0
    pd.save(player, "Steve", data)
    assert _slots(player)[0] == {0: "diamond", 4: "diamond_helmet"}


# ------------------------------------------------------- réponse du serveur

def test_ask_returns_the_server_answer(running_proc):
    proc = running_proc()
    pattern = re.compile(r"Replaced|No entity was found")

    class Echo:
        def write(self, text):
            proc.log("[12:00:00 INFO]: System chat: No entity was found",
                     quiet=True)

        def flush(self):
            pass
    proc.proc.stdin = Echo()
    assert "No entity was found" in proc.ask("item replace …", pattern, 1.0)


def test_ask_gives_up_without_answer(running_proc):
    proc = running_proc()
    assert proc.ask("item replace …", re.compile("Replaced"), 0.2) is None


def test_modded_item_keeps_its_namespace_offline():
    """Le catalogue donne aussi les objets des mods : `create:wrench` ne
    doit pas devenir `minecraft:create:wrench` dans le .dat."""
    import nbtlib
    from app.core import playerdata as pd
    data = nbtlib.Compound({"Inventory": nbtlib.List[nbtlib.Compound]()})
    assert pd.give_item(data, "farmersdelight:apple_pie", 16) == 0
    assert pd.give_item(data, "stone") == 1
    inv = pd.inventory(data)["inv"]
    assert (inv[0]["id"], inv[0]["count"]) == ("farmersdelight:apple_pie", 16)
    assert inv[1]["id"] == "minecraft:stone"
