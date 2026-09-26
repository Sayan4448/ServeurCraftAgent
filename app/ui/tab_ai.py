"""Onglet 'Agent IA & Outils' : chat, analyse de logs, prompts rapides."""
import threading
import time

import customtkinter as ctk

from ..ai.agent import Agent
from ..ai import providers
from ..ai.autonomy import AutonomousModerator, get_moderator, set_moderator
from ..config import load_settings, save_settings
from ..core import server_manager as sm
from . import theme

QUICK_PROMPTS = [
    "Prompts rapides…",
    "Configure ce serveur pour du RP avec Voice Chat et 4 Go de RAM",
    "Optimise les performances du serveur (view-distance, ticks…)",
    "Explique les erreurs présentes dans latest.log",
    "Active une whitelist et liste les commandes utiles",
    "Change le MOTD et passe le serveur en mode aventure",
]

_LABEL_TO_PROVIDER = {v: k for k, v in providers.PROVIDERS.items()}

_ENTRY_STYLE = dict(fg_color=theme.PANEL_2, border_color=theme.BORDER,
                    text_color=theme.TEXT)
_MENU_STYLE = dict(fg_color=theme.PANEL_2, button_color=theme.ACCENT,
                   button_hover_color=theme.ACCENT_HOVER, text_color=theme.TEXT)
_COMBO_STYLE = dict(fg_color=theme.PANEL_2, border_color=theme.BORDER,
                    button_color=theme.ACCENT,
                    button_hover_color=theme.ACCENT_HOVER,
                    dropdown_fg_color=theme.PANEL_2,
                    dropdown_hover_color=theme.HOVER,
                    dropdown_text_color=theme.TEXT, text_color=theme.TEXT)


class AiTab(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master, fg_color="transparent")
        self.settings = load_settings()
        self._agents = {}
        self._busy = False
        self._entries = {}
        self._model_menus = {}

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ------------------------------------------------------------- config
        cfg = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=10)
        cfg.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        ctk.CTkLabel(cfg, text="Provider", text_color=theme.MUTED,
                     font=(theme.FONT, 12)).grid(
            row=0, column=0, padx=(14, 6), pady=10, sticky="w")
        self.provider_menu = ctk.CTkOptionMenu(
            cfg, width=190, values=list(providers.PROVIDERS.values()),
            **_MENU_STYLE, command=self._provider_changed)
        self.provider_menu.set(
            providers.PROVIDERS.get(
                self.settings.get("ai_provider"), providers.PROVIDERS["gemini"]))
        self.provider_menu.grid(row=0, column=1, padx=6, pady=10, sticky="w")

        self.fields_holder = ctk.CTkFrame(cfg, fg_color="transparent")
        self.fields_holder.grid(row=0, column=2, padx=6, pady=10, sticky="w")

        # panneaux par provider (affichés/masqués à la demande)
        self.fields = {
            "gemini": self._build_key_model(
                "gemini_api_key", "gemini_model", "AIza…"),
            "anthropic": self._build_key_model(
                "anthropic_api_key", "anthropic_model", "sk-ant-…"),
            "openai": self._build_openai(),
            "ollama": self._build_local("ollama", "ollama_url"),
            "lmstudio": self._build_local("lmstudio", "lmstudio_url"),
            "custom": self._build_custom(),
        }
        self._provider_changed(self.provider_menu.get())

        # serveur cible
        ctk.CTkLabel(cfg, text="Serveur", text_color=theme.MUTED,
                     font=(theme.FONT, 12)).grid(row=0, column=3, padx=(16, 6))
        self.server_menu = ctk.CTkOptionMenu(
            cfg, width=150, values=self._server_names(),
            **_MENU_STYLE, command=lambda _v: self._server_changed())
        self.server_menu.grid(row=0, column=4, padx=(0, 6), pady=10)
        ctk.CTkButton(cfg, text="⟳", width=32, fg_color=theme.PANEL_2,
                      hover_color=theme.HOVER,
                      command=self._refresh_servers).grid(
            row=0, column=5, padx=(0, 12))

        # -------------------------------------------------- mode autonome
        auto = ctk.CTkFrame(cfg, fg_color="transparent")
        auto.grid(row=1, column=0, columnspan=6, sticky="ew",
                  padx=14, pady=(0, 10))
        self.auto_switch = ctk.CTkSwitch(
            auto, text="🤖 Modération autonome du chat (l'IA surveille et "
            "warn/kick/ban selon les règles)",
            text_color=theme.TEXT, progress_color=theme.ACCENT,
            command=self._toggle_autonomy)
        self.auto_switch.pack(side="left")
        self.rules_entry = ctk.CTkEntry(
            auto, width=400,
            placeholder_text="Règles : ex « warn les insultes, kick au 3e warn »",
            **_ENTRY_STYLE)
        self.rules_entry.insert(0, self.settings.get("auto_mod_rules", ""))
        self.rules_entry.pack(side="left", padx=12)

        # ------------------------------------------------------------- chat
        self.chat_frame = ctk.CTkScrollableFrame(self, fg_color=theme.PANEL,
                                               corner_radius=10)
        self.chat_frame.grid(row=1, column=0, sticky="nsew")

        # ------------------------------------------------------------- saisie
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        bottom.grid_columnconfigure(1, weight=1)

        # barre d'activité : chronomètre + nombre d'actions pendant le travail
        self.activity_lbl = ctk.CTkLabel(
            bottom, text="", font=(theme.FONT, 11, "italic"),
            text_color=theme.ACCENT, anchor="w")
        self.activity_lbl.grid(row=0, column=0, columnspan=4,
                               sticky="w", pady=(0, 2))
        self._busy_since = None
        self._step_count = 0

        self.quick_menu = ctk.CTkOptionMenu(
            bottom, width=210, values=QUICK_PROMPTS, **_MENU_STYLE,
            command=self._quick_pick)
        self.quick_menu.grid(row=1, column=0, padx=(0, 8))

        self.input_entry = ctk.CTkEntry(
            bottom, placeholder_text="Demandez à l'agent (ex: analyse les logs et corrige la config)…",
            fg_color=theme.PANEL, border_color=theme.BORDER,
            text_color=theme.TEXT, height=36)
        self.input_entry.grid(row=1, column=1, sticky="ew", padx=(0, 8))
        self.input_entry.bind("<Return>", lambda e: self._send())

        self.analyze_btn = ctk.CTkButton(
            bottom, text="🔍 Analyser les logs", width=150, height=36,
            fg_color=theme.PANEL_2, hover_color=theme.HOVER,
            command=self._analyze)
        self.analyze_btn.grid(row=1, column=2, padx=(0, 8))
        self.send_btn = ctk.CTkButton(
            bottom, text="Envoyer", width=100, height=36,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            command=self._send)
        self.send_btn.grid(row=1, column=3)

        self._add_bubble(
            "assistant",
            "Bonjour ! Je suis l'agent ServerCraft. Sélectionnez un provider "
            "et un serveur : je peux lire les logs, modifier les fichiers de "
            "configuration et corriger les erreurs pour vous.")

    # ----------------------------------------------------- panneaux provider

    def _label(self, parent, text):
        ctk.CTkLabel(parent, text=text, text_color=theme.MUTED,
                     font=(theme.FONT, 11)).pack(side="left", padx=(0, 4))

    def _entry(self, parent, key, width, ph="", secret=False):
        e = ctk.CTkEntry(parent, width=width, placeholder_text=ph,
                         show="•" if secret else "", **_ENTRY_STYLE)
        e.insert(0, self.settings.get(key, ""))
        e.pack(side="left", padx=(0, 8))
        self._entries[key] = e
        return e

    def _model_menu(self, parent, provider):
        current = self.settings.get(f"{provider}_model", "")
        menu = ctk.CTkComboBox(parent, width=180,
                               values=[current] if current else [],
                               **_COMBO_STYLE)
        menu.set(current)
        menu.pack(side="left", padx=(0, 4))
        self._model_menus[provider] = menu
        return menu

    def _refresh_btn(self, parent, provider):
        ctk.CTkButton(parent, text="⟳", width=32, fg_color=theme.PANEL_2,
                      hover_color=theme.HOVER,
                      command=lambda: self._refresh_models(provider),
                      ).pack(side="left")

    def _build_key_model(self, key_key, model_key, key_ph, provider=None):
        f = ctk.CTkFrame(self.fields_holder, fg_color="transparent")
        self._label(f, "Clé API")
        self._entry(f, key_key, 210, key_ph, secret=True)
        self._label(f, "Modèle")
        self._model_menu(f, provider or model_key.rsplit("_", 1)[0])
        self._refresh_btn(f, provider or model_key.rsplit("_", 1)[0])
        return f

    def _build_openai(self):
        f = ctk.CTkFrame(self.fields_holder, fg_color="transparent")
        self._label(f, "Clé API")
        self._entry(f, "openai_api_key", 170, "sk-…", secret=True)
        self._label(f, "Base")
        self._entry(f, "openai_base", 175)
        self._label(f, "Modèle")
        self._model_menu(f, "openai")
        self._refresh_btn(f, "openai")
        return f

    def _build_local(self, provider, url_key):
        f = ctk.CTkFrame(self.fields_holder, fg_color="transparent")
        self._label(f, "URL")
        self._entry(f, url_key, 195)
        self._model_menu(f, provider)
        self._refresh_btn(f, provider)
        return f

    def _build_custom(self):
        f = ctk.CTkFrame(self.fields_holder, fg_color="transparent")
        self._label(f, "Base")
        self._entry(f, "custom_base", 175, "https://…/v1")
        self._label(f, "Clé")
        self._entry(f, "custom_key", 110, secret=True)
        self._label(f, "Modèle")
        self._model_menu(f, "custom")
        self._refresh_btn(f, "custom")
        return f

    def _provider_changed(self, label):
        key = _LABEL_TO_PROVIDER.get(label, "gemini")
        self.settings["ai_provider"] = key
        save_settings(self.settings)
        for f in self.fields.values():
            f.pack_forget()
        self.fields[key].pack(side="left")
        self._refresh_models(key, silent=True)

    def _refresh_models(self, provider, silent=False):
        self._sync_settings()

        def work():
            models = providers.list_models(provider, self.settings)
            self.after(0, self._set_models, provider, models, silent)

        threading.Thread(target=work, daemon=True).start()

    def _set_models(self, provider, models, silent=False):
        menu = self._model_menus[provider]
        if models:
            current = menu.get().strip()
            menu.configure(values=models)
            if current not in models:
                menu.set(models[0])
        elif not silent:
            self._add_bubble(
                "step",
                f"{providers.PROVIDERS[provider]} : aucun modèle trouvé — "
                "clé API/URL correcte, service lancé ?")

    # ------------------------------------------------------------- serveurs

    def _server_names(self):
        names = [s["name"] for s in sm.list_servers()]
        return names or ["(aucun serveur)"]

    def _refresh_servers(self):
        names = self._server_names()
        self.server_menu.configure(values=names)
        self.server_menu.set(names[0])
        self._server_changed()

    def _server_changed(self):
        mod = get_moderator(self.server_menu.get())
        if mod and mod.enabled:
            self.auto_switch.select()
        else:
            self.auto_switch.deselect()

    def _toggle_autonomy(self):
        name = self.server_menu.get()
        if name == "(aucun serveur)":
            self.auto_switch.deselect()
            self._add_bubble(
                "assistant", "Sélectionnez d'abord un serveur (liste ci-dessus).")
            return
        if self.auto_switch.get():
            self._sync_settings()
            rules = self.rules_entry.get().strip() or \
                "Aucune insulte, aucun spam, respect entre joueurs."
            self.settings["auto_mod_rules"] = rules
            self.settings["auto_mod_enabled"] = True
            save_settings(self.settings)
            mod = AutonomousModerator(
                name, self.settings, rules,
                on_event=lambda t: self.after(
                    0, self._add_bubble, "step", f"🤖 {t}"))
            set_moderator(name, mod)
            self._add_bubble(
                "step",
                f"Modération autonome activée sur « {name} » — règles : {rules}")
        else:
            set_moderator(name, None)
            self.settings["auto_mod_enabled"] = False
            save_settings(self.settings)
            self._add_bubble("step", "Modération autonome désactivée.")

    def _get_agent(self):
        name = self.server_menu.get()
        if name == "(aucun serveur)":
            return None
        if name not in self._agents:
            self._sync_settings()
            self._agents[name] = Agent(name, self.settings)
        return self._agents[name]

    def _sync_settings(self):
        self.settings["ai_provider"] = _LABEL_TO_PROVIDER.get(
            self.provider_menu.get(), "gemini")
        for key, entry in self._entries.items():
            self.settings[key] = entry.get().strip()
        for provider, menu in self._model_menus.items():
            self.settings[f"{provider}_model"] = menu.get().strip()
        save_settings(self.settings)

    # ------------------------------------------------------------- chat

    def _add_bubble(self, role, text):
        if role == "step":
            ctk.CTkLabel(
                self.chat_frame, text=text, font=(theme.FONT, 11, "italic"),
                text_color=theme.ORANGE, anchor="w", justify="left",
            ).pack(fill="x", padx=14, pady=(0, 2))
        else:
            is_user = role == "user"
            bubble = ctk.CTkFrame(
                self.chat_frame,
                fg_color=theme.ACCENT if is_user else theme.PANEL_2,
                corner_radius=10)
            bubble.pack(fill="x", padx=14, pady=6,
                        anchor="e" if is_user else "w")
            ctk.CTkLabel(
                bubble, text=text, font=(theme.FONT, 13),
                text_color="#ffffff" if is_user else theme.TEXT,
                wraplength=820, justify="left", anchor="w",
            ).pack(padx=12, pady=8)
        self.after(50, lambda: self.chat_frame._parent_canvas.yview_moveto(1.0))

    _STEP_COLORS = {
        "file": theme.ACCENT, "mod": theme.GREEN, "del": theme.RED,
        "cmd": theme.ORANGE, "build": theme.ORANGE, "error": theme.RED,
        "search": theme.MUTED, "info": theme.MUTED,
    }

    def _add_step(self, ev):
        """Affiche une action de l'agent (fichier modifié, mod installé, …)."""
        self._step_count += 1
        row = ctk.CTkFrame(self.chat_frame, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(0, 2))
        color = self._STEP_COLORS.get(ev.get("kind"), theme.MUTED)
        ctk.CTkLabel(row, text=ev.get("icon", "⚙"), width=24,
                     font=(theme.FONT, 12)).pack(side="left")
        ctk.CTkLabel(
            row, text=ev.get("text", ""), font=(theme.FONT, 11),
            text_color=color, anchor="w", justify="left",
            wraplength=780).pack(side="left", fill="x", expand=True)
        self.after(50, lambda: self.chat_frame._parent_canvas.yview_moveto(1.0))

    def _quick_pick(self, value):
        if value != QUICK_PROMPTS[0]:
            self.input_entry.delete(0, "end")
            self.input_entry.insert(0, value)
        self.quick_menu.set(QUICK_PROMPTS[0])

    def _set_busy(self, busy):
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.send_btn.configure(state=state)
        self.analyze_btn.configure(state=state)
        if busy:
            self._busy_since = time.time()
            self._step_count = 0
            self._tick()
        else:
            self._busy_since = None
            self.activity_lbl.configure(text="")

    def _tick(self):
        if not self._busy:
            return
        elapsed = int(time.time() - self._busy_since)
        self.activity_lbl.configure(
            text=f"🤖 L'agent travaille — {elapsed} s · "
                 f"{self._step_count} action(s)")
        self.after(1000, self._tick)

    def _send(self):
        if self._busy:
            return
        msg = self.input_entry.get().strip()
        if not msg:
            return
        agent = self._get_agent()
        if not agent:
            self._add_bubble("assistant",
                             "Créez d'abord un serveur (onglet Créateur Rapide).")
            return
        self._sync_settings()
        agent.settings = self.settings
        self.input_entry.delete(0, "end")
        self._add_bubble("user", msg)
        self._set_busy(True)

        def work():
            try:
                reply = agent.run(
                    msg, on_step=lambda ev: self.after(0, self._add_step, ev))
            except providers.ProviderError as e:
                reply = f"⚠ {e}"
            except Exception as e:
                reply = f"⚠ Erreur inattendue : {e}"
            self.after(0, self._add_bubble, "assistant", reply)
            summary = agent.summary()
            if summary:
                self.after(0, self._add_bubble, "step", summary)
            self.after(0, self._set_busy, False)

        threading.Thread(target=work, daemon=True).start()

    def _analyze(self):
        if self._busy:
            return
        agent = self._get_agent()
        if not agent:
            self._add_bubble("assistant",
                             "Créez d'abord un serveur (onglet Créateur Rapide).")
            return
        self._sync_settings()
        agent.settings = self.settings
        self._add_bubble("step", "Analyse de logs/latest.log en cours…")
        self._set_busy(True)

        def work():
            try:
                reply = agent.analyze_logs(
                    on_step=lambda ev: self.after(0, self._add_step, ev))
            except providers.ProviderError as e:
                reply = f"⚠ {e}"
            except Exception as e:
                reply = f"⚠ Erreur inattendue : {e}"
            self.after(0, self._add_bubble, "assistant", reply)
            summary = agent.summary()
            if summary:
                self.after(0, self._add_bubble, "step", summary)
            self.after(0, self._set_busy, False)

        threading.Thread(target=work, daemon=True).start()
