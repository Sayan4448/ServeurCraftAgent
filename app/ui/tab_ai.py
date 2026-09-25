"""Onglet 'Agent IA & Outils' : chat, analyse de logs, prompts rapides."""
import threading

import customtkinter as ctk

from ..ai.agent import Agent
from ..ai import providers
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


class AiTab(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master, fg_color="transparent")
        self.settings = load_settings()
        self._agents = {}
        self._busy = False

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ------------------------------------------------------------- config
        cfg = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=10)
        cfg.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        cfg.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(cfg, text="Provider", text_color=theme.MUTED,
                     font=(theme.FONT, 12)).grid(
            row=0, column=0, padx=(14, 6), pady=10, sticky="w")
        self.provider_seg = ctk.CTkSegmentedButton(
            cfg, values=["Gemini API", "Ollama local"],
            selected_color=theme.ACCENT,
            selected_hover_color=theme.ACCENT_HOVER,
            unselected_color=theme.PANEL_2,
            unselected_hover_color=theme.HOVER,
            command=self._provider_changed)
        self.provider_seg.set(
            "Ollama local" if self.settings["ai_provider"] == "ollama"
            else "Gemini API")
        self.provider_seg.grid(row=0, column=1, padx=6, pady=10, sticky="w")

        # panneau Gemini
        self.gemini_box = ctk.CTkFrame(cfg, fg_color="transparent")
        ctk.CTkLabel(self.gemini_box, text="Clé API", text_color=theme.MUTED,
                     font=(theme.FONT, 12)).pack(side="left", padx=(0, 6))
        self.key_entry = ctk.CTkEntry(
            self.gemini_box, width=220, show="•",
            placeholder_text="AIza…",
            fg_color=theme.PANEL_2, border_color=theme.BORDER,
            text_color=theme.TEXT)
        self.key_entry.insert(0, self.settings.get("gemini_api_key", ""))
        self.key_entry.pack(side="left", padx=4)
        ctk.CTkLabel(self.gemini_box, text="Modèle", text_color=theme.MUTED,
                     font=(theme.FONT, 12)).pack(side="left", padx=(10, 6))
        self.gmodel_entry = ctk.CTkEntry(
            self.gemini_box, width=150, fg_color=theme.PANEL_2,
            border_color=theme.BORDER, text_color=theme.TEXT)
        self.gmodel_entry.insert(0, self.settings.get("gemini_model", ""))
        self.gmodel_entry.pack(side="left", padx=4)

        # panneau Ollama
        self.ollama_box = ctk.CTkFrame(cfg, fg_color="transparent")
        ctk.CTkLabel(self.ollama_box, text="URL", text_color=theme.MUTED,
                     font=(theme.FONT, 12)).pack(side="left", padx=(0, 6))
        self.ourl_entry = ctk.CTkEntry(
            self.ollama_box, width=190, fg_color=theme.PANEL_2,
            border_color=theme.BORDER, text_color=theme.TEXT)
        self.ourl_entry.insert(0, self.settings.get("ollama_url", ""))
        self.ourl_entry.pack(side="left", padx=4)
        self.omodel_menu = ctk.CTkOptionMenu(
            self.ollama_box, width=170,
            values=[self.settings.get("ollama_model", "llama3.1")],
            fg_color=theme.PANEL_2, button_color=theme.ACCENT,
            button_hover_color=theme.ACCENT_HOVER, text_color=theme.TEXT)
        self.omodel_menu.set(self.settings.get("ollama_model", "llama3.1"))
        self.omodel_menu.pack(side="left", padx=4)
        ctk.CTkButton(self.ollama_box, text="⟳", width=32,
                      fg_color=theme.PANEL_2, hover_color=theme.HOVER,
                      command=self._refresh_ollama_models).pack(side="left")

        # serveur cible
        ctk.CTkLabel(cfg, text="Serveur", text_color=theme.MUTED,
                     font=(theme.FONT, 12)).grid(row=0, column=3, padx=(16, 6))
        self.server_menu = ctk.CTkOptionMenu(
            cfg, width=160, values=self._server_names(),
            fg_color=theme.PANEL_2, button_color=theme.ACCENT,
            button_hover_color=theme.ACCENT_HOVER, text_color=theme.TEXT,
            command=lambda _v: None)
        self.server_menu.grid(row=0, column=4, padx=(0, 6), pady=10)
        ctk.CTkButton(cfg, text="⟳", width=32, fg_color=theme.PANEL_2,
                      hover_color=theme.HOVER,
                      command=self._refresh_servers).grid(
            row=0, column=5, padx=(0, 12))

        self._provider_changed(self.provider_seg.get())

        # ------------------------------------------------------------- chat
        self.chat_frame = ctk.CTkScrollableFrame(self, fg_color=theme.PANEL,
                                               corner_radius=10)
        self.chat_frame.grid(row=1, column=0, sticky="nsew")

        # ------------------------------------------------------------- saisie
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        bottom.grid_columnconfigure(1, weight=1)

        self.quick_menu = ctk.CTkOptionMenu(
            bottom, width=210, values=QUICK_PROMPTS,
            fg_color=theme.PANEL_2, button_color=theme.ACCENT,
            button_hover_color=theme.ACCENT_HOVER, text_color=theme.TEXT,
            command=self._quick_pick)
        self.quick_menu.grid(row=0, column=0, padx=(0, 8))

        self.input_entry = ctk.CTkEntry(
            bottom, placeholder_text="Demandez à l'agent (ex: analyse les logs et corrige la config)…",
            fg_color=theme.PANEL, border_color=theme.BORDER,
            text_color=theme.TEXT, height=36)
        self.input_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        self.input_entry.bind("<Return>", lambda e: self._send())

        self.analyze_btn = ctk.CTkButton(
            bottom, text="🔍 Analyser les logs", width=150, height=36,
            fg_color=theme.PANEL_2, hover_color=theme.HOVER,
            command=self._analyze)
        self.analyze_btn.grid(row=0, column=2, padx=(0, 8))
        self.send_btn = ctk.CTkButton(
            bottom, text="Envoyer", width=100, height=36,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            command=self._send)
        self.send_btn.grid(row=0, column=3)

        self._add_bubble(
            "assistant",
            "Bonjour ! Je suis l'agent ServerCraft. Sélectionnez un serveur "
            "ci-dessus : je peux lire ses logs, modifier ses fichiers de "
            "configuration et corriger les erreurs pour vous.")

    # ------------------------------------------------------------- providers

    def _provider_changed(self, value):
        self.settings["ai_provider"] = "ollama" if value == "Ollama local" else "gemini"
        save_settings(self.settings)
        self.gemini_box.grid_forget()
        self.ollama_box.grid_forget()
        box = self.gemini_box if value == "Gemini API" else self.ollama_box
        box.grid(row=0, column=2, padx=6, pady=10, sticky="w")

    def _refresh_ollama_models(self):
        base = self.ourl_entry.get().strip() or "http://localhost:11434"
        self.settings["ollama_url"] = base

        def work():
            models = providers.list_ollama_models(base)
            self.after(0, lambda: self._set_ollama_models(models))

        threading.Thread(target=work, daemon=True).start()

    def _set_ollama_models(self, models):
        if not models:
            models = ["llama3.1"]
            self._add_bubble("step",
                             "Ollama injoignable — vérifiez que le serveur "
                             "tourne (ollama serve).")
        self.omodel_menu.configure(values=models)
        self.omodel_menu.set(models[0])

    # ------------------------------------------------------------- serveurs

    def _server_names(self):
        names = [s["name"] for s in sm.list_servers()]
        return names or ["(aucun serveur)"]

    def _refresh_servers(self):
        names = self._server_names()
        self.server_menu.configure(values=names)
        self.server_menu.set(names[0])

    def _get_agent(self):
        name = self.server_menu.get()
        if name == "(aucun serveur)":
            return None
        if name not in self._agents:
            self._sync_settings()
            self._agents[name] = Agent(name, self.settings)
        return self._agents[name]

    def _sync_settings(self):
        self.settings["ai_provider"] = (
            "ollama" if self.provider_seg.get() == "Ollama local" else "gemini")
        self.settings["gemini_api_key"] = self.key_entry.get().strip()
        self.settings["gemini_model"] = self.gmodel_entry.get().strip()
        self.settings["ollama_url"] = self.ourl_entry.get().strip()
        self.settings["ollama_model"] = self.omodel_menu.get().strip()
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
                    msg, on_step=lambda s: self.after(0, self._add_bubble, "step", s))
            except providers.ProviderError as e:
                reply = f"⚠ {e}"
            except Exception as e:
                reply = f"⚠ Erreur inattendue : {e}"
            self.after(0, self._add_bubble, "assistant", reply)
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
                    on_step=lambda s: self.after(0, self._add_bubble, "step", s))
            except providers.ProviderError as e:
                reply = f"⚠ {e}"
            except Exception as e:
                reply = f"⚠ Erreur inattendue : {e}"
            self.after(0, self._add_bubble, "assistant", reply)
            self.after(0, self._set_busy, False)

        threading.Thread(target=work, daemon=True).start()
