"""Fenêtre 'Mods & Plugins' : recherche Modrinth/CurseForge + install auto."""
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from ..config import load_settings, save_settings
from ..core import mods as mods_mod
from ..core.downloader import LOADER_LABELS
from . import theme

_FMT = lambda n: f"{n/1_000_000:.1f}M" if n >= 1_000_000 else (
    f"{n/1_000:.0f}k" if n >= 1_000 else str(n))


class ModsManager(ctk.CTkToplevel):
    def __init__(self, master, meta: dict):
        super().__init__(master)
        self.meta = meta
        self.server_dir = Path(meta["dir"])
        self.settings = load_settings()
        self._results = []
        self._busy = False

        loader_label = LOADER_LABELS.get(meta["loader"], meta["loader"])
        self.title(f"Mods & Plugins — {meta['name']} ({meta['mc_version']})")
        self.geometry("780x640")
        self.configure(fg_color=theme.BG)
        self.transient(master)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # ------------------------------------------------------------- haut
        top = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=10)
        top.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        ctk.CTkLabel(
            top, text=f"{meta['name']}  ·  {loader_label}  ·  MC {meta['mc_version']}",
            font=(theme.FONT, 13, "bold"), text_color=theme.TEXT,
        ).pack(side="left", padx=12, pady=10)

        # --------------------------------------------------------- contrôles
        ctrl = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=10)
        ctrl.grid(row=1, column=0, sticky="ew", padx=12, pady=6)

        self.source_seg = ctk.CTkSegmentedButton(
            ctrl, values=["Modrinth", "CurseForge"],
            selected_color=theme.ACCENT,
            selected_hover_color=theme.ACCENT_HOVER,
            unselected_color=theme.PANEL_2,
            unselected_hover_color=theme.HOVER,
            command=self._source_changed)
        self.source_seg.set("Modrinth")
        self.source_seg.pack(side="left", padx=10, pady=10)

        kinds = []
        if mods_mod.supports_mods(meta["loader"]):
            kinds.append("Mods")
        if mods_mod.supports_plugins(meta["loader"]):
            kinds.append("Plugins")
        self.kind_seg = ctk.CTkSegmentedButton(
            ctrl, values=kinds or ["Mods"],
            selected_color=theme.ACCENT,
            selected_hover_color=theme.ACCENT_HOVER,
            unselected_color=theme.PANEL_2,
            unselected_hover_color=theme.HOVER)
        self.kind_seg.set(
            "Plugins" if mods_mod.default_kind(meta["loader"]) == "plugin"
            else "Mods")
        self.kind_seg.pack(side="left", padx=6, pady=10)

        self.search_entry = ctk.CTkEntry(
            ctrl, placeholder_text="Rechercher (ex: voice chat, luckperms, jei)…",
            fg_color=theme.PANEL_2, border_color=theme.BORDER,
            text_color=theme.TEXT, width=220)
        self.search_entry.pack(side="left", padx=10)
        self.search_entry.bind("<Return>", lambda e: self._search())
        ctk.CTkButton(ctrl, text="Rechercher", width=100,
                      fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                      command=self._search).pack(side="left", padx=4, pady=10)

        # clé CurseForge (affichée seulement si source=CurseForge)
        self.cf_box = ctk.CTkFrame(ctrl, fg_color="transparent")
        ctk.CTkLabel(self.cf_box, text="Clé CurseForge",
                     text_color=theme.MUTED, font=(theme.FONT, 11),
                     ).pack(side="left", padx=(10, 4))
        self.cf_key = ctk.CTkEntry(
            self.cf_box, width=170, show="•", placeholder_text="x-api-key",
            fg_color=theme.PANEL_2, border_color=theme.BORDER,
            text_color=theme.TEXT)
        self.cf_key.insert(0, self.settings.get("curseforge_api_key", ""))
        self.cf_key.pack(side="left")

        # --------------------------------------------------------- contenu
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=2, column=0, sticky="nsew", padx=12, pady=6)
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(1, weight=3)
        body.grid_rowconfigure(3, weight=2)

        ctk.CTkLabel(body, text="Résultats", font=(theme.FONT, 13, "bold"),
                     text_color=theme.TEXT).grid(
            row=0, column=0, sticky="w", pady=(2, 4))
        self.results_frame = ctk.CTkScrollableFrame(body, fg_color=theme.PANEL,
                                                  corner_radius=10)
        self.results_frame.grid(row=1, column=0, sticky="nsew")

        ctk.CTkLabel(body, text="Installés sur ce serveur",
                     font=(theme.FONT, 13, "bold"),
                     text_color=theme.TEXT).grid(
            row=2, column=0, sticky="w", pady=(8, 4))
        self.installed_frame = ctk.CTkScrollableFrame(body, fg_color=theme.PANEL,
                                                    corner_radius=10)
        self.installed_frame.grid(row=3, column=0, sticky="nsew")

        self.status = ctk.CTkLabel(self, text="", text_color=theme.MUTED,
                                   font=(theme.FONT, 11))
        self.status.grid(row=3, column=0, sticky="w", padx=16, pady=(0, 8))

        self._refresh_installed()
        self._search()  # résultats populaires par défaut

    # ------------------------------------------------------------ helpers

    def _kind(self) -> str:
        return "plugin" if self.kind_seg.get() == "Plugins" else "mod"

    def _source_changed(self, _v):
        if self.source_seg.get() == "CurseForge":
            self.cf_box.pack(side="left", padx=4)
        else:
            self.cf_box.pack_forget()

    def _set_status(self, text):
        self.status.configure(text=text)

    # ------------------------------------------------------------ recherche

    def _search(self):
        if self._busy:
            return
        self._busy = True
        self._set_status("Recherche…")
        for w in self.results_frame.winfo_children():
            w.destroy()
        query = self.search_entry.get().strip()
        source = self.source_seg.get()
        kind = self._kind()
        api_key = self.cf_key.get().strip()

        def work():
            try:
                if source == "CurseForge":
                    res = mods_mod.search_curseforge(
                        query, self.meta["loader"], self.meta["mc_version"],
                        kind, api_key)
                else:
                    res = mods_mod.search_modrinth(
                        query, self.meta["loader"], self.meta["mc_version"],
                        kind)
                self.after(0, self._show_results, res)
            except Exception as e:
                self.after(0, self._set_status, f"Erreur : {e}")
            finally:
                self._busy = False

        threading.Thread(target=work, daemon=True).start()

    def _show_results(self, results):
        self._results = results
        self._set_status(f"{len(results)} résultat(s)")
        if not results:
            ctk.CTkLabel(self.results_frame, text="Aucun résultat.",
                         text_color=theme.MUTED).pack(pady=12)
            return
        for r in results:
            row = ctk.CTkFrame(self.results_frame, fg_color=theme.PANEL_2,
                               corner_radius=8)
            row.pack(fill="x", padx=4, pady=3)
            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", fill="x", expand=True, padx=10, pady=6)
            ctk.CTkLabel(
                info, text=r["title"],
                font=(theme.FONT, 12, "bold"), text_color=theme.TEXT,
                anchor="w").pack(anchor="w")
            ctk.CTkLabel(
                info,
                text=f"{r['author']} · ⬇ {_FMT(r['downloads'])} · {r['description'][:110]}",
                font=(theme.FONT, 10), text_color=theme.MUTED,
                anchor="w", wraplength=560, justify="left").pack(anchor="w")
            btn = ctk.CTkButton(
                row, text="Installer", width=90, height=28,
                fg_color=theme.GREEN, hover_color="#16a34a",
                text_color="#06210f")
            btn.configure(command=lambda b=btn, res=r: self._install(res, b))
            btn.pack(side="right", padx=10)

    # ------------------------------------------------------------ install

    def _install(self, result, btn):
        if self._busy:
            return
        self._busy = True
        btn.configure(state="disabled", text="…")
        self._set_status(f"Installation de {result['title']}…")
        api_key = self.cf_key.get().strip()
        self.settings["curseforge_api_key"] = api_key
        save_settings(self.settings)

        def work():
            try:
                path = mods_mod.install_result(
                    result, self.server_dir, self.meta["loader"],
                    self.meta["mc_version"], api_key=api_key)
                self.after(0, lambda: self._set_status(
                    f"✔ {path.name} installé dans {path.parent.name}/"))
                self.after(0, self._refresh_installed)
                self.after(0, lambda: btn.configure(text="✔"))
            except Exception as e:
                self.after(0, lambda: self._set_status(
                    f"✖ {result['title']} : {e}"))
                self.after(0, lambda: btn.configure(state="normal",
                                                    text="Installer"))
            finally:
                self._busy = False

        threading.Thread(target=work, daemon=True).start()

    def _refresh_installed(self):
        for w in self.installed_frame.winfo_children():
            w.destroy()
        items = mods_mod.list_installed(self.server_dir, self.meta["loader"])
        if not items:
            ctk.CTkLabel(self.installed_frame, text="Rien d'installé.",
                         text_color=theme.MUTED).pack(pady=10)
            return
        for it in items:
            row = ctk.CTkFrame(self.installed_frame, fg_color=theme.PANEL_2,
                               corner_radius=8)
            row.pack(fill="x", padx=4, pady=3)
            badge = "MOD" if it["kind"] == "mod" else "PLUGIN"
            ctk.CTkLabel(
                row, text=f"[{badge}] {it['name']}", anchor="w",
                font=(theme.FONT, 11), text_color=theme.TEXT,
            ).pack(side="left", padx=10, pady=6)
            ctk.CTkButton(
                row, text="Supprimer", width=80, height=26,
                fg_color=theme.RED, hover_color="#b91c1c",
                command=lambda p=it["path"]: self._remove(p),
            ).pack(side="right", padx=8)

    def _remove(self, path):
        if messagebox.askyesno("Supprimer", f"Supprimer {path.split('/')[-1].split(chr(92))[-1]} ?",
                               parent=self):
            mods_mod.remove_installed(path)
            self._refresh_installed()
