"""Inventaire dessiné comme l'écran du jeu (PIL -> tk.Canvas).

Coordonnées en « pixels GUI » Minecraft (écran d'inventaire 176×166),
multipliées par une échelle entière pour rester net. Survol = infobulle
façon jeu, clic = sélection du slot (callback `on_select`).
"""
import colorsys
import tkinter as tk

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageTk

from ..core import item_icons
from ..core import playerdata as pd
from ..i18n import t
from . import theme

_BG = (198, 198, 198)
_SLOT = (139, 139, 139)
_DARK = (55, 55, 55)
_LIGHT = (255, 255, 255)
_TITLE = (64, 64, 64)
_GLINT = (140, 70, 230)
_GLINT_ITEMS = {"minecraft:enchanted_golden_apple", "minecraft:nether_star",
                "minecraft:experience_bottle", "minecraft:enchanted_book",
                "minecraft:end_crystal", "minecraft:debug_stick"}

# slot -> (x, y) du coin haut-gauche de l'item (16×16) dans l'écran
INV_W, INV_H = 176, 166
INV_SLOTS = {103: (8, 8), 102: (8, 26), 101: (8, 44), 100: (8, 62),
             pd.SLOT_OFFHAND: (77, 62)}
INV_SLOTS.update({9 + r * 9 + c: (8 + c * 18, 84 + r * 18)
                  for r in range(3) for c in range(9)})
INV_SLOTS.update({c: (8 + c * 18, 142) for c in range(9)})
PLAYER_BOX = (26, 8, 75, 78)
ENDER_W, ENDER_H = 176, 80
ENDER_SLOTS = {r * 9 + c: (8 + c * 18, 18 + r * 18)
               for r in range(3) for c in range(9)}

_ROMAN = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]


def enchant_label(ench_id: str, lvl: int) -> str:
    name = ench_id.split(":", 1)[-1].replace("_", " ").title()
    if lvl == 1 and ench_id.endswith(("mending", "silk_touch", "infinity",
                                      "channeling", "multishot",
                                      "aqua_affinity", "flame",
                                      "binding_curse", "vanishing_curse")):
        return name
    return f"{name} {_ROMAN[lvl] if 0 < lvl < len(_ROMAN) else lvl}"


def item_title(entry: dict) -> str:
    return entry.get("name") or pd.pretty_name(entry["id"])


def _glint(icon: Image.Image) -> Image.Image:
    over = Image.new("RGBA", icon.size, _GLINT + (0,))
    alpha = icon.getchannel("A").point(lambda a: a * 90 // 255)
    over.putalpha(alpha)
    out = icon.copy()
    out.alpha_composite(over)
    return out


def _panel(w: int, h: int, k: int) -> Image.Image:
    img = Image.new("RGBA", (w * k, h * k), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    dr.rounded_rectangle((0, 0, w * k - 1, h * k - 1), radius=3 * k,
                         fill=_BG, outline=(0, 0, 0), width=k)
    dr.line((k * 2, k * 2, w * k - 3 * k, k * 2), fill=_LIGHT, width=2 * k)
    dr.line((k * 2, k * 2, k * 2, h * k - 3 * k), fill=_LIGHT, width=2 * k)
    dr.line((k * 3, h * k - 3 * k, w * k - 3 * k, h * k - 3 * k),
            fill=(85, 85, 85), width=2 * k)
    dr.line((w * k - 3 * k, k * 3, w * k - 3 * k, h * k - 3 * k),
            fill=(85, 85, 85), width=2 * k)
    return img


def _slot(dr: ImageDraw.ImageDraw, x: int, y: int, k: int) -> None:
    x0, y0 = (x - 1) * k, (y - 1) * k
    dr.rectangle((x0, y0, x0 + 18 * k - 1, y0 + 18 * k - 1), fill=_SLOT)
    dr.rectangle((x0, y0, x0 + 17 * k - 1, y0 + k - 1), fill=_DARK)
    dr.rectangle((x0, y0, x0 + k - 1, y0 + 17 * k - 1), fill=_DARK)
    dr.rectangle((x0 + k, y0 + 17 * k, x0 + 18 * k - 1, y0 + 18 * k - 1),
                 fill=_LIGHT)
    dr.rectangle((x0 + 17 * k, y0 + k, x0 + 18 * k - 1, y0 + 18 * k - 1),
                 fill=_LIGHT)


def render(items: dict, ender: bool, k: int, icons: item_icons.Icons,
           title: str = "", player_img: Image.Image | None = None,
           selected=None) -> Image.Image:
    """Image de l'inventaire (ou de l'ender chest) à l'échelle `k`."""
    w, h, slots = ((ENDER_W, ENDER_H, ENDER_SLOTS) if ender
                   else (INV_W, INV_H, INV_SLOTS))
    img = _panel(w, h, k)
    dr = ImageDraw.Draw(img)
    font = item_icons.font_for(max(8, int(7.5 * k)))
    if title:
        pos = (8 * k, 6 * k) if ender else (82 * k, 8 * k)
        dr.text(pos, title, font=font, fill=_TITLE)
    if not ender:
        x0, y0, x1, y1 = PLAYER_BOX
        dr.rectangle((x0 * k, y0 * k, x1 * k - 1, y1 * k - 1), fill=(0, 0, 0))
        dr.rectangle((x0 * k, y0 * k, x1 * k - 1, y0 * k + k - 1),
                     fill=_DARK)
        if player_img is not None:
            bw, bh = (x1 - x0 - 6) * k, (y1 - y0 - 6) * k
            p = player_img.convert("RGBA")
            ratio = min(bw / p.width, bh / p.height)
            p = p.resize((max(1, int(p.width * ratio)),
                          max(1, int(p.height * ratio))), Image.NEAREST)
            img.alpha_composite(p, ((x0 * k + (x1 - x0) * k // 2
                                     - p.width // 2),
                                    y1 * k - 3 * k - p.height))
    for s, (x, y) in slots.items():
        _slot(dr, x, y, k)
    for s, (x, y) in slots.items():
        it = items.get(s)
        if not it:
            continue
        icon = icons.get(it["id"])
        if it.get("enchants") or it["id"] in _GLINT_ITEMS:
            icon = _glint(icon)
        img.alpha_composite(icon, (x * k, y * k))
        dmg, mx = it.get("damage", 0), it.get("max_damage", 0)
        if dmg > 0 and mx > 0:
            frac = max(0.0, 1 - dmg / mx)
            r, g, b = colorsys.hsv_to_rgb(frac / 3, 1, 1)
            bx, by = (x + 2) * k, (y + 13) * k
            dr.rectangle((bx, by, bx + 13 * k - 1, by + 2 * k - 1),
                         fill=(0, 0, 0))
            dr.rectangle((bx, by, bx + max(1, round(13 * frac)) * k - 1,
                          by + k - 1),
                         fill=(int(r * 255), int(g * 255), int(b * 255)))
        if it["count"] > 1:
            tx, ty = (x + 17) * k, (y + 17) * k
            dr.text((tx + k, ty + k), str(it["count"]), font=font,
                    fill=(63, 63, 63), anchor="rd")
            dr.text((tx, ty), str(it["count"]), font=font,
                    fill=(255, 255, 255), anchor="rd")
    if selected in slots:
        x, y = slots[selected]
        over = Image.new("RGBA", (16 * k, 16 * k), (255, 255, 255, 110))
        img.alpha_composite(over, (x * k, y * k))
        c = theme.c(theme.ACCENT)
        dr.rectangle(((x - 1) * k, (y - 1) * k, (x + 17) * k - 1,
                      (y + 17) * k - 1), outline=c, width=k)
    return img


class InventoryView(tk.Canvas):
    """Canvas qui affiche `render()` et gère survol / clic."""

    def __init__(self, master, on_select=None):
        super().__init__(master, highlightthickness=0, bd=0,
                         bg=theme.c(theme.PANEL_2))
        self.on_select = on_select
        self.items: dict = {}
        self.ender = False
        self.title = ""
        self.player_img = None
        self.selected = None
        self.icons_root = None
        self._icons: dict = {}
        self._k = 2
        self._origin = (0, 0)
        self._photo = None
        self._hover = None
        self.bind("<Configure>", lambda _e: self.redraw())
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda _e: self._tooltip(None))
        self.bind("<Button-1>", self._click)

    # ------------------------------------------------------------ données
    def set(self, items: dict, ender: bool, title: str = "",
            selected=None) -> None:
        self.items, self.ender, self.title = items, ender, title
        self.selected = selected
        self.redraw()

    def set_player(self, img) -> None:
        self.player_img = img
        self.redraw()

    def set_textures(self, root) -> None:
        self.icons_root = root
        self._icons.clear()
        self.redraw()

    def icons(self, k: int) -> item_icons.Icons:
        if k not in self._icons:
            self._icons[k] = item_icons.Icons(self.icons_root, 16 * k)
        return self._icons[k]

    def image(self, k: int = 4) -> Image.Image:
        return render(self.items, self.ender, k, self.icons(k), self.title,
                      self.player_img)

    # ------------------------------------------------------------ dessin
    def _size(self):
        return (ENDER_W, ENDER_H) if self.ender else (INV_W, INV_H)

    def redraw(self) -> None:
        self.configure(bg=theme.c(theme.PANEL_2))
        cw, ch = self.winfo_width(), self.winfo_height()
        if cw < 20 or ch < 20:
            return
        w, h = self._size()
        self._k = max(1, min(4, int(min((cw - 8) / w, (ch - 8) / h))))
        img = render(self.items, self.ender, self._k, self.icons(self._k),
                     self.title, self.player_img, self.selected)
        self._photo = ImageTk.PhotoImage(img)
        self.delete("all")
        ox, oy = (cw - img.width) // 2, (ch - img.height) // 2
        self._origin = (ox, oy)
        self.create_image(ox, oy, image=self._photo, anchor="nw")
        self._hover = None

    def _slot_at(self, ex, ey):
        k = self._k
        gx, gy = (ex - self._origin[0]) / k, (ey - self._origin[1]) / k
        slots = ENDER_SLOTS if self.ender else INV_SLOTS
        for s, (x, y) in slots.items():
            if x - 1 <= gx < x + 17 and y - 1 <= gy < y + 17:
                return s
        return None

    def _click(self, e):
        s = self._slot_at(e.x, e.y)
        if s is not None and self.on_select:
            self.on_select(s)

    def _motion(self, e):
        s = self._slot_at(e.x, e.y)
        it = self.items.get(s) if s is not None else None
        self._tooltip(it, e.x, e.y)

    def _tooltip(self, it, x=0, y=0):
        self.delete("tip")
        if not it:
            return
        lines = [(item_title(it) + (f"  ×{it['count']}"
                                    if it["count"] > 1 else ""),
                  "#55ffff" if it.get("enchants") else "#ffffff")]
        lines += [(enchant_label(e, lv), "#aaaaaa")
                  for e, lv in it.get("enchants", [])]
        if it.get("max_damage") and it.get("damage"):
            left = it["max_damage"] - it["damage"]
            lines.append((t("inv_durability", n=left, max=it["max_damage"]),
                          "#aaaaaa"))
        lines.append((it["id"], "#555555"))
        font = (theme.FONT, 10)
        tx, ty = x + 14, y - 8
        ids = []
        for i, (txt, col) in enumerate(lines):
            ids.append(self.create_text(tx + 6, ty + 5 + i * 17, text=txt,
                                        fill=col, anchor="nw", font=font,
                                        tags="tip"))
        x0, y0, x1, y1 = self.bbox(*ids)
        cw, ch = self.winfo_width(), self.winfo_height()
        dx = -(x1 - x0 + 40) if x1 + 10 > cw else 0      # bascule à gauche
        dy = min(0, ch - 8 - y1) + max(0, 8 - y0)
        bg = self.create_rectangle(x0 - 6, y0 - 5, x1 + 6, y1 + 5,
                                   fill="#100010", outline="#2a0e61",
                                   width=2, tags="tip")
        self.tag_lower(bg, ids[0])
        self.move("tip", dx, dy)
