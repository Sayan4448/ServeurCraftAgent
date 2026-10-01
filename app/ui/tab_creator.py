"""Onglet 'Créateur Rapide' : formulaire + téléchargement + intégrations."""
import threading
from tkinter import messagebox

import customtkinter as ctk

from ..config import curseforge_key
from ..core import downloader, mods as mods_mod, server_manager as sm
from ..i18n import t
from . import theme
from .playit_panel import PlayitPanel
from .tunnels_editor import TunnelsEditor
from .uithread import ui_call

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

        head = ctk.CTkFrame(form, fg_color="transparent")
        head.grid(row=0, column=0, columnspan=2, sticky="ew", padx=16,
                  pady=(14, 10))
        top = ctk.CTkFrame(head, fg_color="transparent")
        top.pack(fill="x")
        ctk.CTkLabel(top, text=t("cre_new"),
                     font=(theme.FONT, 16, "bold"),
                     text_color=theme.TEXT).pack(side="left")
        self.pack_btn = ctk.CTkButton(
            top, text=t("cre_from_pack"), height=30,
            fg_color="transparent", border_width=1,
            border_color=theme.ACCENT, text_color=theme.ACCENT,
            hover_color=theme.PANEL_2, command=self._pick_pack)
        self.pack_btn.pack(side="right")
        self._pack = None
        self.pack_bar = ctk.CTkFrame(head, fg_color=theme.PANEL_2,
                                     corner_radius=8)
        self.pack_lbl = ctk.CTkLabel(
            self.pack_bar, text="", font=(theme.FONT, 12, "bold"),
            text_color=theme.TEXT, anchor="w", justify="left",
            wraplength=420)
        self.pack_lbl.pack(side="left", fill="x", expand=True, padx=10,
                           pady=6)
        ctk.CTkButton(self.pack_bar, text="✕ " + t("cre_pack_clear"),
                      width=90, height=26, fg_color=theme.PANEL,
                      hover_color=theme.RED, text_color=theme.TEXT,
                      command=self._clear_pack).pack(side="right", padx=8)
        self.pack_hint = ctk.CTkLabel(
            head, text=t("cre_pack_hint"), font=(theme.FONT, 10),
            text_color=theme.MUTED, anchor="w", justify="left",
            wraplength=480)
        self.pack_hint.pack(fill="x", pady=(4, 0))

        def label(r, text):
            ctk.CTkLabel(form, text=text, text_color=theme.MUTED,
                         font=(theme.FONT, 12)).grid(
                row=r, column=0, sticky="w", padx=16, pady=6)

        entry_style = dict(fg_color=theme.PANEL_2, border_color=theme.BORDER,
                           text_color=theme.TEXT)

        label(1, t("cre_name"))
        self.name_entry = ctk.CTkEntry(form, placeholder_text="mon-serveur",
                                       **entry_style)
        self.name_entry.grid(row=1, column=1, sticky="ew", padx=16, pady=6)

        label(2, t("cre_type"))
        self.loader_menu = ctk.CTkOptionMenu(
            form, values=list(downloader.LOADER_LABELS.values()),
            fg_color=theme.PANEL_2, button_color=theme.ACCENT,
            button_hover_color=theme.ACCENT_HOVER, text_color=theme.TEXT,
            command=lambda _v: self._load_versions())
        self.loader_menu.grid(row=2, column=1, sticky="ew", padx=16, pady=6)

        label(3, t("cre_version"))
        self.version_menu = ctk.CTkOptionMenu(
            form, values=["…"], fg_color=theme.PANEL_2,
            button_color=theme.ACCENT, button_hover_color=theme.ACCENT_HOVER,
            text_color=theme.TEXT)
        self.version_menu.grid(row=3, column=1, sticky="ew", padx=16, pady=6)

        label(4, t("cre_port"))
        self.port_entry = ctk.CTkEntry(form, **entry_style)
        self.port_entry.insert(0, "25565")
        self.port_entry.grid(row=4, column=1, sticky="ew", padx=16, pady=6)

        label(5, t("cre_ram"))
        rambox = ctk.CTkFrame(form, fg_color="transparent")
        rambox.grid(row=5, column=1, sticky="ew", padx=16, pady=6)
        self.ram_entry = ctk.CTkEntry(rambox, width=90, **entry_style)
        self.ram_entry.insert(0, "4")
        self.ram_entry.pack(side="left")
        ctk.CTkLabel(rambox, text="Go", text_color=theme.MUTED).pack(
            side="left", padx=6)

        label(6, t("cre_accounts"))
        accbox = ctk.CTkFrame(form, fg_color="transparent")
        accbox.grid(row=6, column=1, sticky="ew", padx=16, pady=6)
        self.accounts_seg = ctk.CTkSegmentedButton(
            accbox, values=[t("acc_crack"), t("acc_premium"), t("acc_both")],
            **theme.SEG)
        self.accounts_seg.set(t("acc_both"))
        self.accounts_seg.pack(anchor="w")
        self.crossplay_check = ctk.CTkCheckBox(
            accbox, text=t("cp_switch"), text_color=theme.TEXT,
            fg_color=theme.GREEN, hover_color=theme.GREEN_HOVER)
        self.crossplay_check.pack(anchor="w", pady=(8, 0))
        ctk.CTkLabel(accbox, text=t("cp_hint_short"), font=(theme.FONT, 10),
                     text_color=theme.MUTED, justify="left",
                     wraplength=380).pack(anchor="w")

        # ------------------------------------------------------ gameplay
        sep1 = ctk.CTkFrame(form, height=1, fg_color=theme.BORDER)
        sep1.grid(row=7, column=0, columnspan=2, sticky="ew", padx=16, pady=10)

        label(8, t("ss_gameplay"))
        gbox = ctk.CTkFrame(form, fg_color="transparent")
        gbox.grid(row=8, column=1, sticky="w", padx=16, pady=6)
        self.pvp_switch = ctk.CTkSwitch(gbox, text=t("ss_pvp"),
                                        text_color=theme.TEXT,
                                        progress_color=theme.ACCENT)
        self.pvp_switch.select()
        self.pvp_switch.pack(side="left", padx=(0, 16))
        self.monsters_switch = ctk.CTkSwitch(gbox, text=t("ss_monsters"),
                                             text_color=theme.TEXT,
                                             progress_color=theme.ACCENT)
        self.monsters_switch.select()
        self.monsters_switch.pack(side="left")

        label(9, "Voice Chat")
        voicebox = ctk.CTkFrame(form, fg_color="transparent")
        voicebox.grid(row=9, column=1, sticky="ew", padx=16, pady=6)
        self.voice_check = ctk.CTkCheckBox(
            voicebox, text=t("cre_install"), text_color=theme.TEXT,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER)
        self.voice_check.pack(side="left")
        self.voice_choice = ctk.CTkSegmentedButton(
            voicebox, values=["Simple Voice Chat", "Plasmo Voice"],
            **theme.SEG)
        self.voice_choice.set("Simple Voice Chat")
        self.voice_choice.pack(side="left", padx=10)

        # --------------------------------------------------------- playit
        sep2 = ctk.CTkFrame(form, height=1, fg_color=theme.BORDER)
        sep2.grid(row=10, column=0, columnspan=2, sticky="ew", padx=16,
                  pady=10)

        label(11, "Playit.gg")
        self.playit_check = ctk.CTkCheckBox(
            form, text=t("cre_playit"),
            text_color=theme.TEXT, fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER, command=self._toggle_playit)
        self.playit_check.grid(row=11, column=1, sticky="w", padx=16, pady=6)

        self.playit_frame = ctk.CTkFrame(form, fg_color=theme.PANEL_2,
                                         corner_radius=8)
        self.playit_frame.grid(row=12, column=0, columnspan=2, sticky="ew",
                               padx=16, pady=(0, 10))
        self.playit_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.playit_frame, text=t("pl_cre_hint"),
                     font=(theme.FONT, 11, "bold"), text_color=theme.ACCENT,
                     anchor="w", justify="left", wraplength=560).grid(
            row=0, column=0, sticky="w", padx=12, pady=(10, 0))
        self.tunnels_editor = TunnelsEditor(self.playit_frame)
        self.tunnels_editor.grid(row=1, column=0, sticky="ew", padx=10,
                                 pady=10)
        self.playit_frame.grid_remove()

        self.create_btn = ctk.CTkButton(
            form, text=t("cre_create"), height=42, corner_radius=10,
            font=(theme.FONT, 14, "bold"), fg_color=theme.GREEN,
            hover_color=theme.GREEN_HOVER, text_color=theme.ON_GREEN,
            command=self._create)
        self.create_btn.grid(row=13, column=0, columnspan=2, sticky="ew",
                             padx=16, pady=(8, 16))

        # ------------------------------------------------------------- droite
        right = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=10)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_rowconfigure(2, weight=1)
        right.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(right, text=t("cre_progress"), font=(theme.FONT, 14, "bold"),
                     text_color=theme.TEXT).grid(
            row=0, column=0, sticky="w", padx=14, pady=(14, 4))
        self.progress = ctk.CTkProgressBar(right, progress_color=theme.ACCENT)
        self.progress.set(0)
        self.progress.grid(row=1, column=0, sticky="ew", padx=14, pady=4)
        self.logbox = ctk.CTkTextbox(
            right, font=(theme.FONT_MONO, 11), fg_color=theme.CONSOLE_BG,
            text_color=theme.CONSOLE_TEXT, state="disabled", wrap="word")
        self.logbox.grid(row=2, column=0, sticky="nsew", padx=14, pady=(4, 14))
        self.log_hint = ctk.CTkLabel(
            right, text=t("cre_log_hint"), font=(theme.FONT, 11),
            text_color=theme.MUTED, fg_color=theme.CONSOLE_BG,
            wraplength=300, justify="center")
        self.log_hint.place(in_=self.logbox, relx=0.5, rely=0.5,
                            anchor="center")

        self._load_versions()

    # ----------------------------------------------------------------- helpers

    def _toggle_playit(self):
        if self.playit_check.get():
            self.playit_frame.grid()
        else:
            self.playit_frame.grid_remove()

    def _log(self, text):
        ui_call(self, self._append_log, text)

    def _append_log(self, text):
        self.log_hint.place_forget()
        self.logbox.configure(state="normal")
        self.logbox.insert("end", text + "\n")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def _load_versions(self):
        loader = _LABEL_TO_LOADER[self.loader_menu.get()]
        if loader in self._versions_cache:
            self._set_versions(self._versions_cache[loader])
            return
        self.version_menu.configure(values=[t("loading")])
        self.version_menu.set(t("loading"))

        def work():
            try:
                versions = downloader.get_versions(loader)
            except Exception as e:  # noqa: BLE001
                self._log(f"Erreur versions {loader} : "
                          f"{mods_mod.explain(e)}")
                versions = []
            if versions:              # un échec réseau n'est pas mémorisé
                self._versions_cache[loader] = versions
            ui_call(self, self._set_versions, versions, loader)

        threading.Thread(target=work, daemon=True).start()

    def _set_versions(self, versions, loader=None):
        # Réponse d'un type de serveur qui n'est plus celui affiché (on a
        # changé de type pendant le chargement) : elle écraserait la liste
        # avec des versions qui n'existent pas pour le type choisi.
        if loader and loader != _LABEL_TO_LOADER[self.loader_menu.get()]:
            return
        if not versions:
            versions = [t("none_f")]
        self.version_menu.configure(values=versions)
        self.version_menu.set(versions[0])
        if self._pack and self._pack.get("mc_version"):
            self.version_menu.set(self._pack["mc_version"])

    # ----------------------------------------------------------------- modpack

    def _pick_pack(self):
        if self._creating:
            return
        from .mods_manager import pick_modpack
        path = pick_modpack(self.winfo_toplevel())
        if not path:
            return
        self.pack_btn.configure(state="disabled", text=t("cre_pack_reading"))

        def work():                   # thread : lecture du zip
            from ..core import modpack
            try:
                ui_call(self, self._pack_loaded, modpack.read_pack(path), None)
            except Exception as e:  # noqa: BLE001
                ui_call(self, self._pack_loaded, None, e)
        threading.Thread(target=work, daemon=True).start()

    def _pack_loaded(self, pack, err):
        self.pack_btn.configure(state="normal", text=t("cre_from_pack"))
        if err:
            messagebox.showerror("Modpack", t("cre_pack_err", e=err),
                                 parent=self.winfo_toplevel())
            return
        if pack["format"] == "curseforge" and not curseforge_key():
            messagebox.showwarning("Modpack", t("cre_pack_need_cf"),
                                   parent=self.winfo_toplevel())
            return
        self._pack = pack
        loader, mc = pack.get("loader"), pack.get("mc_version")
        if loader in downloader.LOADER_LABELS:
            self.loader_menu.set(downloader.LOADER_LABELS[loader])
            self._load_versions()
        if mc:
            self.version_menu.set(mc)
        locked = bool(loader and mc)
        for w in (self.loader_menu, self.version_menu):
            w.configure(state="disabled" if locked else "normal")
        if not self.name_entry.get().strip():
            self.name_entry.insert(0, sm._slug(pack.get("name") or "modpack"))
        if self.ram_entry.get().strip() == "4":
            self.ram_entry.delete(0, "end")
            self.ram_entry.insert(0, "6")
        parts = [pack.get("name") or "modpack"]
        if loader:
            parts.append(downloader.LOADER_LABELS.get(loader, loader)
                         .split(" (")[0] + (f" {pack['loader_version']}"
                                            if pack.get("loader_version")
                                            else ""))
        if mc:
            parts.append(f"MC {mc}")
        self.pack_lbl.configure(text="📦 " + "  ·  ".join(parts))
        self.pack_hint.configure(text=t("cre_pack_ready") if locked
                                 else t("cre_pack_noinfo"))
        self.pack_bar.pack(fill="x", pady=(8, 0), before=self.pack_hint)

    def _clear_pack(self):
        self._pack = None
        self.pack_bar.pack_forget()
        self.pack_hint.configure(text=t("cre_pack_hint"))
        for w in (self.loader_menu, self.version_menu):
            w.configure(state="normal")
        self._load_versions()

    # ----------------------------------------------------------------- création

    def _create(self):
        if self._creating:
            return
        name = self.name_entry.get().strip()
        if not name:
            messagebox.showwarning(t("cre_missing_name_t"),
                                   t("cre_missing_name"))
            return
        version = self.version_menu.get()
        if version in (t("loading"), t("none_f")):
            messagebox.showwarning(t("cre_bad_version_t"),
                                   t("cre_bad_version"))
            return
        try:
            port = int(self.port_entry.get())
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            messagebox.showwarning(t("cre_bad_port_t"), t("cre_bad_port"))
            return

        voice = "none"
        if self.voice_check.get():
            voice = ("simple_voice_chat" if self.voice_choice.get()
                     == "Simple Voice Chat" else "plasmo_voice")

        tunnels = []
        playit_auto = False
        if self.playit_check.get():
            tunnels = self.tunnels_editor.get()
            playit_auto = not tunnels

        try:
            ram_mb = int(float(self.ram_entry.get().replace(",", ".")) * 1024)
            if ram_mb < 256:
                raise ValueError
        except ValueError:
            messagebox.showwarning(t("cre_ram"), t("cre_bad_ram"))
            return

        acc_label = self.accounts_seg.get()
        accounts = ("premium" if acc_label == t("acc_premium")
                    else "crack" if acc_label == t("acc_crack") else "both")

        options = {
            "name": name,
            "loader": _LABEL_TO_LOADER[self.loader_menu.get()],
            "mc_version": version,
            "ram_mb": ram_mb,
            "port": port,
            "online_mode": accounts == "premium",
            "accounts": accounts,
            "crossplay": bool(self.crossplay_check.get()),
            "props": {
                "pvp": "true" if self.pvp_switch.get() else "false",
                "spawn-monsters": ("true" if self.monsters_switch.get()
                                   else "false"),
            },
            "voice": voice,
            "tunnels": tunnels,
            "playit_auto": playit_auto,
        }
        if self._pack:
            options.update(modpack=self._pack,
                           loader_version=self._pack.get("loader_version"),
                           cf_key=curseforge_key())

        self._creating = True
        self.create_btn.configure(state="disabled", text=t("cre_creating"))
        self.progress.set(0)
        self._append_log(t("cre_log_start", name=name))

        def work():
            try:
                meta = sm.create_server(
                    options,
                    progress_cb=lambda f: ui_call(self, self.progress.set, f),
                    log=self._log,
                )
                ui_call(self, self._create_done, meta)
            except Exception as e:  # noqa: BLE001
                self._log(f"✖ Erreur : {mods_mod.explain(e)}")
                ui_call(self, self._create_failed)

        threading.Thread(target=work, daemon=True).start()

    def _create_done(self, meta):
        self._creating = False
        self.create_btn.configure(state="normal", text=t("cre_create"))
        self.progress.set(1)
        if self._pack:
            self._clear_pack()
        if self.on_created:
            self.on_created(meta)
        if meta.get("playit_auto"):
            PlayitPanel.show(self, sm.get_process(meta["name"]))
        if meta.get("summary"):
            SummaryDialog(self.winfo_toplevel(), meta["summary"])
        else:
            messagebox.showinfo(t("cre_done"),
                                t("cre_done_msg", name=meta["name"]))

    def _create_failed(self):
        self._creating = False
        self.create_btn.configure(state="normal", text=t("cre_create"))


class SummaryDialog(ctk.CTkToplevel):
    """Fenêtre récapitulative Playit avec bouton copier."""

    def __init__(self, master, text):
        super().__init__(master)
        self.title(t("summary_title"))
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
            self, text=t("copy_clip"),
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            command=lambda: self._copy(text)).pack(pady=(0, 14))

    def _copy(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)
