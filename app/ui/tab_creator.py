"""Onglet 'Créateur Rapide' : formulaire + téléchargement + intégrations."""
import threading
from tkinter import messagebox

import customtkinter as ctk

from ..core import downloader, mods as mods_mod, server_manager as sm
from . import theme

_LABEL_TO_LOADER = {v: k for k, v in downloader.LOADER_LABELS.items()}


class CreatorTab(ctk.CTkFrame):
    def __init__(self, master, on_created=None):
        super().__init__(master, fg_color="transparent")
        self.on_created = on_created
        self._versions_cache = {}
        self._creating = False

        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(0, weight=1)

        # ------------------------------------------------------------- form
        form = ctk.CTkScrollableFrame(self, fg_color=theme.PANEL, corner_radius=10)
        form.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        form.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(form, text="Nouveau serveur",
                     font=(theme.FONT, 16, "bold"),
                     text_color=theme.TEXT).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(14, 10))

        def label(r, text):
            ctk.CTkLabel(form, text=text, text_color=theme.MUTED,
                         font=(theme.FONT, 12)).grid(
                row=r, column=0, sticky="w", padx=16, pady=6)

        entry_style = dict(fg_color=theme.PANEL_2, border_color=theme.BORDER,
                           text_color=theme.TEXT)

        label(1, "Nom du serveur")
        self.name_entry = ctk.CTkEntry(form, placeholder_text="mon-serveur",
                                       **entry_style)
        self.name_entry.grid(row=1, column=1, sticky="ew", padx=16, pady=6)

        label(2, "Type de serveur")
        self.loader_menu = ctk.CTkOptionMenu(
            form, values=list(downloader.LOADER_LABELS.values()),
            fg_color=theme.PANEL_2, button_color=theme.ACCENT,
            button_hover_color=theme.ACCENT_HOVER, text_color=theme.TEXT,
            command=lambda _v: self._load_versions())
        self.loader_menu.grid(row=2, column=1, sticky="ew", padx=16, pady=6)

        label(3, "Version de Minecraft")
        self.version_menu = ctk.CTkOptionMenu(
            form, values=["…"], fg_color=theme.PANEL_2,
            button_color=theme.ACCENT, button_hover_color=theme.ACCENT_HOVER,
            text_color=theme.TEXT)
        self.version_menu.grid(row=3, column=1, sticky="ew", padx=16, pady=6)

        label(4, "Port")
        self.port_entry = ctk.CTkEntry(form, **entry_style)
        self.port_entry.insert(0, "25565")
        self.port_entry.grid(row=4, column=1, sticky="ew", padx=16, pady=6)

        label(5, "RAM allouée")
        rambox = ctk.CTkFrame(form, fg_color="transparent")
        rambox.grid(row=5, column=1, sticky="ew", padx=16, pady=6)
        rambox.grid_columnconfigure(0, weight=1)
        self.ram_slider = ctk.CTkSlider(
            rambox, from_=1024, to=16384, number_of_steps=30,
            progress_color=theme.ACCENT, button_color=theme.ACCENT,
            command=self._ram_changed)
        self.ram_slider.set(4096)
        self.ram_slider.grid(row=0, column=0, sticky="ew")
        self.ram_label = ctk.CTkLabel(rambox, text="4 Go", width=60,
                                    text_color=theme.TEXT)
        self.ram_label.grid(row=0, column=1, padx=(10, 0))

        label(6, "Comptes requis")
        self.online_switch = ctk.CTkSwitch(
            form, text="online-mode (comptes premium uniquement)",
            text_color=theme.TEXT, progress_color=theme.ACCENT)
        self.online_switch.grid(row=6, column=1, sticky="w", padx=16, pady=6)

        # ------------------------------------------------------ voice chat
        sep1 = ctk.CTkFrame(form, height=1, fg_color=theme.BORDER)
        sep1.grid(row=7, column=0, columnspan=2, sticky="ew", padx=16, pady=10)

        label(8, "Voice Chat")
        voicebox = ctk.CTkFrame(form, fg_color="transparent")
        voicebox.grid(row=8, column=1, sticky="ew", padx=16, pady=6)
        self.voice_check = ctk.CTkCheckBox(
            voicebox, text="Installer", text_color=theme.TEXT,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER)
        self.voice_check.pack(side="left")
        self.voice_choice = ctk.CTkSegmentedButton(
            voicebox, values=["Simple Voice Chat", "Plasmo Voice"],
            selected_color=theme.ACCENT,
            selected_hover_color=theme.ACCENT_HOVER,
            unselected_color=theme.PANEL_2,
            unselected_hover_color=theme.HOVER)
        self.voice_choice.set("Simple Voice Chat")
        self.voice_choice.pack(side="left", padx=10)

        # --------------------------------------------------------- playit
        sep2 = ctk.CTkFrame(form, height=1, fg_color=theme.BORDER)
        sep2.grid(row=9, column=0, columnspan=2, sticky="ew", padx=16, pady=10)

        label(10, "Playit.gg")
        self.playit_check = ctk.CTkCheckBox(
            form, text="Configurer un tunnel playit.gg",
            text_color=theme.TEXT, fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER, command=self._toggle_playit)
        self.playit_check.grid(row=10, column=1, sticky="w", padx=16, pady=6)

        self.playit_frame = ctk.CTkFrame(form, fg_color=theme.PANEL_2,
                                         corner_radius=8)
        self.playit_frame.grid(row=11, column=0, columnspan=2, sticky="ew",
                               padx=16, pady=(0, 10))
        self.playit_frame.grid_columnconfigure(1, weight=1)
        for i, (lab, default, ph) in enumerate((
                ("Adresse du tunnel", "", "ex: ab12.gl.joinmc.link"),
                ("Port TCP public", "25565", "port Minecraft"),
                ("Port UDP public", "24454", "port Voice Chat"))):
            ctk.CTkLabel(self.playit_frame, text=lab, text_color=theme.MUTED,
                         font=(theme.FONT, 11)).grid(
                row=i, column=0, sticky="w", padx=12, pady=4)
            e = ctk.CTkEntry(self.playit_frame, placeholder_text=ph,
                             **entry_style)
            if default:
                e.insert(0, default)
            e.grid(row=i, column=1, sticky="ew", padx=12, pady=4)
            setattr(self, f"playit_{['addr', 'tcp', 'udp'][i]}", e)
        self.playit_frame.grid_remove()

        self.create_btn = ctk.CTkButton(
            form, text="⚒  Créer le serveur", height=42,
            font=(theme.FONT, 14, "bold"), fg_color=theme.GREEN,
            hover_color="#16a34a", text_color="#06210f",
            command=self._create)
        self.create_btn.grid(row=12, column=0, columnspan=2, sticky="ew",
                             padx=16, pady=(8, 16))

        # ------------------------------------------------------------- droite
        right = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=10)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_rowconfigure(2, weight=1)
        right.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(right, text="Progression", font=(theme.FONT, 14, "bold"),
                     text_color=theme.TEXT).grid(
            row=0, column=0, sticky="w", padx=14, pady=(14, 4))
        self.progress = ctk.CTkProgressBar(right, progress_color=theme.ACCENT)
        self.progress.set(0)
        self.progress.grid(row=1, column=0, sticky="ew", padx=14, pady=4)
        self.logbox = ctk.CTkTextbox(
            right, font=(theme.FONT_MONO, 11), fg_color="#0a0d12",
            text_color="#c9d1d9", state="disabled", wrap="word")
        self.logbox.grid(row=2, column=0, sticky="nsew", padx=14, pady=(4, 14))

        self._load_versions()

    # ----------------------------------------------------------------- helpers

    def _ram_changed(self, v):
        mb = int(v)
        self.ram_label.configure(
            text=f"{mb // 1024} Go" if mb % 1024 == 0 else f"{mb} Mo")

    def _toggle_playit(self):
        if self.playit_check.get():
            self.playit_frame.grid()
        else:
            self.playit_frame.grid_remove()

    def _log(self, text):
        self.after(0, self._append_log, text)

    def _append_log(self, text):
        self.logbox.configure(state="normal")
        self.logbox.insert("end", text + "\n")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def _load_versions(self):
        loader = _LABEL_TO_LOADER[self.loader_menu.get()]
        if loader in self._versions_cache:
            self._set_versions(self._versions_cache[loader])
            return
        self.version_menu.configure(values=["Chargement…"])
        self.version_menu.set("Chargement…")

        def work():
            try:
                versions = downloader.get_versions(loader)
            except Exception as e:
                self._log(f"Erreur versions {loader} : {e}")
                versions = []
            self._versions_cache[loader] = versions
            self.after(0, self._set_versions, versions)

        threading.Thread(target=work, daemon=True).start()

    def _set_versions(self, versions):
        if not versions:
            versions = ["Aucune"]
        self.version_menu.configure(values=versions)
        self.version_menu.set(versions[0])

    # ----------------------------------------------------------------- création

    def _create(self):
        if self._creating:
            return
        name = self.name_entry.get().strip()
        if not name:
            messagebox.showwarning("Nom manquant", "Donnez un nom au serveur.")
            return
        version = self.version_menu.get()
        if version in ("Chargement…", "Aucune"):
            messagebox.showwarning("Version", "Choisissez une version valide.")
            return
        try:
            port = int(self.port_entry.get())
        except ValueError:
            messagebox.showwarning("Port", "Port invalide.")
            return

        voice = "none"
        if self.voice_check.get():
            voice = ("simple_voice_chat" if self.voice_choice.get()
                     == "Simple Voice Chat" else "plasmo_voice")

        playit = {}
        if self.playit_check.get():
            addr = self.playit_addr.get().strip()
            if not addr:
                messagebox.showwarning("Playit", "Entrez l'adresse du tunnel playit.")
                return
            playit = {
                "address": addr,
                "tcp_port": self.playit_tcp.get().strip() or "25565",
                "udp_port": self.playit_udp.get().strip() or "0",
            }

        options = {
            "name": name,
            "loader": _LABEL_TO_LOADER[self.loader_menu.get()],
            "mc_version": version,
            "ram_mb": int(self.ram_slider.get()),
            "port": port,
            "online_mode": bool(self.online_switch.get()),
            "voice": voice,
            "playit": playit,
        }

        self._creating = True
        self.create_btn.configure(state="disabled", text="Création en cours…")
        self.progress.set(0)
        self._append_log(f"══ Création de « {name} » ══")

        def work():
            try:
                meta = sm.create_server(
                    options,
                    progress_cb=lambda f: self.after(0, self.progress.set, f),
                    log=self._log,
                )
                self.after(0, self._create_done, meta)
            except Exception as e:
                self._log(f"✖ Erreur : {e}")
                self.after(0, self._create_failed)

        threading.Thread(target=work, daemon=True).start()

    def _create_done(self, meta):
        self._creating = False
        self.create_btn.configure(state="normal", text="⚒  Créer le serveur")
        self.progress.set(1)
        if self.on_created:
            self.on_created(meta)
        if meta.get("summary"):
            SummaryDialog(self.winfo_toplevel(), meta["summary"])
        else:
            messagebox.showinfo("Terminé", f"Serveur « {meta['name']} » créé !")

    def _create_failed(self):
        self._creating = False
        self.create_btn.configure(state="normal", text="⚒  Créer le serveur")


class SummaryDialog(ctk.CTkToplevel):
    """Fenêtre récapitulative Playit avec bouton copier."""

    def __init__(self, master, text):
        super().__init__(master)
        self.title("Serveur créé — Récapitulatif")
        self.geometry("560x420")
        self.configure(fg_color=theme.BG)
        self.transient(master)
        self.grab_set()

        box = ctk.CTkTextbox(self, font=(theme.FONT_MONO, 12),
                             fg_color=theme.PANEL, text_color=theme.TEXT)
        box.pack(fill="both", expand=True, padx=14, pady=(14, 6))
        box.insert("1.0", text)
        box.configure(state="disabled")

        ctk.CTkButton(
            self, text="Copier dans le presse-papier",
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            command=lambda: self._copy(text)).pack(pady=(0, 14))

    def _copy(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)
