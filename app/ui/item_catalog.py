"""Catalogue d'objets façon inventaire créatif : tous les objets du jeu et
des mods du serveur, avec leurs textures, à donner d'un double-clic.

La grille est dessinée sur un tk.Canvas et seules les lignes visibles sont
rendues : plusieurs milliers d'objets restent fluides.
"""
import re
import tkinter as tk

import customtkinter as ctk
from PIL import ImageTk

from ..core import item_icons
from ..core import playerdata as pd
from ..i18n import t
from . import theme

# Sans textures (hors ligne, premier lancement) : objets courants seulement.
FALLBACK_ITEMS = (
    "diamond", "diamond_sword", "diamond_pickaxe", "diamond_axe",
    "netherite_sword", "netherite_pickaxe", "iron_sword", "iron_pickaxe",
    "golden_apple", "enchanted_golden_apple", "bow", "arrow", "shield",
    "totem_of_undying", "elytra", "firework_rocket", "ender_pearl",
    "torch", "bread", "cooked_beef", "oak_log", "oak_planks", "stone",
    "cobblestone", "glass", "dirt", "chest", "crafting_table", "furnace",
    "tnt", "water_bucket", "lava_bucket", "obsidian", "beacon",
    "experience_bottle", "name_tag", "saddle",
)
QUANTITIES = ("1", "16", "64")
_RAW_ID = re.compile(r"^[a-z0-9_.-]+(:[a-z0-9_./-]+)?$")


class ItemCatalog(ctk.CTkToplevel):
    """Fenêtre non modale liée à une fiche joueur (`card`) : elle reste
    ouverte pour donner plusieurs objets à la suite."""

    def __init__(self, card):
        super().__init__(card)
        self.card = card
        self._all: list = []          # [(id, nom, texte de recherche)]
        self._shown: list = []        # filtré
        self._icons = None
        self._photos: dict = {}
        self._sel = None              # id sélectionné
        self._hover = None            # index survolé
        self._cols = 1
        scale = self._get_window_scaling()
        self._icon = 48 if scale >= 1.5 else 32
        self._cell = self._icon + 12

        self.title(t("cat_title", name=card.name))
        self.geometry("760x560")
        self.minsize(520, 380)
        self.configure(fg_color=theme.BG)
        self.transient(card)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        self.q = ctk.CTkEntry(bar, placeholder_text=t("cat_search"),
                              fg_color=theme.PANEL_2,
                              border_color=theme.BORDER,
                              text_color=theme.TEXT, height=32)
        self.q.pack(side="left", fill="x", expand=True)
        self.q.bind("<KeyRelease>", lambda _e: self._filter())
        self.q.bind("<Return>", lambda _e: self._give())
        self.source = ctk.CTkOptionMenu(
            bar, values=[t("cat_all")], width=150, height=32,
            fg_color=theme.PANEL_2, button_color=theme.PANEL_2,
            button_hover_color=theme.HOVER, text_color=theme.TEXT,
            command=lambda _v: self._filter())
        self.source.pack(side="left", padx=8)
        ctk.CTkLabel(bar, text=t("cat_qty"), font=(theme.FONT, 11),
                     text_color=theme.MUTED).pack(side="left", padx=(4, 6))
        self.qty = ctk.CTkSegmentedButton(bar, values=list(QUANTITIES),
                                          font=(theme.FONT, 11), **theme.SEG)
        self.qty.set("1")
        self.qty.pack(side="left")

        box = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=10)
        box.grid(row=1, column=0, sticky="nsew", padx=12, pady=4)
        box.grid_columnconfigure(0, weight=1)
        box.grid_rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(box, highlightthickness=0, bd=0,
                                bg=theme.c(theme.PANEL),
                                yscrollincrement=self._cell)
        self.canvas.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        self.bar = ctk.CTkScrollbar(box, command=self._yview)
        self.bar.grid(row=0, column=1, sticky="ns", padx=(2, 4), pady=8)
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.canvas.bind("<Configure>", lambda _e: self._draw())
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Motion>", self._motion)
        self.canvas.bind("<Leave>", lambda _e: self._set_hover(None))
        self.canvas.bind("<Button-1>", self._click)
        self.canvas.bind("<Double-Button-1>", lambda _e: self._give())

        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.grid(row=2, column=0, sticky="ew", padx=12, pady=(4, 12))
        foot.grid_columnconfigure(0, weight=1)
        self.info = ctk.CTkLabel(foot, text=t("cat_loading"), anchor="w",
                                 font=(theme.FONT, 12, "bold"),
                                 text_color=theme.TEXT)
        self.info.grid(row=0, column=0, sticky="ew")
        self.sub = ctk.CTkLabel(foot, text="", anchor="w",
                                font=(theme.FONT, 10),
                                text_color=theme.MUTED)
        self.sub.grid(row=1, column=0, sticky="ew")
        self.give_btn = ctk.CTkButton(
            foot, height=36, width=150, font=(theme.FONT, 12, "bold"),
            fg_color=theme.GREEN, hover_color=theme.GREEN_HOVER,
            text_color=theme.ON_GREEN, command=self._give,
            **theme.labelled("gift", t("cat_give"), "🎁", 14, theme.ON_GREEN))
        self.give_btn.grid(row=0, column=1, rowspan=2, padx=(10, 0))

        self.q.focus()
        self._wait()

    # ------------------------------------------------------------ données
    def _wait(self):
        """Les textures et les mods sont chargés par la fiche joueur (thread)
        : on attend qu'ils soient prêts."""
        if not self.winfo_exists():
            return
        tex = self.card.textures
        if tex is None:
            self.after(200, self._wait)
            return
        root, mods, names = tex
        self._icons = item_icons.Icons(root, self._icon, extra=mods)
        if names:
            entries = list(names.items())
        else:
            entries = [(f"minecraft:{i}", pd.pretty_name(i))
                       for i in FALLBACK_ITEMS]
        self._all = [(i, name, f"{name} {i}".lower()) for i, name in entries]
        spaces = sorted({i.split(":", 1)[0] for i, _n, _h in self._all}
                        - {"minecraft"})
        self.source.configure(values=[t("cat_all"), "Minecraft", *spaces])
        self._filter()

    def _filter(self):
        words = self.q.get().strip().lower().split()
        src = self.source.get()
        ns = "" if src == t("cat_all") else src.lower() + ":"
        self._shown = [e for e in self._all
                       if e[0].startswith(ns)
                       and all(w in e[2] for w in words)]
        if self._sel not in {e[0] for e in self._shown}:
            self._sel = None
        self.canvas.yview_moveto(0)
        self._hover = None
        self._draw()
        self._describe()

    # ------------------------------------------------------------- dessin
    def _yview(self, *args):
        self.canvas.yview(*args)
        self._draw()

    def _wheel(self, e):
        self.canvas.yview_scroll(-2 if e.delta > 0 else 2, "units")
        self._draw()

    def _photo(self, item_id):
        if item_id not in self._photos:
            self._photos[item_id] = ImageTk.PhotoImage(
                self._icons.get(item_id))
        return self._photos[item_id]

    def _draw(self):
        c, cell = self.canvas, self._cell
        c.configure(bg=theme.c(theme.PANEL))
        w, h = c.winfo_width(), c.winfo_height()
        if w < cell or self._icons is None:
            return
        self._cols = cols = max(1, w // cell)
        rows = -(-len(self._shown) // cols)
        c.configure(scrollregion=(0, 0, w, max(rows * cell, h)))
        top = c.canvasy(0)
        first = int(top // cell)
        last = int((top + h) // cell) + 1
        c.delete("all")
        slot, sel = theme.c(theme.PANEL_2), theme.c(theme.SEL)
        for idx in range(first * cols, min(len(self._shown), last * cols)):
            item_id = self._shown[idx][0]
            x, y = (idx % cols) * cell, (idx // cols) * cell
            c.create_rectangle(x + 2, y + 2, x + cell - 2, y + cell - 2,
                               fill=sel if item_id == self._sel else slot,
                               outline="")
            c.create_image(x + cell // 2, y + cell // 2,
                           image=self._photo(item_id))
        self._outline()

    def _outline(self):
        self.canvas.delete("hover")
        if self._hover is None or self._hover >= len(self._shown):
            return
        cell = self._cell
        x, y = (self._hover % self._cols) * cell, \
            (self._hover // self._cols) * cell
        self.canvas.create_rectangle(
            x + 2, y + 2, x + cell - 2, y + cell - 2, tags="hover",
            outline=theme.c(theme.ACCENT), width=2)

    # -------------------------------------------------------- interaction
    def _index_at(self, e):
        col = int(self.canvas.canvasx(e.x) // self._cell)
        row = int(self.canvas.canvasy(e.y) // self._cell)
        idx = row * self._cols + col
        return idx if 0 <= col < self._cols and \
            0 <= idx < len(self._shown) else None

    def _motion(self, e):
        self._set_hover(self._index_at(e))

    def _set_hover(self, idx):
        if idx != self._hover:
            self._hover = idx
            self._outline()
            self._describe()

    def _click(self, e):
        idx = self._index_at(e)
        if idx is not None:
            self._sel = self._shown[idx][0]
            self._draw()
            self._describe()

    def _target(self):
        """(id, nom) de l'objet que « Donner » enverrait : la sélection,
        sinon l'identifiant tapé à la main s'il ne correspond à rien."""
        if self._sel:
            name = next((n for i, n, _h in self._all if i == self._sel),
                        self._sel)
            return self._sel, name
        raw = self.q.get().strip().lower().replace(" ", "_")
        if raw and not self._shown and _RAW_ID.match(raw):
            item_id = raw if ":" in raw else f"minecraft:{raw}"
            return item_id, item_id
        return None, ""

    def _describe(self, note: str = "", color=None):
        """Nom et identifiant de l'objet survolé (sinon sélectionné)."""
        if self._icons is None:
            return
        if self._hover is not None and self._hover < len(self._shown):
            item_id, name = self._shown[self._hover][:2]
        else:
            item_id, name = self._target()
        if item_id:
            self.info.configure(text=name)
            self.sub.configure(text=note or item_id,
                               text_color=color or theme.MUTED)
        else:
            self.info.configure(text=t("cat_none") if not self._shown
                                else t("cat_count", n=len(self._shown)))
            self.sub.configure(text=note or t("cat_hint"),
                               text_color=color or theme.MUTED)

    def _give(self):
        if self._hover is not None and self._hover < len(self._shown):
            self._sel = self._shown[self._hover][0]     # double-clic
            self._draw()
        item_id, name = self._target()
        if not item_id:
            self._describe(t("pc_select_item"), theme.ORANGE)
            return
        count = int(self.qty.get() or 1)
        if self.card.give(item_id, count, name):
            self._describe(t("pc_given", item=name, n=count), theme.GREEN)
        else:
            self._describe(t("pc_wait"), theme.ORANGE)
