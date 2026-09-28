"""Fenêtre principale : en-tête + Tabview (2 onglets) + Paramètres."""
import sys
from pathlib import Path

import customtkinter as ctk
from tkinter import messagebox

from ..config import load_settings, save_settings
from ..i18n import LANGS, t
from . import theme
from .tab_servers import ServersTab
from .tab_creator import CreatorTab


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
            header, text=t("header_sub"),
            font=(theme.FONT, 12), text_color=theme.MUTED,
        ).pack(side="left", padx=8)
        ctk.CTkButton(
            header, text="⚙", width=40, height=34,
            fg_color=theme.PANEL_2, hover_color=theme.HOVER,
            font=(theme.FONT, 16),
            command=lambda: SettingsDialog(self),
        ).pack(side="right", padx=14)

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

        self.tabview.add(t("tab_servers"))
        self.tabview.add(t("tab_creator"))

        self.servers_tab = ServersTab(self.tabview.tab(t("tab_servers")))
        self.servers_tab.pack(fill="both", expand=True)

        self.creator_tab = CreatorTab(
            self.tabview.tab(t("tab_creator")),
            on_created=lambda meta: self.servers_tab.refresh(),
        )
        self.creator_tab.pack(fill="both", expand=True)

        # Onglet Agent IA — bêta, activé dans les Paramètres
        if load_settings().get("ai_beta"):
            from .tab_ai import AiTab
            self.tabview.add(t("tab_ai"))
            self.ai_tab = AiTab(self.tabview.tab(t("tab_ai")))
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


class SettingsDialog(ctk.CTkToplevel):
    """Paramètres : langue, thème, interface serveur, IA bêta, clé CurseForge."""

    def __init__(self, master):
        super().__init__(master)
        self.settings = load_settings()
        self.title(t("settings"))
        self.geometry("500x470")
        self.configure(fg_color=theme.BG)
        self.transient(master)
        self.grab_set()

        card = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=10)
        card.pack(fill="both", expand=True, padx=14, pady=14)

        ctk.CTkLabel(card, text=t("settings"),
                     font=(theme.FONT, 15, "bold"),
                     text_color=theme.TEXT).pack(anchor="w", padx=14, pady=(14, 8))

        # langue + thème
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=6)
        ctk.CTkLabel(row, text=t("language"), width=140, anchor="w",
                     text_color=theme.MUTED).pack(side="left")
        self.lang_menu = ctk.CTkOptionMenu(
            row, values=list(LANGS.values()), width=160,
            fg_color=theme.PANEL_2, button_color=theme.ACCENT,
            button_hover_color=theme.ACCENT_HOVER, text_color=theme.TEXT)
        self.lang_menu.set(LANGS.get(self.settings.get("language"), "Français"))
        self.lang_menu.pack(side="left")

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=6)
        ctk.CTkLabel(row, text=t("theme"), width=140, anchor="w",
                     text_color=theme.MUTED).pack(side="left")
        self.theme_seg = ctk.CTkSegmentedButton(
            row, values=[t("theme_dark"), t("theme_light")],
            selected_color=theme.ACCENT,
            selected_hover_color=theme.ACCENT_HOVER,
            unselected_color=theme.PANEL_2,
            unselected_hover_color=theme.HOVER)
        self.theme_seg.set(
            t("theme_light") if self.settings.get("theme") == "light"
            else t("theme_dark"))
        self.theme_seg.pack(side="left")
        ctk.CTkLabel(card, text=t("restart_hint"), font=(theme.FONT, 10),
                     text_color=theme.MUTED).pack(anchor="w", padx=14)

        # interface serveur
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=10)
        self.iface_switch = ctk.CTkSwitch(
            row, text=t("server_interface"), text_color=theme.TEXT,
            progress_color=theme.ACCENT)
        if self.settings.get("server_interface", True):
            self.iface_switch.select()
        self.iface_switch.pack(side="left")
        ctk.CTkLabel(card, text=t("server_interface_hint"),
                     font=(theme.FONT, 10), text_color=theme.MUTED,
                     wraplength=440, justify="left").pack(
            anchor="w", padx=14, pady=(0, 8))

        # agent IA (bêta)
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=6)
        self.ai_switch = ctk.CTkSwitch(
            row, text=t("ai_beta"), text_color=theme.TEXT,
            progress_color=theme.ORANGE,
            command=self._ai_toggled)
        if self.settings.get("ai_beta"):
            self.ai_switch.select()
        self.ai_switch.pack(side="left")
        ctk.CTkLabel(card, text=t("ai_beta_hint"), font=(theme.FONT, 10),
                     text_color=theme.MUTED, wraplength=440,
                     justify="left").pack(anchor="w", padx=14, pady=(0, 8))

        # clé curseforge
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=6)
        ctk.CTkLabel(row, text=t("cf_key_label"), width=140, anchor="w",
                     text_color=theme.MUTED).pack(side="left")
        self.cf_entry = ctk.CTkEntry(
            row, width=250, show="•", placeholder_text="x-api-key",
            fg_color=theme.PANEL_2, border_color=theme.BORDER,
            text_color=theme.TEXT)
        self.cf_entry.insert(0, self.settings.get("curseforge_api_key", ""))
        self.cf_entry.pack(side="left")
        ctk.CTkLabel(card, text=t("cf_key_hint"), font=(theme.FONT, 10),
                     text_color=theme.MUTED, wraplength=440,
                     justify="left").pack(anchor="w", padx=14, pady=(0, 8))

        ctk.CTkButton(card, text=t("save_close"), width=140,
                      fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                      command=self._save).pack(pady=10)

    def _ai_toggled(self):
        if self.ai_switch.get():
            messagebox.showwarning(
                t("ai_beta_warn_t"), t("ai_beta_warn"), parent=self)

    def _save(self):
        label = self.lang_menu.get()
        for code, name in LANGS.items():
            if name == label:
                self.settings["language"] = code
        self.settings["theme"] = ("light" if self.theme_seg.get()
                                  == t("theme_light") else "dark")
        self.settings["server_interface"] = bool(self.iface_switch.get())
        self.settings["ai_beta"] = bool(self.ai_switch.get())
        self.settings["curseforge_api_key"] = self.cf_entry.get().strip()
        save_settings(self.settings)
        self.destroy()
