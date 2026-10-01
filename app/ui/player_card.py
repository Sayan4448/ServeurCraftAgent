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
import tkinter as tk
from pathlib import Path

import requests
import customtkinter as ctk
from PIL import Image

from ..core import item_icons
from ..core import playerdata as pd
from ..core import worldmap
from ..i18n import t
from . import theme
from .inventory_view import InventoryView
from .uithread import ui_call

MINOTAR = "https://minotar.net/helm/{}/64.png"
MINOTAR_BODY = "https://minotar.net/armor/body/{}/100.png"

# Réponses du serveur aux commandes d'inventaire (pour vérifier qu'une
# modification a bien été appliquée) et, parmi elles, les refus.
_FAIL = (r"No entity was found|No player was found|Could not|Can't|"
         r"Unknown|Incorrect|Expected|<--\[HERE\]")
_ANSWER = re.compile(r"Replaced|Removed \d+ item|No items were found|Gave |"
                     + _FAIL)
_REFUSED = re.compile(_FAIL)
_LOG_PREFIX = re.compile(r"^.*?\]:\s*(?:System chat:\s*)?")

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
_POS_ANSWER = re.compile(r"entity data|No entity was found")


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
        self._loading = False           # lecture des données en cours
        self._busy = False              # commandes en cours d'envoi
        self._note = ""                 # résultat de la dernière action

        self.title(t("pc_title", name=name))
        self.geometry("1040x640")
        self.minsize(900, 560)
        self.configure(fg_color=theme.BG)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

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
            font=(theme.FONT, 11), **theme.SEG)
        self.zoom_seg.set("2")
        self.zoom_seg.pack(side="left")
        self.map_info = ctk.CTkLabel(left, text="", font=(theme.FONT, 10),
                                     text_color=theme.MUTED)
        self.map_info.pack()
        ctk.CTkButton(left, height=28,
                      font=(theme.FONT, 11), fg_color=theme.PANEL_2,
                      hover_color=theme.HOVER, text_color=theme.TEXT,
                      command=self.refresh,
                      **theme.labelled("restart", t("pc_refresh"), "⟳", 13)
                      ).pack(pady=(4, 10))

        # ------------------------------------------------ inventaire (droite)
        right = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=10)
        right.grid(row=1, column=1, sticky="nsew", padx=(5, 10),
                   pady=(0, 10))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)
        top = ctk.CTkFrame(right, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 4))
        self.inv_seg = ctk.CTkSegmentedButton(
            top, values=[t("pc_inv"), t("pc_ender")],
            command=lambda _v: self._render_inv(),
            font=(theme.FONT, 11), **theme.SEG)
        self.inv_seg.set(t("pc_inv"))
        self.inv_seg.pack(side="left")
        ctk.CTkButton(top, height=28,
                      font=(theme.FONT, 11), fg_color=theme.PANEL_2,
                      hover_color=theme.HOVER, text_color=theme.TEXT,
                      command=self.refresh,
                      **theme.labelled("restart", t("pc_refresh"), "⟳", 13)
                      ).pack(side="right")
        ctk.CTkButton(top, height=28,
                      font=(theme.FONT, 11), fg_color=theme.PANEL_2,
                      hover_color=theme.HOVER, text_color=theme.TEXT,
                      command=self._export,
                      **theme.labelled("camera", t("inv_export"), "📷", 13)
                      ).pack(side="right", padx=6)

        self.inv_view = InventoryView(right, on_select=self._select_slot,
                                      on_move=self._move,
                                      on_context=self._slot_menu)
        self.inv_view.grid(row=1, column=0, sticky="nsew", padx=10, pady=6)
        self.bind("<Delete>", lambda _e: self._remove_sel())

        btns = ctk.CTkFrame(right, fg_color="transparent")
        btns.grid(row=2, column=0, sticky="ew", padx=10, pady=(2, 4))
        ctk.CTkButton(btns, height=32,
                      font=(theme.FONT, 12, "bold"), fg_color=theme.GREEN,
                      hover_color=theme.GREEN_HOVER,
                      text_color=theme.ON_GREEN,
                      command=self._give_dialog,
                      **theme.labelled("gift", t("pc_give"), "🎁", 14,
                                       theme.ON_GREEN)).pack(
            side="left", expand=True, fill="x", padx=(0, 4))
        ctk.CTkButton(btns, height=32,
                      font=(theme.FONT, 12), fg_color=theme.PANEL_2,
                      hover_color=theme.HOVER, text_color=theme.TEXT,
                      command=self._remove_sel,
                      **theme.labelled("close", t("pc_remove"), "✕", 13)
                      ).pack(side="left", expand=True, fill="x", padx=4)
        ctk.CTkButton(btns, height=32,
                      font=(theme.FONT, 12), fg_color="transparent",
                      border_width=1, border_color=theme.RED,
                      hover_color=theme.TINT_RED, text_color=theme.RED,
                      command=self._clear_all,
                      **theme.labelled("delete", t("pc_clear"), "🗑", 14,
                                       theme.RED)).pack(
            side="left", expand=True, fill="x", padx=(4, 0))

        self.status = ctk.CTkLabel(right, text="", font=(theme.FONT, 10),
                                   text_color=theme.MUTED, anchor="w",
                                   justify="left", wraplength=600)
        self.status.grid(row=3, column=0, sticky="w", padx=12, pady=(0, 8))

        self.refresh()
        self._load_head()
        self._load_textures()

    # ------------------------------------------------------------ données

    def _close(self):
        self._alive = False
        self.destroy()

    def refresh(self):
        """Recharge playerdata + position live si possible."""
        name, proc = self.name, self.proc
        online = pd.is_online(proc, name)
        self._loading = True

        def work():
            try:
                live, unreadable = None, False
                if online:              # le .dat d'un joueur connecté est
                    try:                # périmé (sauvegarde auto ~5 min)
                        live = pd.load_live(proc, name)
                    except pd.PlayerDataError:
                        unreadable = True
                data = live if live is not None else pd.load(self.dir, name)
                inf = pd.info(data)
                if unreadable:          # au moins la position exacte
                    pos = self._fetch_pos()
                    if pos:
                        inf.update(x=pos[0], y=pos[1], z=pos[2])
                ui_call(self, self._apply_data, data, inf, online,
                        online and live is None)
            except Exception as e:  # noqa: BLE001
                ui_call(self, self._err, str(e))
        threading.Thread(target=work, daemon=True).start()

    def _fetch_pos(self):
        """`data get entity <joueur> Pos` -> (x,y,z) live, ou None."""
        proc = self.proc
        if not (proc and proc.is_running() and proc.ready):
            return None
        ln = proc.ask(f"data get entity {self.name} Pos", _POS_ANSWER, 2.0)
        m = _POS_RE.search(ln) if ln and "entity data" in ln else None
        return tuple(float(g) for g in m.groups()) if m else None

    def _err(self, msg):
        self._loading = False
        if self._alive:
            self.status.configure(text=t("pc_error", e=msg),
                                  text_color=theme.RED)

    def _apply_data(self, data, inf, online, stale=False):
        self._loading = False
        if not self._alive:
            return
        self.data = data
        if stale and not self._note:    # connecté mais lecture en direct KO
            self._note = (t("pc_stale"), theme.ORANGE)
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
            for url, cb in ((MINOTAR, self._set_head),
                            (MINOTAR_BODY, self._set_body)):
                try:
                    r = requests.get(url.format(name), timeout=8)
                    if r.ok:
                        ui_call(self, cb, Image.open(io.BytesIO(r.content)))
                except Exception:  # noqa: BLE001
                    pass
        threading.Thread(target=work, daemon=True).start()

    def _set_head(self, img: Image.Image):
        if not self._alive:
            return
        self._head_ctk = ctk.CTkImage(img, size=(48, 48))
        self.head_lbl.configure(image=self._head_ctk, text="")

    def _set_body(self, img: Image.Image):
        if self._alive:
            self.inv_view.set_player(img)

    def _load_textures(self):
        """Textures officielles de la version du serveur (téléchargées une
        seule fois) ; en attendant : celles d'une autre version ou des
        pastilles."""
        version = str(self.proc.meta.get("mc_version", ""))
        cached = item_icons.best_cached(version)
        if cached:
            self.inv_view.set_textures(cached)
        if item_icons.available(version):
            return
        self._tex_status = t("inv_tex_dl")
        self.status.configure(text=self._tex_status)

        def work():
            try:
                ui_call(self, self._textures_ready, item_icons.ensure(version))
            except item_icons.TextureError as e:
                ui_call(self, self._textures_ready, None, str(e))
        threading.Thread(target=work, daemon=True).start()

    def _textures_ready(self, root, err=""):
        if not self._alive:
            return
        self._tex_status = ""
        if root:
            self.inv_view.set_textures(root)
            self._render_inv()
        else:
            self._say(t("inv_tex_err", e=err[:80]), theme.ORANGE)

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
                ui_call(self, self._map_failed, str(e))
        threading.Thread(target=work, daemon=True).start()

    def _map_failed(self, err: str):
        if self._alive:
            self._map_img = None
            self.map_lbl.configure(image=None, text=err[:120])

    def _show_map(self, img, n):
        if not self._alive:
            return
        self._map_img = ctk.CTkImage(img, size=(336, 336))
        self.map_lbl.configure(image=self._map_img, text="")
        self.map_info.configure(text=t("pc_chunks", n=n))

    # -------------------------------------------------------- inventaire

    def _ender(self) -> bool:
        return self.inv_seg.get() == t("pc_ender")

    def _say(self, text: str, color=None) -> None:
        self.status.configure(text=text, text_color=color or theme.MUTED)

    def _render_inv(self):
        ender = self._ender()
        items = pd.inventory(self.data)["ender" if ender else "inv"]
        sel = self._sel[0] if self._sel and self._sel[1] == ender else None
        self.inv_view.set(items, ender,
                          t("pc_ender") if ender else self.name, sel)
        if getattr(self, "_tex_status", "") or self._busy:
            return
        if self._note:                  # résultat de la dernière action
            self._say(*self._note)
            self._note = ""
            return
        on = pd.is_online(self.proc, self.name)
        self._say(t("pc_hint_online" if on else "pc_hint_offline")
                  + "  " + t("pc_hint_drag"))

    def _select_slot(self, slot):
        ender = self._ender()
        self._sel = None if self._sel == (slot, ender) else (slot, ender)
        self.focus_set()                # la touche Suppr arrive à la fenêtre
        self._render_inv()

    def _slot_menu(self, slot, x, y):
        """Clic droit sur une case : sélection + menu « Retirer »."""
        ender = self._ender()
        if slot not in pd.inventory(self.data)["ender" if ender else "inv"]:
            return
        self._sel = (slot, ender)
        self._render_inv()
        menu = tk.Menu(self, tearoff=0, bg=theme.c(theme.PANEL_2),
                       fg=theme.c(theme.TEXT),
                       activebackground=theme.c(theme.ACCENT),
                       activeforeground="#ffffff")
        menu.add_command(label="✕ " + t("pc_remove"),
                         command=self._remove_sel)
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _export(self):
        from tkinter import filedialog
        ender = self._ender()
        path = filedialog.asksaveasfilename(
            parent=self, defaultextension=".png",
            filetypes=[("PNG", "*.png")],
            initialfile=f"{self.name}-{'ender' if ender else 'inventory'}.png")
        if not path:
            return
        self.inv_view.image(4).save(path)
        self._say(t("inv_exported", path=Path(path).name), theme.GREEN)

    # ---------------------------------------------------------- actions

    def _ready(self) -> bool:
        """False (avec un message) tant qu'une lecture ou un envoi est en
        cours : on ne modifie pas un inventaire qu'on n'a pas encore lu."""
        if self._busy or self._loading:
            self._say(t("pc_wait"), theme.ORANGE)
            return False
        return True

    def _run_online(self, commands: list, done_text: str,
                    strict: bool = True) -> None:
        """Envoie les commandes une par une et lit la réponse du serveur à
        chacune : la modification n'est annoncée comme faite que si le
        serveur l'a confirmée. `strict=False` : un refus isolé (case déjà
        vide) n'interrompt pas la série."""
        proc = self.proc
        self._busy = True
        self._say(t("pc_working"), theme.ORANGE)

        def work():                   # thread : aucun appel Tk
            note = (done_text, theme.GREEN)
            for cmd in commands:
                answer = proc.ask(cmd, _ANSWER)
                if answer is None:
                    note = (t("pc_no_answer"), theme.ORANGE)
                    break
                gone = re.search(r"No (entity|player) was found", answer)
                if _REFUSED.search(answer) and (strict or gone):
                    note = (t("pc_refused",
                              msg=_LOG_PREFIX.sub("", answer)[:160]),
                            theme.RED)
                    break
            ui_call(self, self._action_done, note)
        threading.Thread(target=work, daemon=True).start()

    def _action_done(self, note) -> None:
        self._busy = False
        if not self._alive:
            return
        self._note = note
        self._sel = None
        self._say(*note)
        self.refresh()                # relit l'inventaire réel du serveur

    def _edit_offline(self, edit, done_text: str) -> None:
        """Applique `edit(data)` au .dat relu à l'instant (jamais aux données
        lues en direct, qui ne sont pas le fichier) puis l'enregistre.
        `edit` retourne False pour annuler, ou un message d'erreur."""
        try:
            data = pd.load(self.dir, self.name)
            if data is None:
                self._say(t("pc_never"), theme.ORANGE)
                return
            res = edit(data)
            if res is False or isinstance(res, str):
                self._say(res or t("pc_empty_slot"), theme.ORANGE)
                return
            pd.save(self.dir, self.name, data)
        except (pd.PlayerDataError, OSError) as e:
            self._say(t("pc_error", e=e), theme.RED)
            return
        self._note = (f"{done_text}  {t('pc_saved')}", theme.GREEN)
        self._sel = None
        self.refresh()

    def _remove_sel(self):
        if not self._sel:
            self._say(t("pc_select_first"), theme.ORANGE)
            return
        if not self._ready():
            return
        slot, ender = self._sel
        if slot not in pd.inventory(self.data)["ender" if ender else "inv"]:
            self._say(t("pc_empty_slot"), theme.ORANGE)
            return
        if pd.is_online(self.proc, self.name):
            self._run_online(
                [pd.remove_command(self.name, slot, ender,
                                   self.proc.meta.get("mc_version"))],
                t("pc_removed"))
        else:
            self._edit_offline(
                lambda data: pd.remove_item(data, slot, ender),
                t("pc_removed"))

    def _move(self, src: int, dst: int):
        """Glisser-déposer : déplace l'objet, ou échange si la case d'arrivée
        est occupée."""
        if not self._ready():
            return
        ender = self._ender()
        inv = pd.inventory(self.data)
        if src not in inv["ender" if ender else "inv"]:
            return
        if pd.is_online(self.proc, self.name):
            try:
                cmds = pd.move_commands(
                    self.name, src, dst, ender, inv["inv"], inv["ender"],
                    self.proc.meta.get("mc_version"))
            except pd.PlayerDataError as e:
                self._say(str(e), theme.ORANGE)
                return
            self._run_online(cmds, t("pc_moved"))
        else:
            self._edit_offline(
                lambda data: pd.move_item(data, src, dst, ender),
                t("pc_moved"))

    def _clear_all(self):
        """« Tout supprimer » : rien n'est touché sans un « Oui » explicite
        (« Non » est le choix par défaut, fermer la fenêtre annule)."""
        from tkinter import messagebox
        if not self._ready():
            return
        ender = self._ender()
        if not messagebox.askyesno(
                t("pc_clear"),
                t("pc_clear_confirm_ender" if ender else "pc_clear_confirm",
                  name=self.name),
                icon="warning", default="no", parent=self):
            return
        if pd.is_online(self.proc, self.name):
            self._run_online(
                pd.clear_commands(self.name, ender,
                                  self.proc.meta.get("mc_version")),
                t("pc_cleared"), strict=False)
        else:
            self._edit_offline(
                lambda data: pd.clear_inventory(data, ender),
                t("pc_cleared"))

    def _give_dialog(self):
        if not self._ready():
            return
        dlg = _GiveDialog(self)
        self.wait_window(dlg)
        if not dlg.result or not self._alive:
            return
        item, count = dlg.result
        done = t("pc_given", item=pd.pretty_name(item), n=count)
        if pd.is_online(self.proc, self.name):
            self._run_online(
                [f"give {self.name} minecraft:{item} {count}"], done)
            return
        if pd.load(self.dir, self.name) is None:   # jamais connecté
            import nbtlib
            pd.save(self.dir, self.name, nbtlib.File(nbtlib.Compound(
                {"Inventory": nbtlib.List[nbtlib.Compound]()})))
        self._edit_offline(
            lambda data: (t("pc_full")
                          if pd.give_item(data, item, count) < 0 else None),
            done)


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
