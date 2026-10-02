"""Fenêtre principale : en-tête + Tabview (2 onglets) + Paramètres + Aide."""
import os
import sys
import threading
import webbrowser
from pathlib import Path

import customtkinter as ctk
from tkinter import messagebox

from .. import __channel__, __version__
from ..config import APP_DIR, curseforge_key, load_settings, save_settings
from ..core import discord, playit
from ..core import mods as mods_mod
from ..i18n import LANGS, t
from . import theme
from .feedback import Tooltip, toast
from .playit_panel import PlayitPanel
from .uithread import ui_call
from .tab_servers import ServersTab
from .tab_creator import CreatorTab


REPO_URL = "https://github.com/Sayan4448/ServeurCraftAgent"
VERSION_LABEL = f"v{__version__} {__channel__}".strip()


def _install_dir() -> Path:
    """Dossier de l'app (exe installé, ou racine des sources)."""
    return (Path(sys.executable).parent if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parent.parent.parent)


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
        logo = self._logo(header)
        logo.pack(side="left", padx=(18, 10))
        titles = ctk.CTkFrame(header, fg_color="transparent")
        titles.pack(side="left")
        name_row = ctk.CTkFrame(titles, fg_color="transparent")
        name_row.pack(anchor="w")
        ctk.CTkLabel(name_row, text="ServerCraft Agent",
                     font=(theme.FONT, 17, "bold"), text_color=theme.TEXT,
                     anchor="w").pack(side="left")
        ctk.CTkLabel(name_row, text=VERSION_LABEL, height=18,
                     corner_radius=9, fg_color=theme.PANEL_2,
                     font=(theme.FONT, 10, "bold"),
                     text_color=theme.MUTED).pack(side="left", padx=8)
        ctk.CTkLabel(titles, text=t("header_sub"), font=(theme.FONT, 11),
                     text_color=theme.MUTED, anchor="w").pack(anchor="w")
        # navigation entre les pages, au centre de l'en-tête
        self.nav = ctk.CTkFrame(header, fg_color=theme.PANEL_2,
                                corner_radius=12)
        self.nav.pack(side="left", padx=(36, 0))
        self._nav_btns: dict = {}
        tool = dict(height=34, fg_color=theme.PANEL_2,
                    hover_color=theme.HOVER, text_color=theme.TEXT,
                    font=(theme.FONT, 12))
        ctk.CTkButton(
            header, width=120, command=self.open_settings, **tool,
            **theme.labelled("settings", t("settings"), "⚙"),
        ).pack(side="right", padx=(8, 16))
        help_btn = ctk.CTkButton(
            header, width=38, command=self.open_help, **tool,
            **theme.labelled("help", "", "?"))
        help_btn.pack(side="right", padx=(8, 0))
        Tooltip(help_btn, f"{t('help_title')} (F1)")
        self.theme_btn = ctk.CTkButton(
            header, text="", width=38, command=self._toggle_theme, **tool)
        self.theme_btn.pack(side="right")
        Tooltip(self.theme_btn, t("tip_theme"))
        self._theme_icon()
        ctk.CTkFrame(self, height=1, fg_color=theme.BORDER,
                     corner_radius=0).pack(fill="x")

        self.tabview = Pages(self)
        self.tabview.pack(fill="both", expand=True, padx=12, pady=12)

        self._add_page(t("tab_servers"), "list")
        self._add_page(t("tab_creator"), "add")

        self.servers_tab = ServersTab(
            self.tabview.tab(t("tab_servers")),
            on_new=lambda: self.show_tab(t("tab_creator")))
        self.servers_tab.pack(fill="both", expand=True)

        self.creator_tab = CreatorTab(
            self.tabview.tab(t("tab_creator")),
            on_created=self._server_created,
        )
        self.creator_tab.pack(fill="both", expand=True)

        # Onglet Agent IA — bêta, activé dans les Paramètres
        if load_settings().get("ai_beta"):
            from .tab_ai import AiTab
            self._add_page(t("tab_ai"), "robot")
            self.ai_tab = AiTab(self.tabview.tab(t("tab_ai")))
            self.ai_tab.pack(fill="both", expand=True)

        self.show_tab(t("tab_servers"))
        self._bind_shortcuts()

    def _add_page(self, name: str, icon: str):
        self.tabview.add(name)
        btn = ctk.CTkButton(
            self.nav, height=32, corner_radius=10, width=0,
            font=(theme.FONT, 13, "bold"), fg_color="transparent",
            hover_color=theme.HOVER, text_color=theme.MUTED,
            command=lambda: self.show_tab(name),
            **theme.labelled(icon, name, "", 15, theme.MUTED))
        btn.pack(side="left", padx=3, pady=3)
        self._nav_btns[name] = (btn, icon)

    def _nav_sync(self):
        """Bouton de la page affichée en couleur d'accent."""
        current = self.tabview.get()
        for name, (btn, icon) in self._nav_btns.items():
            on = name == current
            color = theme.ON_ACCENT if on else theme.MUTED
            btn.configure(fg_color=theme.ACCENT if on else "transparent",
                          hover_color=theme.ACCENT_HOVER if on
                          else theme.HOVER, text_color=color)
            img = theme.icon(icon, 15, color)
            if img is not None:
                btn.configure(image=img)

    def _logo(self, parent):
        """Icône de l'app (assets/icon.png) ; pastille de repli sinon."""
        try:
            from PIL import Image
            img = Image.open(_install_dir() / "assets" / "icon.png")
            self._logo_img = ctk.CTkImage(img, size=(38, 38))
            return ctk.CTkLabel(parent, text="", image=self._logo_img,
                                width=38, height=38)
        except Exception:  # noqa: BLE001 — fichier absent ou illisible
            return ctk.CTkLabel(parent, text="⛏", width=38, height=38,
                                corner_radius=10, fg_color=theme.ACCENT,
                                text_color="#ffffff", font=(theme.FONT, 18))

    # ------------------------------------------------------------ raccourcis
    def _bind_shortcuts(self):
        """Raccourcis de la fenêtre principale (liste dans l'aide, F1). Ils
        ne s'appliquent pas aux autres fenêtres ouvertes."""
        def on_servers(fn):
            def run(_e=None):
                if self.tabview.get() == t("tab_servers"):
                    fn()
            return run

        def console(fn):
            def run(_e=None):
                self.show_tab(t("tab_servers"))
                fn()
            return run
        tab = self.servers_tab
        for keys, fn in (
                (("<Control-n>", "<Control-N>"),
                 lambda _e=None: self.show_tab(t("tab_creator"))),
                (("<F5>",), on_servers(tab.start_selected)),
                (("<Shift-F5>",), on_servers(tab.stop_selected)),
                (("<Control-r>", "<Control-R>"),
                 on_servers(tab.restart_selected)),
                (("<Control-l>", "<Control-L>"), console(tab.focus_command)),
                (("<Control-f>", "<Control-F>"), console(tab.focus_filter)),
                (("<Control-comma>",), lambda _e=None: self.open_settings()),
                (("<F1>",), lambda _e=None: self.open_help())):
            for key in keys:
                self.bind(key, fn)

    def show_tab(self, name: str):
        """Affiche une page (Mes serveurs, Créateur…) et met la navigation
        de l'en-tête à jour."""
        self.tabview.set(name)
        self._nav_sync()

    def open_settings(self):
        SettingsDialog(self)

    def open_help(self):
        HelpDialog.show(self)

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
        self.show_tab(t("tab_servers"))

    def _theme_icon(self):
        img = theme.icon("sun" if theme.is_dark() else "moon")
        if img is not None:
            self.theme_btn.configure(image=img, text="")
        else:
            self.theme_btn.configure(text="☀" if theme.is_dark() else "☾")

    def _toggle_theme(self):
        mode = "light" if theme.is_dark() else "dark"
        theme.apply(mode)
        s = load_settings()
        s["theme"] = mode
        save_settings(s)
        self._theme_icon()

    def _set_icon(self):
        ico = _install_dir() / "assets" / "icon.ico"
        if ico.exists():
            try:
                self.wm_iconbitmap(str(ico))
            except Exception:
                pass


class Pages(ctk.CTkFrame):
    """Pages de la fenêtre principale, une seule visible à la fois. Même
    interface que CTkTabview (`add`, `tab`, `get`, `set`) sans sa barre
    d'onglets (la navigation est dans l'en-tête) ni son masquage différé,
    qui laissait la fenêtre vide après deux changements rapprochés."""

    def __init__(self, master):
        super().__init__(master, fg_color="transparent")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._pages: dict = {}
        self._current = ""

    @property
    def _name_list(self) -> list:
        return list(self._pages)

    def add(self, name: str):
        page = ctk.CTkFrame(self, fg_color="transparent")
        self._pages[name] = page
        if not self._current:
            self.set(name)
        return page

    def tab(self, name: str):
        return self._pages[name]

    def get(self) -> str:
        return self._current

    def set(self, name: str) -> None:
        for n, page in self._pages.items():
            if n == name:
                page.grid(row=0, column=0, sticky="nsew")
            else:
                page.grid_remove()
        self._current = name


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
            **theme.SEG)
        self.theme_seg.set(
            t("theme_light") if self.settings.get("theme") == "light"
            else t("theme_dark"))
        self.theme_seg.pack(side="left")

        # couleur d'accent (appliquée au prochain lancement)
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=6)
        ctk.CTkLabel(row, text=t("accent"), width=140, anchor="w",
                     text_color=theme.MUTED).pack(side="left")
        self._accent = self.settings.get("accent", "blue")
        self._accent_btns = {}
        for name, (color, *_rest) in theme.ACCENTS.items():
            b = ctk.CTkButton(row, text="", width=26, height=26,
                              corner_radius=13, fg_color=color,
                              hover_color=color, border_width=3,
                              command=lambda n=name: self._pick_accent(n))
            b.pack(side="left", padx=3)
            Tooltip(b, t(f"accent_{name}"))
            self._accent_btns[name] = b
        self._pick_accent(self._accent)
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
        self.cf_test_btn = ctk.CTkButton(
            row, text=t("cf_key_test"), width=70, fg_color=theme.PANEL_2,
            hover_color=theme.HOVER, text_color=theme.TEXT,
            command=self._cf_test)
        self.cf_test_btn.pack(side="left", padx=(6, 0))
        env_key = not self.settings.get("curseforge_api_key") and \
            curseforge_key({})
        self.cf_status = ctk.CTkLabel(
            card, text=t("cf_key_env") if env_key else "",
            font=(theme.FONT, 10), text_color=theme.MUTED, anchor="w",
            wraplength=440, justify="left")
        self.cf_status.pack(anchor="w", padx=14)
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

        # Playit.gg (IP gratuite)
        ctk.CTkLabel(card, text=t("pl_set_section"),
                     font=(theme.FONT, 13, "bold"),
                     text_color=theme.ACCENT).pack(anchor="w", padx=14,
                                                   pady=(10, 4))
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(2, 10))
        self.pl_status = ctk.CTkLabel(row, text="", font=(theme.FONT, 11),
                                      anchor="w", justify="left",
                                      wraplength=300)
        self.pl_status.pack(side="left", fill="x", expand=True)
        self.pl_btn = ctk.CTkButton(row, text="", width=0, height=30,
                                    command=self._pl_action)
        self.pl_btn.pack(side="right")
        self._pl_refresh()

        ctk.CTkButton(self, text=t("save_close"), width=140,
                      fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                      command=self._save).pack(pady=10)

    def _cf_test(self):
        """Vérifie la clé saisie (ou celle de l'environnement) auprès de
        CurseForge, sans l'enregistrer."""
        key = self.cf_entry.get().strip() or curseforge_key({})
        self.cf_test_btn.configure(state="disabled")
        self.cf_status.configure(text=t("cf_key_testing"),
                                 text_color=theme.MUTED)

        def work():                   # thread : requête HTTP
            try:
                mods_mod.check_curseforge_key(key)
                ui_call(self, self._cf_tested, "")
            except Exception as e:  # noqa: BLE001
                ui_call(self, self._cf_tested, mods_mod.explain(e))
        threading.Thread(target=work, daemon=True).start()

    def _cf_tested(self, err):
        self.cf_test_btn.configure(state="normal")
        self.cf_status.configure(
            text=err or t("cf_key_ok"),
            text_color=theme.RED if err else theme.GREEN)

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

    def _pl_refresh(self):
        if playit.linked():
            self.pl_status.configure(text=t("pl_set_linked"),
                                     text_color=theme.GREEN)
            self.pl_btn.configure(text=t("pl_unlink_btn"),
                                  fg_color=theme.PANEL_2,
                                  hover_color=theme.RED,
                                  text_color=theme.TEXT)
        else:
            self.pl_status.configure(text=t("pl_set_unlinked"),
                                     text_color=theme.MUTED)
            self.pl_btn.configure(text=t("pl_link_btn"),
                                  fg_color=theme.ACCENT,
                                  hover_color=theme.ACCENT_HOVER,
                                  text_color=theme.ON_ACCENT)

    def _pl_action(self):
        if not playit.linked():
            PlayitPanel.show(self, on_done=self._pl_refresh)
        elif messagebox.askyesno(t("pl_set_section"),
                                 t("pl_unlink_confirm"), parent=self):
            playit.unlink()
            self._pl_refresh()

    def _pick_accent(self, name: str):
        self._accent = name
        for n, b in self._accent_btns.items():
            b.configure(border_color=theme.TEXT if n == name else theme.PANEL)

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
        before = load_settings()
        self.settings["accent"] = self._accent
        # langue et couleur d'accent : lues à la création des widgets
        lang_changed = self.settings["language"] != before.get("language") \
            or self._accent != before.get("accent", "blue")
        save_settings(self.settings)
        theme.apply(self.settings["theme"])       # appliqué immédiatement
        if hasattr(self.master, "_theme_icon"):
            self.master._theme_icon()
        master = self.master
        self.destroy()
        toast(master, t("set_restart") if lang_changed else t("set_saved"),
              "info" if lang_changed else "success",
              5000 if lang_changed else 2500)


class HelpDialog(ctk.CTkToplevel):
    """Aide : raccourcis clavier, version, dossier des données, liens."""
    _open = None

    @classmethod
    def show(cls, master):
        if cls._open is not None and cls._open.winfo_exists():
            cls._open.lift()
            cls._open.focus_force()
            return cls._open
        cls._open = cls(master)
        return cls._open

    SHORTCUTS = (
        ("Ctrl + N", "sc_new"), ("F5", "sc_start"), ("Maj + F5", "sc_stop"),
        ("Ctrl + R", "sc_restart"), ("Ctrl + L", "sc_command"),
        ("↑ / ↓", "sc_history"), ("Ctrl + F", "sc_filter"),
        ("Ctrl + ,", "sc_settings"), ("F1", "sc_help"),
    )

    def __init__(self, master):
        super().__init__(master)
        self.title(t("help_title"))
        self.geometry("520x600")
        self.minsize(460, 420)
        self.configure(fg_color=theme.BG)
        self.transient(master)
        self.after(100, self.lift)
        self.bind("<Escape>", lambda _e: self.destroy())

        body = ctk.CTkScrollableFrame(self, fg_color=theme.PANEL,
                                      corner_radius=theme.RADIUS)
        body.pack(fill="both", expand=True, padx=14, pady=14)

        def section(text):
            ctk.CTkLabel(body, text=text, font=(theme.FONT, 13, "bold"),
                         text_color=theme.ACCENT, anchor="w").pack(
                fill="x", padx=14, pady=(14, 6))

        section(t("help_shortcuts"))
        for keys, label in self.SHORTCUTS:
            row = ctk.CTkFrame(body, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=2)
            ctk.CTkLabel(row, text=keys, width=96, height=24,
                         corner_radius=6, fg_color=theme.PANEL_2,
                         font=(theme.FONT_MONO, 11),
                         text_color=theme.TEXT).pack(side="left")
            ctk.CTkLabel(row, text=t(label), font=(theme.FONT, 12),
                         text_color=theme.TEXT, anchor="w",
                         justify="left", wraplength=340).pack(
                side="left", padx=12)
        ctk.CTkLabel(body, text=t("sc_inventory"), font=(theme.FONT, 11),
                     text_color=theme.MUTED, anchor="w", justify="left",
                     wraplength=440).pack(fill="x", padx=14, pady=(8, 0))

        section(t("help_data"))
        ctk.CTkLabel(body, text=str(APP_DIR), font=(theme.FONT_MONO, 10),
                     text_color=theme.MUTED, anchor="w", justify="left",
                     wraplength=440).pack(fill="x", padx=14)
        btn = dict(height=30, fg_color=theme.PANEL_2,
                   hover_color=theme.HOVER, text_color=theme.TEXT)
        ctk.CTkButton(body, command=self._open_data, **btn,
                      **theme.labelled("folder", t("help_open_data"), "📁")
                      ).pack(anchor="w", padx=14, pady=(8, 0))

        section(t("help_about"))
        ctk.CTkLabel(body, text=f"ServerCraft Agent  {VERSION_LABEL}",
                     font=(theme.FONT, 13, "bold"), text_color=theme.TEXT,
                     anchor="w").pack(fill="x", padx=14)
        ctk.CTkLabel(body, text=t("help_privacy"), font=(theme.FONT, 11),
                     text_color=theme.MUTED, anchor="w").pack(
            fill="x", padx=14, pady=(2, 8))
        links = ctk.CTkFrame(body, fg_color="transparent")
        links.pack(fill="x", padx=14, pady=(0, 14))
        if (_install_dir() / "CHANGELOG.md").exists():
            ctk.CTkButton(links, command=self._open_changelog, **btn,
                          **theme.labelled("list", t("help_changelog"), "")
                          ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(links, command=lambda: webbrowser.open(REPO_URL),
                      **btn, **theme.labelled("globe", "GitHub", "")
                      ).pack(side="left")

    def _open_data(self):
        try:
            os.startfile(str(APP_DIR))          # Windows
        except (OSError, AttributeError):
            webbrowser.open(APP_DIR.as_uri())

    def _open_changelog(self):
        path = _install_dir() / "CHANGELOG.md"
        try:
            os.startfile(str(path))
        except (OSError, AttributeError):
            webbrowser.open(path.as_uri())
