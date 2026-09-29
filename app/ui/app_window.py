"""Fenêtre principale : en-tête + Tabview (2 onglets) + Paramètres."""
import sys
import threading
from pathlib import Path

import customtkinter as ctk
from tkinter import messagebox

from ..config import load_settings, save_settings
from ..core import discord
from ..i18n import LANGS, t
from . import theme
from .uithread import ui_call
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
        from .uithread import install
        install(self)
        from ..core import scheduler
        scheduler.start()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        header = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=0,
                              height=60, border_width=0)
        header.pack(fill="x")
        header.pack_propagate(False)
        logo = ctk.CTkLabel(header, text="⛏", width=38, height=38,
                            corner_radius=10, fg_color=theme.ACCENT,
                            text_color="#ffffff", font=(theme.FONT, 18))
        logo.pack(side="left", padx=(18, 10))
        titles = ctk.CTkFrame(header, fg_color="transparent")
        titles.pack(side="left")
        ctk.CTkLabel(titles, text="ServerCraft Agent",
                     font=(theme.FONT, 17, "bold"), text_color=theme.TEXT,
                     anchor="w").pack(anchor="w")
        ctk.CTkLabel(titles, text=t("header_sub"), font=(theme.FONT, 11),
                     text_color=theme.MUTED, anchor="w").pack(anchor="w")
        ctk.CTkButton(
            header, text="⚙  " + t("settings"), width=120, height=34,
            fg_color=theme.PANEL_2, hover_color=theme.HOVER,
            text_color=theme.TEXT, font=(theme.FONT, 12),
            command=lambda: SettingsDialog(self),
        ).pack(side="right", padx=16)
        self.theme_btn = ctk.CTkButton(
            header, text="", width=38, height=34, fg_color=theme.PANEL_2,
            hover_color=theme.HOVER, text_color=theme.TEXT,
            font=(theme.FONT, 15), command=self._toggle_theme)
        self.theme_btn.pack(side="right")
        self._theme_icon()
        ctk.CTkFrame(self, height=1, fg_color=theme.BORDER,
                     corner_radius=0).pack(fill="x")

        self.tabview = ctk.CTkTabview(
            self, fg_color=theme.BG, corner_radius=10,
            segmented_button_fg_color=theme.PANEL_2,
            segmented_button_selected_color=theme.SEL,
            segmented_button_selected_hover_color=theme.SEL_HOVER,
            segmented_button_unselected_color=theme.PANEL_2,
            segmented_button_unselected_hover_color=theme.HOVER,
            text_color=theme.TEXT, anchor="nw",
        )
        self.tabview.pack(fill="both", expand=True, padx=12, pady=(6, 12))
        self.tabview._segmented_button.configure(
            font=(theme.FONT, 13, "bold"), height=34)

        self.tabview.add(t("tab_servers"))
        self.tabview.add(t("tab_creator"))

        self.servers_tab = ServersTab(
            self.tabview.tab(t("tab_servers")),
            on_new=lambda: self.tabview.set(t("tab_creator")))
        self.servers_tab.pack(fill="both", expand=True)

        self.creator_tab = CreatorTab(
            self.tabview.tab(t("tab_creator")),
            on_created=self._server_created,
        )
        self.creator_tab.pack(fill="both", expand=True)

        # Onglet Agent IA — bêta, activé dans les Paramètres
        if load_settings().get("ai_beta"):
            from .tab_ai import AiTab
            self.tabview.add(t("tab_ai"))
            self.ai_tab = AiTab(self.tabview.tab(t("tab_ai")))
            self.ai_tab.pack(fill="both", expand=True)

    def _on_close(self):
        """Arrête proprement les serveurs (sinon java.exe reste orphelin)."""
        from ..core import server_manager as sm
        running = [p for p in sm.PROCESSES.values() if p.is_running()]
        if running:
            if not messagebox.askyesno(
                    t("quit_title"), t("quit_running", n=len(running)),
                    parent=self):
                return
            win = ctk.CTkToplevel(self)
            win.title("ServerCraft Agent")
            win.geometry("360x110")
            win.configure(fg_color=theme.BG)
            ctk.CTkLabel(win, text=t("quit_stopping"),
                         font=(theme.FONT, 13), text_color=theme.TEXT).pack(
                expand=True)
            win.update()
            sm.stop_all(timeout=40)
        self.destroy()

    def _server_created(self, meta):
        self.servers_tab.select_by_name(meta["name"])
        self.tabview.set(t("tab_servers"))

    def _theme_icon(self):
        self.theme_btn.configure(text="☀" if theme.is_dark() else "☾")

    def _toggle_theme(self):
        mode = "light" if theme.is_dark() else "dark"
        theme.apply(mode)
        s = load_settings()
        s["theme"] = mode
        save_settings(s)
        self._theme_icon()

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
    """Paramètres : langue, thème, interface serveur, IA bêta, clé CurseForge,
    notifications Discord."""

    def __init__(self, master):
        super().__init__(master)
        self.settings = load_settings()
        self.title(t("settings"))
        self.geometry("560x640")
        self.configure(fg_color=theme.BG)
        self.transient(master)
        self.grab_set()

        card = ctk.CTkScrollableFrame(self, fg_color=theme.PANEL,
                                      corner_radius=10)
        card.pack(fill="both", expand=True, padx=14, pady=(14, 0))

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
            selected_color=theme.SEL, text_color=theme.TEXT,
            selected_hover_color=theme.SEL_HOVER,
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

        # monitoring
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=6)
        self.mon_switch = ctk.CTkSwitch(
            row, text=t("mon_setting"), text_color=theme.TEXT,
            progress_color=theme.ACCENT)
        if self.settings.get("monitoring", True):
            self.mon_switch.select()
        self.mon_switch.pack(side="left")
        ctk.CTkLabel(card, text=t("mon_setting_hint"),
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

        # notifications Discord
        ctk.CTkLabel(card, text=t("dc_section"),
                     font=(theme.FONT, 13, "bold"),
                     text_color=theme.ACCENT).pack(anchor="w", padx=14,
                                                   pady=(10, 4))
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=6)
        ctk.CTkLabel(row, text=t("dc_url"), width=140, anchor="w",
                     text_color=theme.MUTED).pack(side="left")
        self.dc_entry = ctk.CTkEntry(
            row, width=250, show="•",
            placeholder_text="https://discord.com/api/webhooks/…",
            fg_color=theme.PANEL_2, border_color=theme.BORDER,
            text_color=theme.TEXT)
        self.dc_entry.insert(0, self.settings.get("discord_webhook", ""))
        self.dc_entry.pack(side="left")
        self.dc_test_btn = ctk.CTkButton(
            row, text=t("dc_test"), width=70, fg_color=theme.PANEL_2,
            hover_color=theme.HOVER, text_color=theme.TEXT,
            command=self._dc_test)
        self.dc_test_btn.pack(side="left", padx=(6, 0))
        evs = ctk.CTkFrame(card, fg_color="transparent")
        evs.pack(fill="x", padx=14, pady=(2, 4))
        cur = self.settings.get("discord_events") or {}
        self.dc_checks = {}
        for i, ev in enumerate(discord.EVENTS):
            cb = ctk.CTkCheckBox(evs, text=t(f"dc_ev_{ev}"),
                                 text_color=theme.TEXT, fg_color=theme.ACCENT,
                                 hover_color=theme.ACCENT_HOVER, width=20)
            if cur.get(ev, True):
                cb.select()
            cb.grid(row=i // 3, column=i % 3, sticky="w", padx=(0, 14),
                    pady=2)
            self.dc_checks[ev] = cb
        self.dc_status = ctk.CTkLabel(card, text="", font=(theme.FONT, 10),
                                      text_color=theme.MUTED, anchor="w")
        self.dc_status.pack(anchor="w", padx=14)
        ctk.CTkLabel(card, text=t("dc_hint"), font=(theme.FONT, 10),
                     text_color=theme.MUTED, wraplength=440,
                     justify="left").pack(anchor="w", padx=14, pady=(0, 8))

        ctk.CTkButton(self, text=t("save_close"), width=140,
                      fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                      command=self._save).pack(pady=10)

    def _dc_test(self):
        url = self.dc_entry.get().strip()
        if not discord.valid_url(url):
            self.dc_status.configure(text=t("dc_bad_url"),
                                     text_color=theme.RED)
            return
        self.dc_test_btn.configure(state="disabled")
        self.dc_status.configure(text="…", text_color=theme.MUTED)

        def work():                   # thread : requête HTTP
            ui_call(self, self._dc_tested, discord.send_test(url))
        threading.Thread(target=work, daemon=True).start()

    def _dc_tested(self, err):
        self.dc_test_btn.configure(state="normal")
        if err:
            self.dc_status.configure(text=t("dc_test_err", e=err),
                                     text_color=theme.RED)
        else:
            self.dc_status.configure(text=t("dc_test_ok"),
                                     text_color=theme.GREEN)

    def _ai_toggled(self):
        if self.ai_switch.get():
            messagebox.showwarning(
                t("ai_beta_warn_t"), t("ai_beta_warn"), parent=self)

    def _save(self):
        url = self.dc_entry.get().strip()
        if url and not discord.valid_url(url):
            self.dc_status.configure(text=t("dc_bad_url"),
                                     text_color=theme.RED)
            return
        self.settings["discord_webhook"] = url
        self.settings["discord_events"] = {
            ev: bool(cb.get()) for ev, cb in self.dc_checks.items()}
        label = self.lang_menu.get()
        for code, name in LANGS.items():
            if name == label:
                self.settings["language"] = code
        self.settings["theme"] = ("light" if self.theme_seg.get()
                                  == t("theme_light") else "dark")
        self.settings["server_interface"] = bool(self.iface_switch.get())
        self.settings["monitoring"] = bool(self.mon_switch.get())
        if hasattr(self.master, "servers_tab"):
            self.master.servers_tab.set_monitoring(
                self.settings["monitoring"])
        self.settings["ai_beta"] = bool(self.ai_switch.get())
        self.settings["curseforge_api_key"] = self.cf_entry.get().strip()
        save_settings(self.settings)
        theme.apply(self.settings["theme"])       # appliqué immédiatement
        if hasattr(self.master, "_theme_icon"):
            self.master._theme_icon()
        self.destroy()
