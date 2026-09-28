"""Palette et styles.

Chaque couleur est un tuple (clair, sombre) : CustomTkinter choisit la bonne
selon le mode et **rebascule en direct** quand on change de thème.
Pour les widgets Tk natifs (Menu, tags de Textbox) qui n'acceptent qu'une
chaîne, utiliser `c(couleur)`.
"""
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

FONT = "Segoe UI"
FONT_MONO = "Consolas"


def is_dark() -> bool:
    return ctk.get_appearance_mode() == "Dark"


def c(color) -> str:
    """Résout un tuple (clair, sombre) pour les widgets Tk natifs."""
    if isinstance(color, (tuple, list)):
        return color[1] if is_dark() else color[0]
    return color


def apply(mode: str) -> None:
    ctk.set_appearance_mode("light" if mode == "light" else "dark")


def action_button(btn, enabled: bool, color, hover, text_color=ON_ACCENT):
    """Bouton coloré quand actif, grisé (et visiblement inactif) sinon."""
    if enabled:
        btn.configure(state="normal", fg_color=color, hover_color=hover,
                      text_color=text_color)
    else:
        btn.configure(state="disabled", fg_color=DISABLED,
                      text_color_disabled=DISABLED_TEXT)


def card(parent, **kw):
    kw.setdefault("fg_color", PANEL)
    kw.setdefault("corner_radius", 12)
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
