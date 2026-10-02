"""Palette et styles.

Chaque couleur est un tuple (clair, sombre) : CustomTkinter choisit la bonne
selon le mode et **rebascule en direct** quand on change de thème.
Pour les widgets Tk natifs (Menu, tags de Textbox) qui n'acceptent qu'une
chaîne, utiliser `c(couleur)`.
"""
import os
from pathlib import Path

import customtkinter as ctk

BG = ("#eef1f6", "#0b0e13")
PANEL = ("#ffffff", "#131820")
PANEL_2 = ("#e9edf4", "#1a212c")
HOVER = ("#dbe2ee", "#242e3d")
BORDER = ("#d3dbe7", "#263041")
ACCENT = ("#2563eb", "#3b82f6")
ACCENT_HOVER = ("#1d4ed8", "#2563eb")
SEL = ("#bfdbfe", "#1e40af")          # sélection (boutons segmentés)
SEL_HOVER = ("#93c5fd", "#1d4ed8")
GREEN = ("#16a34a", "#22c55e")
GREEN_HOVER = ("#15803d", "#16a34a")
RED = ("#dc2626", "#ef4444")
RED_HOVER = ("#b91c1c", "#dc2626")
ORANGE = ("#d97706", "#f59e0b")
ORANGE_HOVER = ("#b45309", "#d97706")
PURPLE = ("#7c3aed", "#a78bfa")
TEXT = ("#111827", "#e6e9ef")
MUTED = ("#64748b", "#8b94a7")
CONSOLE_BG = ("#f7f9fc", "#080a0e")
CONSOLE_TEXT = ("#1f2937", "#c9d1d9")
DISABLED = ("#cbd5e1", "#2a3240")
DISABLED_TEXT = ("#94a3b8", "#5b6576")
ON_ACCENT = "#ffffff"
ON_GREEN = ("#ffffff", "#052e16")
# fonds teintés des notifications (toasts)
TINT_GREEN = ("#dcfce7", "#12301f")
TINT_RED = ("#fee2e2", "#3a1618")
TINT_ORANGE = ("#fef3c7", "#3a2a0d")
TINT_BLUE = ("#dbeafe", "#14243f")

FONT = "Segoe UI"
FONT_MONO = "Consolas"

# espacements et rayons communs (px)
RADIUS = 12            # cartes
RADIUS_SM = 8          # champs, boutons, lignes de liste
PAD = 12

# Couleur d'accent au choix (⚙ Paramètres) : (accent, survol, sélection,
# survol de la sélection), chacun en (clair, sombre).
ACCENTS = {
    "blue": (("#2563eb", "#3b82f6"), ("#1d4ed8", "#2563eb"),
             ("#bfdbfe", "#1e40af"), ("#93c5fd", "#1d4ed8")),
    "emerald": (("#059669", "#10b981"), ("#047857", "#059669"),
                ("#a7f3d0", "#065f46"), ("#6ee7b7", "#047857")),
    "violet": (("#7c3aed", "#8b5cf6"), ("#6d28d9", "#7c3aed"),
               ("#ddd6fe", "#5b21b6"), ("#c4b5fd", "#6d28d9")),
    "orange": (("#ea580c", "#f97316"), ("#c2410c", "#ea580c"),
               ("#fed7aa", "#9a3412"), ("#fdba74", "#c2410c")),
    "pink": (("#db2777", "#ec4899"), ("#be185d", "#db2777"),
             ("#fbcfe8", "#9d174d"), ("#f9a8d4", "#be185d")),
}

# Couleur propre à chaque type de serveur (pastilles, cartes, créateur)
LOADER_COLORS = {
    "paper": ("#2563eb", "#60a5fa"), "purpur": ("#7c3aed", "#c084fc"),
    "fabric": ("#a16207", "#e3c08d"), "forge": ("#c2410c", "#fb923c"),
    "neoforge": ("#b45309", "#fbbf24"), "mohist": ("#0f766e", "#2dd4bf"),
}


def _seg() -> dict:
    # Boutons segmentés : même fond que les champs, sélection à la couleur
    # d'accent — sans le cadre gris par défaut. À passer en **theme.SEG.
    return dict(fg_color=PANEL_2, selected_color=SEL,
                selected_hover_color=SEL_HOVER, unselected_color=PANEL_2,
                unselected_hover_color=HOVER, text_color=TEXT,
                corner_radius=RADIUS_SM)


SEG = _seg()


def set_accent(name: str) -> None:
    """Change la couleur d'accent. À appeler avant de créer l'interface :
    les widgets lisent les couleurs à leur création."""
    global ACCENT, ACCENT_HOVER, SEL, SEL_HOVER, SEG
    ACCENT, ACCENT_HOVER, SEL, SEL_HOVER = ACCENTS.get(name, ACCENTS["blue"])
    SEG = _seg()


def is_dark() -> bool:
    return ctk.get_appearance_mode() == "Dark"


def c(color) -> str:
    """Résout un tuple (clair, sombre) pour les widgets Tk natifs."""
    if isinstance(color, (tuple, list)):
        return color[1] if is_dark() else color[0]
    return color


def apply(mode: str) -> None:
    ctk.set_appearance_mode("light" if mode == "light" else "dark")


# ------------------------------------------------------------------ icônes

# Glyphes de « Segoe MDL2 Assets », police d'icônes livrée avec Windows 10
# et 11 : traits nets et homogènes, là où les émojis sortent en petit et en
# monochrome dans Tk. Aucune dépendance ni fichier embarqué ; si la police
# est absente (autre système), `icon()` renvoie None et les boutons gardent
# leur émoji.
ICONS = {
    "play": 0xF5B0, "stop": 0xE71A, "restart": 0xE72C, "settings": 0xE713,
    "folder": 0xED25, "delete": 0xE74D, "add": 0xE710, "puzzle": 0xEA86,
    "history": 0xE81C, "copy": 0xE8C8, "globe": 0xE774, "search": 0xE721,
    "save": 0xE74E, "camera": 0xE722, "people": 0xE716, "shield": 0xE83D,
    "sun": 0xE706, "moon": 0xE708, "send": 0xE724, "download": 0xE896,
    "close": 0xE711, "check": 0xE73E, "warning": 0xE7BA, "info": 0xE946,
    "more": 0xE712, "map": 0xE707, "package": 0xE7B8, "console": 0xE756,
    "filter": 0xE71C, "link": 0xE71B, "star": 0xE734, "gift": 0xF133,
    "error": 0xEA39, "open": 0xE8A7, "block": 0xE8F8, "robot": 0xE99A,
    "list": 0xEA37, "clipboard": 0xE77F, "contact": 0xE77B,
    "broom": 0xEA99, "clock": 0xE823, "keyboard": 0xE765,
    "checklist": 0xE930, "help": 0xE9CE,
}
_ICON_FONT_FILE = "segmdl2.ttf"
_icon_fonts: dict = {}
_icon_cache: dict = {}


def _icon_font(px: int):
    if px not in _icon_fonts:
        try:
            from PIL import ImageFont
            path = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" \
                / _ICON_FONT_FILE
            _icon_fonts[px] = ImageFont.truetype(str(path), px)
        except (OSError, ImportError):
            _icon_fonts[px] = None
    return _icon_fonts[px]


def _glyph(name: str, px: int, color: str):
    from PIL import Image, ImageDraw
    font = _icon_font(px)
    if font is None or name not in ICONS:
        return None
    img = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((px / 2, px / 2), chr(ICONS[name]), font=font,
                             fill=color, anchor="mm")
    return img


def icon(name: str, size: int = 16, color=TEXT):
    """CTkImage de l'icône (couleur claire/sombre suivie en direct), ou
    None si la police d'icônes n'est pas disponible."""
    light, dark = (color if isinstance(color, (tuple, list))
                   else (color, color))
    key = (name, size, light, dark)
    if key not in _icon_cache:
        px = size * 3                 # sur-échantillonné : net en 150-200 %
        a, b = _glyph(name, px, light), _glyph(name, px, dark)
        _icon_cache[key] = (ctk.CTkImage(light_image=a, dark_image=b,
                                         size=(size, size))
                            if a is not None and b is not None else None)
    return _icon_cache[key]


def labelled(name: str, text: str = "", emoji: str = "", size: int = 16,
             color=TEXT) -> dict:
    """Arguments `text` / `image` d'un bouton ou label avec icône ; repli
    sur l'émoji d'origine si la police d'icônes est absente."""
    img = icon(name, size, color)
    if img is None:
        return {"text": f"{emoji}  {text}".strip() if emoji else text}
    return {"text": text, "image": img, "compound": "left"}


def action_button(btn, enabled: bool, color, hover, text_color=ON_ACCENT,
                  icon_name: str | None = None):
    """Bouton coloré quand actif, grisé (et visiblement inactif) sinon.
    `icon_name` : l'icône suit la couleur du texte dans les deux états."""
    if enabled:
        btn.configure(state="normal", fg_color=color, hover_color=hover,
                      text_color=text_color)
    else:
        btn.configure(state="disabled", fg_color=DISABLED,
                      text_color_disabled=DISABLED_TEXT)
    if icon_name:
        img = icon(icon_name, 14, text_color if enabled else DISABLED_TEXT)
        if img is not None:
            btn.configure(image=img)


def card(parent, **kw):
    kw.setdefault("fg_color", PANEL)
    kw.setdefault("corner_radius", RADIUS)
    kw.setdefault("border_width", 1)
    kw.setdefault("border_color", BORDER)
    return ctk.CTkFrame(parent, **kw)


def fmt_duration(sec: float) -> str:
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} h {m:02d} min"
    if m:
        return f"{m} min {s:02d} s"
    return f"{s} s"
