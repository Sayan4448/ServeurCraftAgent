"""Fenêtre principale : en-tête + Tabview (3 onglets)."""
import sys
from pathlib import Path

import customtkinter as ctk

from . import theme
from .tab_servers import ServersTab
from .tab_creator import CreatorTab
from .tab_ai import AiTab


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("ServerCraft Agent")
        self.geometry("1240x780")
        self.minsize(1040, 660)
        self.configure(fg_color=theme.BG)
        self.after(250, self._set_icon)

        header = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=0, height=56)
        header.pack(fill="x")
        header.pack_propagate(False)
        ctk.CTkLabel(
            header, text="⛏  ServerCraft Agent",
            font=(theme.FONT, 20, "bold"), text_color=theme.TEXT,
        ).pack(side="left", padx=18)
        ctk.CTkLabel(
            header, text="Créateur & gestionnaire de serveurs Minecraft — sans compte requis",
            font=(theme.FONT, 12), text_color=theme.MUTED,
        ).pack(side="left", padx=8)

        self.tabview = ctk.CTkTabview(
            self, fg_color=theme.BG, corner_radius=10,
            segmented_button_fg_color=theme.PANEL,
            segmented_button_selected_color=theme.ACCENT,
            segmented_button_selected_hover_color=theme.ACCENT_HOVER,
            segmented_button_unselected_color=theme.PANEL,
            segmented_button_unselected_hover_color=theme.HOVER,
            anchor="nw",
        )
        self.tabview.pack(fill="both", expand=True, padx=12, pady=(4, 12))

        self.tabview.add("Mes Serveurs")
        self.tabview.add("Créateur Rapide")
        self.tabview.add("Agent IA & Outils")

        self.servers_tab = ServersTab(self.tabview.tab("Mes Serveurs"))
        self.servers_tab.pack(fill="both", expand=True)

        self.creator_tab = CreatorTab(
            self.tabview.tab("Créateur Rapide"),
            on_created=lambda meta: self.servers_tab.refresh(),
        )
        self.creator_tab.pack(fill="both", expand=True)

        self.ai_tab = AiTab(self.tabview.tab("Agent IA & Outils"))
        self.ai_tab.pack(fill="both", expand=True)

    def _set_icon(self):
        base = (Path(sys.executable).parent if getattr(sys, "frozen", False)
                else Path(__file__).resolve().parent.parent.parent)
        ico = base / "assets" / "icon.ico"
        if ico.exists():
            try:
                self.wm_iconbitmap(str(ico))
            except Exception:
                pass
