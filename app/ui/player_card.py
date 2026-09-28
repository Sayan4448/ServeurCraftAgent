"""Fiche joueur : carte top-down du monde autour de lui + coordonnées
exactes + inventaire consultable et modifiable (slots, ender chest).

- Position : `data get entity … Pos` en live si le joueur est en ligne,
  sinon sa dernière position enregistrée (playerdata .dat).
- Inventaire : serveur lancé + joueur en ligne → commandes
  `item replace`/`give`/`clear` ; sinon édition directe du .dat NBT.
"""
import io
import re
import threading
from pathlib import Path

import requests
import customtkinter as ctk
from PIL import Image

from ..core import playerdata as pd
from ..core import server_manager
from ..core import worldmap

MINOTAR = "https://minotar.net/helm/{}/64.png"
from ..i18n import t
from . import theme
from .uithread import ui_call

# correspondance slot NBT -> nom de slot pour `item replace entity`
_CMD_SLOT = {pd.SLOT_OFFHAND: "weapon.offhand", 100: "armor.feet",
             101: "armor.legs", 102: "armor.chest", 103: "armor.head"}

# petit catalogue pour le bouton « Donner » (id minecraft + joli nom)
GIVE_ITEMS = [
    "diamond", "diamond_sword", "diamond_pickaxe", "diamond_axe",
    "diamond_shovel", "diamond_hoe", "netherite_sword", "netherite_pickaxe",
    "iron_sword", "iron_pickaxe", "golden_apple", "enchanted_golden_apple",
    "bow", "crossbow", "arrow", "trident", "shield", "totem_of_undying",
    "elytra", "firework_rocket", "ender_pearl", "ender_eye", "compass",
    "clock", "map", "fishing_rod", "shears", "flint_and_steel",
    "torch", "lantern", "bread", "cooked_beef", "cooked_porkchop",
    "golden_carrot", "cake", "pumpkin_pie", "cookie",
    "oak_log", "spruce_log", "birch_log", "oak_planks", "stone",
    "cobblestone", "stone_bricks", "bricks", "glass", "sand", "gravel",
    "dirt", "grass_block", "oak_sapling", "bed", "chest", "crafting_table",
    "furnace", "anvil", "enchanting_table", "bookshelf", "tnt",
    "water_bucket", "lava_bucket", "bucket", "iron_block", "gold_block",
    "diamond_block", "emerald_block", "obsidian", "crying_obsidian",
    "beacon", "conduit", "nether_star", "dragon_egg", "experience_bottle",
    "name_tag", "saddle", "lead", "minecart", "boat", "rail",
    "spyglass", "amethyst_shard", "echo_shard", "recovery_compass",
]

_POS_RE = re.compile(r"\[(-?[\d.]+)d?,\s*(-?[\d.]+)d?,\s*(-?[\d.]+)d?\]")


def _slot_cmd(slot: int, ender: bool) -> str:
    if ender:
        return f"enderchest.{slot}"
    if slot in _CMD_SLOT:
        return _CMD_SLOT[slot]
    return f"inventory.{slot}"


class PlayerCard(ctk.CTkToplevel):
    def __init__(self, master, proc, name: str):
        super().__init__(master)
        self.proc = proc
        self.name = name
        self.dir = Path(proc.path)
        self.data = None                # compound NBT courant
        self._sel = None                # (slot, ender)
        self._map_img = None            # CTkImage à garder en référence
        self._alive = True

        self.title(t("pc_title", name=name))
        self.geometry("980x560")
        self.minsize(880, 500)
        self.configure(fg_color=theme.BG)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ------------------------------------------------------- en-tête
        head = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=10)
        head.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10,
                  pady=10)
        self.head_lbl = ctk.CTkLabel(head, text="", width=48, height=48)
        self.head_lbl.pack(side="left", padx=12, pady=10)
        info = ctk.CTkFrame(head, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True, pady=8)
        self.name_lbl = ctk.CTkLabel(
            info, text=name, font=(theme.FONT, 16, "bold"),
            text_color=theme.TEXT, anchor="w")
        self.name_lbl.pack(anchor="w")
        self.pos_lbl = ctk.CTkLabel(info, text="…", font=(theme.FONT_MONO, 11),
                                    text_color=theme.ACCENT, anchor="w")
        self.pos_lbl.pack(anchor="w")
        self.vital_lbl = ctk.CTkLabel(info, text="", font=(theme.FONT, 11),
                                      text_color=theme.MUTED, anchor="w")
        self.vital_lbl.pack(anchor="w")
        self.online_lbl = ctk.CTkLabel(head, text="", font=(theme.FONT, 11,
                                                          "bold"))
        self.online_lbl.pack(side="right", padx=14)

        # --------------------------------------------------- carte (gauche)
        left = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=10)
        left.grid(row=1, column=0, sticky="nsew", padx=(10, 5), pady=(0, 10))
        ctk.CTkLabel(left, text=t("pc_map"), font=(theme.FONT, 12, "bold"),
                     text_color=theme.TEXT).pack(anchor="w", padx=10,
                                                 pady=(8, 4))
        self.map_lbl = ctk.CTkLabel(left, text=t("pc_loading"),
                                    width=336, height=336,
                                    fg_color=theme.PANEL_2, corner_radius=8,
                                    font=(theme.FONT, 11),
                                    text_color=theme.MUTED)
        self.map_lbl.pack(padx=10, pady=4)
        zoom = ctk.CTkFrame(left, fg_color="transparent")
        zoom.pack(pady=4)
        ctk.CTkLabel(zoom, text=t("pc_zoom"), font=(theme.FONT, 11),
                     text_color=theme.MUTED).pack(side="left", padx=4)
        self.zoom_seg = ctk.CTkSegmentedButton(
            zoom, values=["1", "2", "4"], command=lambda _v: self._load_map(),
            font=(theme.FONT, 11), selected_color=theme.ACCENT,
            selected_hover_color=theme.ACCENT_HOVER,
            unselected_color=theme.PANEL_2,
            unselected_hover_color=theme.HOVER, text_color=theme.TEXT)
        self.zoom_seg.set("2")
        self.zoom_seg.pack(side="left")
        ctk.CTkButton(left, text="⟳ " + t("pc_refresh"), height=28,
                      font=(theme.FONT, 11), fg_color=theme.PANEL_2,
                      hover_color=theme.HOVER, text_color=theme.TEXT,
                      command=self.refresh).pack(pady=(4, 10))

        # ------------------------------------------------ inventaire (droite)
        right = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=10)
        right.grid(row=1, column=1, sticky="nsew", padx=(5, 10),
                   pady=(0, 10))
        right.grid_columnconfigure(0, weight=1)
        top = ctk.CTkFrame(right, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 4))
        self.inv_seg = ctk.CTkSegmentedButton(
            top, values=[t("pc_inv"), t("pc_ender")],
            command=lambda _v: self._render_inv(),
            font=(theme.FONT, 11), selected_color=theme.ACCENT,
            selected_hover_color=theme.ACCENT_HOVER,
            unselected_color=theme.PANEL_2,
            unselected_hover_color=theme.HOVER, text_color=theme.TEXT)
        self.inv_seg.set(t("pc_inv"))
        self.inv_seg.pack(side="left")
        ctk.CTkButton(top, text="⟳ " + t("pc_refresh"), height=28,
                      font=(theme.FONT, 11), fg_color=theme.PANEL_2,
                      hover_color=theme.HOVER, text_color=theme.TEXT,
                      command=self.refresh).pack(side="right")

        self.grid_f = ctk.CTkFrame(right, fg_color=theme.PANEL_2,
                                 corner_radius=8)
        self.grid_f.grid(row=1, column=0, sticky="nsew", padx=10, pady=6)

        btns = ctk.CTkFrame(right, fg_color="transparent")
        btns.grid(row=2, column=0, sticky="ew", padx=10, pady=(2, 4))
        ctk.CTkButton(btns, text="🎁 " + t("pc_give"), height=32,
                      font=(theme.FONT, 12, "bold"), fg_color=theme.GREEN,
                      hover_color=theme.GREEN_HOVER,
                      text_color=theme.ON_GREEN,
                      command=self._give_dialog).pack(
            side="left", expand=True, fill="x", padx=(0, 4))
        ctk.CTkButton(btns, text="✕ " + t("pc_remove"), height=32,
                      font=(theme.FONT, 12), fg_color=theme.PANEL_2,
                      hover_color=theme.HOVER, text_color=theme.TEXT,
                      command=self._remove_sel).pack(
            side="left", expand=True, fill="x", padx=4)
        ctk.CTkButton(btns, text="🗑 " + t("pc_clear"), height=32,
                      font=(theme.FONT, 12), fg_color=theme.PANEL_2,
                      hover_color=theme.RED, text_color=theme.TEXT,
                      command=self._clear_all).pack(
            side="left", expand=True, fill="x", padx=(4, 0))

        self.status = ctk.CTkLabel(right, text="", font=(theme.FONT, 10),
                                   text_color=theme.MUTED, anchor="w")
        self.status.grid(row=3, column=0, sticky="w", padx=12, pady=(0, 8))

        self.refresh()
        self._load_head()

    # ------------------------------------------------------------ données

    def _close(self):
        self._alive = False
        self.destroy()

    def refresh(self):
        """Recharge playerdata + position live si possible."""
        name, proc = self.name, self.proc
        online = pd.is_online(proc, name)

        def work():
            try:
                data = pd.load(self.dir, name)
                inf = pd.info(data)
                if online:                       # position en direct
                    pos = self._fetch_pos()
                    if pos:
                        inf.update(x=pos[0], y=pos[1], z=pos[2])
                ui_call(self, self._apply_data, data, inf, online)
            except Exception as e:  # noqa: BLE001
                ui_call(self, self._err, str(e))
        threading.Thread(target=work, daemon=True).start()

    def _fetch_pos(self):
        """`data get entity <joueur> Pos` -> (x,y,z) live, ou None."""
        proc = self.proc
        if not (proc and proc.is_running() and proc.ready):
            return None
        import time
        _lines, seen = proc.lines_since(0)
        if not proc.send_quiet(f"data get entity {self.name} Pos"):
            return None
        end = time.time() + 2.0
        while time.time() < end:
            time.sleep(0.15)
            lines, seen = proc.lines_since(seen)
            for ln in lines:
                ln = ln.lstrip(server_manager.QUIET_MARK)
                if "entity data" in ln:
                    m = _POS_RE.search(ln)
                    if m:
                        return tuple(float(g) for g in m.groups())
        return None

    def _err(self, msg):
        if self._alive:
            self.status.configure(text=t("pc_error", e=msg))

    def _apply_data(self, data, inf, online):
        if not self._alive:
            return
        self.data = data
        self.online_lbl.configure(
            text=t("pc_online") if online else t("pc_offline"),
            text_color=theme.GREEN if online else theme.MUTED)
        if not inf:
            self.pos_lbl.configure(text=t("pc_never"))
            self.vital_lbl.configure(text="")
        else:
            self.pos_lbl.configure(
                text="X {:+.1f}   Y {:.0f}   Z {:+.1f}   ·   {}".format(
                    inf["x"], inf["y"], inf["z"], inf["dim_label"]))
            self.vital_lbl.configure(
                text="❤ {}    🍗 {}    ✦ {}    ⌖ {}".format(
                    int(inf["health"]), inf["food"], inf["xp_level"],
                    pd.GAMEMODES.get(inf["gamemode"], "?")))
        self._render_inv()
        self._load_map()

    def _load_head(self):
        name = self.name

        def work():
            try:
                r = requests.get(MINOTAR.format(name), timeout=8)
                if r.ok:
                    ui_call(self, self._set_head,
                            Image.open(io.BytesIO(r.content)))
            except Exception:  # noqa: BLE001
                pass
        threading.Thread(target=work, daemon=True).start()

    def _set_head(self, img: Image.Image):
        if not self._alive:
            return
        self._head_ctk = ctk.CTkImage(img, size=(48, 48))
        self.head_lbl.configure(image=self._head_ctk, text="")

    # ------------------------------------------------------------- carte

    def _load_map(self):
        if not self.data:
            return
        inf = pd.info(self.data)
        radius = int(self.zoom_seg.get())
        dim = inf["dimension"]

        def work():
            try:
                img, n = worldmap.render(self.dir, dim, inf["x"], inf["z"],
                                         yaw=inf["yaw"], radius=radius)
                ui_call(self, self._show_map, img, n)
            except Exception as e:  # noqa: BLE001
                ui_call(self, self.map_lbl.configure,
                        {"text": str(e)[:60], "image": ""})
        threading.Thread(target=work, daemon=True).start()

    def _show_map(self, img, n):
        if not self._alive:
            return
        self._map_img = ctk.CTkImage(img, size=(336, 336))
        self.map_lbl.configure(image=self._map_img, text="")
        self.status.configure(text=t("pc_chunks", n=n))

    # -------------------------------------------------------- inventaire

    def _render_inv(self):
        for w in self.grid_f.winfo_children():
            w.destroy()
        ender = self.inv_seg.get() == t("pc_ender")
        inv = pd.inventory(self.data)
        items = inv["ender" if ender else "inv"]
        on = pd.is_online(self.proc, self.name)

        def slot(r, c, s):
            it = items.get(s)
            txt, col = "", theme.PANEL
            if it:
                short = pd.pretty_name(it["id"])
                txt = (short[:14] + ("…" if len(short) > 14 else "")
                       + (f"\n×{it['count']}" if it["count"] > 1 else ""))
                col = theme.PANEL_2
            sel = self._sel == (s, ender)
            b = ctk.CTkButton(
                self.grid_f, text=txt, width=58, height=44,
                font=(theme.FONT, 9), corner_radius=6, fg_color=col,
                hover_color=theme.HOVER, text_color=theme.TEXT,
                border_width=2,
                border_color=theme.ACCENT if sel else theme.BORDER,
                command=lambda x=s: self._select(x, ender))
            b.grid(row=r, column=c, padx=2, pady=2)

        if ender:
            for i, s in enumerate(range(27)):
                slot(i // 9, i % 9, s)
        else:
            # armure : tête, torse, jambes, pieds + main gauche
            for i, s in enumerate((103, 102, 101, 100, pd.SLOT_OFFHAND)):
                slot(0, i, s)
            for j in (1, 2, 3):             # inventaire principal 9..35
                for i, s in enumerate(range(9 + j * 9 - 9,
                                            9 + j * 9)):
                    slot(j, i, s)
            for i, s in enumerate(range(9)):  # hotbar
                slot(4, i, s)
        hint = t("pc_hint_online" if on else "pc_hint_offline")
        self.status.configure(text=hint)

    def _select(self, slot, ender):
        self._sel = (slot, ender)
        self._render_inv()

    # ---------------------------------------------------------- actions

    def _remove_sel(self):
        if not self._sel:
            self.status.configure(text=t("pc_select_first"))
            return
        slot, ender = self._sel
        if pd.is_online(self.proc, self.name):
            self.proc.send_quiet(
                f"item replace entity {self.name} "
                f"{_slot_cmd(slot, ender)} with air")
            self.status.configure(text="→ item replace … with air")
        else:
            if not self.data:
                return
            pd.remove_item(self.data, slot, ender)
            pd.save(self.dir, self.name, self.data)
            self.status.configure(text=t("pc_saved"))
        self._sel = None
        self.after(800, self.refresh)

    def _clear_all(self):
        from tkinter import messagebox
        if not messagebox.askyesno(t("pc_clear"),
                                   t("pc_clear_confirm", name=self.name),
                                   parent=self):
            return
        ender = self.inv_seg.get() == t("pc_ender")
        if pd.is_online(self.proc, self.name):
            if ender:
                for s in range(27):
                    self.proc.send_quiet(
                        f"item replace entity {self.name} enderchest.{s} "
                        "with air")
            else:
                self.proc.send_quiet(f"clear {self.name}")
        else:
            if not self.data:
                return
            pd.clear_inventory(self.data, ender)
            pd.save(self.dir, self.name, self.data)
        self._sel = None
        self.after(800, self.refresh)

    def _give_dialog(self):
        dlg = _GiveDialog(self)
        self.wait_window(dlg)
        if not dlg.result:
            return
        item, count = dlg.result
        if pd.is_online(self.proc, self.name):
            if self.proc.send_quiet(
                    f"give {self.name} minecraft:{item} {count}"):
                self.status.configure(
                    text=f"→ give {self.name} {item} ×{count}")
            self.after(800, self.refresh)
            return
        if self.data is None:          # jamais connecté -> nouveau .dat
            import nbtlib
            self.data = nbtlib.File(nbtlib.Compound(
                {"Inventory": nbtlib.List[nbtlib.Compound]()}))
        slot = pd.give_item(self.data, item, count)
        if slot < 0:
            self.status.configure(text=t("pc_full"))
            return
        pd.save(self.dir, self.name, self.data)
        self.status.configure(text=t("pc_saved"))
        self.refresh()


class _GiveDialog(ctk.CTkToplevel):
    """Choix d'un item (liste filtrable) + quantité."""

    def __init__(self, master):
        super().__init__(master)
        self.result = None
        self.title(t("pc_give"))
        self.geometry("380x430")
        self.configure(fg_color=theme.BG)
        self.transient(master)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self.q = ctk.CTkEntry(self, placeholder_text=t("pc_give_ph"),
                              fg_color=theme.PANEL_2,
                              border_color=theme.BORDER,
                              text_color=theme.TEXT, height=32)
        self.q.grid(row=0, column=0, columnspan=2, sticky="ew", padx=12,
                    pady=(12, 4))
        self.q.bind("<KeyRelease>", lambda _e: self._filter())
        self.count = ctk.CTkEntry(self, width=70, height=32,
                                  fg_color=theme.PANEL_2,
                                  border_color=theme.BORDER,
                                  text_color=theme.TEXT)
        self.count.insert(0, "1")
        self.count.grid(row=0, column=2, padx=(4, 12), pady=(12, 4))
        self.list_f = ctk.CTkScrollableFrame(
            self, fg_color=theme.PANEL,
            scrollbar_button_color=theme.PANEL_2)
        self.list_f.grid(row=2, column=0, columnspan=3, sticky="nsew",
                         padx=12, pady=6)
        ctk.CTkButton(self, text=t("pc_give"), height=36,
                      font=(theme.FONT, 12, "bold"), fg_color=theme.GREEN,
                      hover_color=theme.GREEN_HOVER,
                      text_color=theme.ON_GREEN,
                      command=self._ok).grid(row=3, column=0, columnspan=3,
                                             sticky="ew", padx=12,
                                             pady=(4, 12))
        self._sel_item = None
        self._rows = {}
        self._filter()
        self.q.focus()
        self.grab_set()

    def _filter(self):
        q = self.q.get().strip().lower()
        for w in self.list_f.winfo_children():
            w.destroy()
        self._rows = {}
        for item in GIVE_ITEMS:
            if q and q not in item:
                continue
            sel = self._sel_item == item
            b = ctk.CTkButton(
                self.list_f, text=pd.pretty_name(f"minecraft:{item}"),
                anchor="w", font=(theme.FONT, 11), height=28,
                fg_color=theme.ACCENT if sel else "transparent",
                hover_color=theme.HOVER, text_color=theme.TEXT,
                command=lambda i=item: self._pick(i))
            b.pack(fill="x", pady=1)
            self._rows[item] = b

    def _pick(self, item):
        self._sel_item = item
        self._filter()

    def _ok(self):
        item = self._sel_item or self.q.get().strip().lower().replace(
            " ", "_")
        if not item:
            return
        try:
            count = max(1, min(int(self.count.get()), 64))
        except ValueError:
            count = 1
        self.result = (item, count)
        self.destroy()
