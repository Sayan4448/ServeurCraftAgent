"""Palette et styles — thème sombre ou clair.

`apply(mode)` met à jour les constantes du module AVANT la construction de
l'UI (appelé dans main.py au démarrage). Le changement de thème s'applique
au prochain lancement.
"""
import customtkinter as ctk

_DARK = {
    "BG": "#0e1116", "PANEL": "#151a23", "PANEL_2": "#1b2230",
    "HOVER": "#232d40", "BORDER": "#2a3347",
    "ACCENT": "#3b82f6", "ACCENT_HOVER": "#2563eb",
    "GREEN": "#22c55e", "RED": "#ef4444", "ORANGE": "#f59e0b",
    "TEXT": "#e6e9ef", "MUTED": "#8b94a7",
    "CONSOLE_BG": "#0a0d12", "CONSOLE_TEXT": "#c9d1d9",
}

_LIGHT = {
    "BG": "#eef1f6", "PANEL": "#ffffff", "PANEL_2": "#e6eaf2",
    "HOVER": "#d4dbe8", "BORDER": "#c3cddb",
    "ACCENT": "#2563eb", "ACCENT_HOVER": "#1d4ed8",
    "GREEN": "#16a34a", "RED": "#dc2626", "ORANGE": "#d97706",
    "TEXT": "#182130", "MUTED": "#5d6a80",
    "CONSOLE_BG": "#f4f6fa", "CONSOLE_TEXT": "#1c2430",
}

BG = PANEL = PANEL_2 = HOVER = BORDER = ACCENT = ACCENT_HOVER = ""
GREEN = RED = ORANGE = TEXT = MUTED = CONSOLE_BG = CONSOLE_TEXT = ""

FONT = "Segoe UI"
FONT_MONO = "Consolas"


def apply(mode: str) -> None:
    p = _LIGHT if mode == "light" else _DARK
    globals().update(p)
    ctk.set_appearance_mode(mode)


# palette par défaut au cas où apply() n'aurait pas été appelé
globals().update(_DARK)
