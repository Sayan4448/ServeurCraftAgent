"""Fenêtre 'Mods & Plugins' : navigation Modrinth/CurseForge avec icônes,
descriptions, pagination et choix de version."""
import threading
from io import BytesIO
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk
import requests
from PIL import Image

from ..config import load_settings, save_settings
from ..core import mods as mods_mod
from ..core.downloader import LOADER_LABELS
from . import theme

PAGE_SIZE = 20


def _fmt(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.0f}k"
    return str(n)


class ModsManager(ctk.CTkToplevel):
    def __init__(self, master, meta: dict):
        super().__init__(master)
        self.meta = meta
        self.server_dir = Path(meta["dir"])
        self.settings = load_settings()
        self._busy = False
        self._offset = 0
        self._last_query = ""
        self._icon_cache = {}

        loader_label = LOADER_LABELS.get(meta["loader"], meta["loader"])
        self.title(f"Mods & Plugins — {meta['name']} ({meta['mc_version']})")
        self.geometry("860x700")
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
            unselected_hover_color=theme.HOVER,
            command=lambda _v: self._search(reset=True))
        self.kind_seg.set(
            "Plugins" if mods_mod.default_kind(meta["loader"]) == "plugin"
            else "Mods")
        self.kind_seg.pack(side="left", padx=6, pady=10)

        self.search_entry = ctk.CTkEntry(
            ctrl, placeholder_text="Rechercher (ex: jei, luckperms, voice chat)…",
            fg_color=theme.PANEL_2, border_color=theme.BORDER,
            text_color=theme.TEXT, width=220)
        self.search_entry.pack(side="left", padx=10)
        self.search_entry.bind("<Return>", lambda e: self._search(reset=True))
        ctk.CTkButton(ctrl, text="Rechercher", width=100,
                      fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                      command=lambda: self._search(reset=True),
                      ).pack(side="left", padx=4, pady=10)

        # clé CurseForge (affichée seulement si source=CurseForge)
        self.cf_box = ctk.CTkFrame(ctrl, fg_color="transparent")
        ctk.CTkLabel(self.cf_box, text="Clé CurseForge",
                     text_color=theme.MUTED, font=(theme.FONT, 11),
                     ).pack(side="left", padx=(10, 4))
        self.cf_key = ctk.CTkEntry(
            self.cf_box, width=150, show="•", placeholder_text="x-api-key",
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

        ctk.CTkLabel(body, text="Parcourir", font=(theme.FONT, 13, "bold"),
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
        self._search(reset=True)  # vue "populaires" au démarrage

    # ------------------------------------------------------------ helpers

    def _kind(self) -> str:
        return "plugin" if self.kind_seg.get() == "Plugins" else "mod"

    def _source_changed(self, _v):
        if self.source_seg.get() == "CurseForge":
            self.cf_box.pack(side="left", padx=4)
        else:
            self.cf_box.pack_forget()
        self._search(reset=True)

    def _set_status(self, text):
        self.status.configure(text=text)

    def _save_cf_key(self):
        self.settings["curseforge_api_key"] = self.cf_key.get().strip()
        save_settings(self.settings)

    # ------------------------------------------------------------- icônes

    def _load_icon(self, url: str, label):
        if not url:
            return
        if url in self._icon_cache:
            label.configure(image=self._icon_cache[url], text="")
            return

        def work():
            try:
                data = requests.get(url, timeout=10).content
                img = Image.open(BytesIO(data)).convert("RGBA")
                cimg = ctk.CTkImage(light_image=img, dark_image=img,
                                    size=(44, 44))
                self._icon_cache[url] = cimg
                self.after(0, lambda: label.configure(image=cimg, text=""))
            except Exception:
                pass

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------ recherche

    def _search(self, reset=False):
        if self._busy:
            return
        if reset:
            self._offset = 0
            self._last_query = self.search_entry.get().strip()
            for w in self.results_frame.winfo_children():
                w.destroy()
        self._busy = True
        self._set_status("Recherche…")
        query = self._last_query
        source = self.source_seg.get()
        kind = self._kind()
        api_key = self.cf_key.get().strip()
        offset = self._offset

        def work():
            try:
                if source == "CurseForge":
                    self._save_cf_key()
                    res = mods_mod.search_curseforge(
                        query, self.meta["loader"], self.meta["mc_version"],
                        kind, api_key, limit=PAGE_SIZE, offset=offset)
                else:
                    res = mods_mod.search_modrinth(
                        query, self.meta["loader"], self.meta["mc_version"],
                        kind, limit=PAGE_SIZE, offset=offset)
                self.after(0, self._show_results, res)
            except Exception as e:
                self.after(0, self._set_status, f"Erreur : {e}")
            finally:
                self._busy = False

        threading.Thread(target=work, daemon=True).start()

    def _show_results(self, results):
        self._offset += len(results)
        self._set_status(f"{self._offset} résultat(s) affiché(s)")
        if not results and self._offset == 0:
            ctk.CTkLabel(self.results_frame, text="Aucun résultat.",
                         text_color=theme.MUTED).pack(pady=12)
            return
        for r in results:
            self._add_result_card(r)
        if len(results) >= PAGE_SIZE:
            ctk.CTkButton(
                self.results_frame, text="Charger plus…", height=30,
                fg_color=theme.PANEL_2, hover_color=theme.HOVER,
                text_color=theme.TEXT, command=self._search,
            ).pack(pady=8)

    def _add_result_card(self, r):
        card = ctk.CTkFrame(self.results_frame, fg_color=theme.PANEL_2,
                            corner_radius=8)
        card.pack(fill="x", padx=4, pady=4)

        icon_lbl = ctk.CTkLabel(card, text="…", width=52, height=52,
                                fg_color=theme.PANEL, corner_radius=8)
        icon_lbl.pack(side="left", padx=8, pady=8)
        self._load_icon(r.get("icon", ""), icon_lbl)

        info = ctk.CTkFrame(card, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True, padx=4, pady=6)
        ctk.CTkLabel(info, text=r["title"], font=(theme.FONT, 13, "bold"),
                     text_color=theme.TEXT, anchor="w").pack(anchor="w")
        ctk.CTkLabel(
            info, text=f"{r['author']} · ⬇ {_fmt(r['downloads'])}",
            font=(theme.FONT, 10), text_color=theme.ACCENT,
            anchor="w").pack(anchor="w")
        ctk.CTkLabel(
            info, text=r["description"], font=(theme.FONT, 11),
            text_color=theme.MUTED, anchor="w", wraplength=560,
            justify="left").pack(anchor="w")

        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.pack(side="right", padx=8, pady=8)
        inst = ctk.CTkButton(
            btns, text="Installer", width=110, height=30,
            fg_color=theme.GREEN, hover_color="#16a34a",
            text_color="#06210f")
        inst.configure(command=lambda b=inst, res=r: self._install_latest(res, b))
        inst.pack(pady=(0, 6))
        ctk.CTkButton(
            btns, text="Versions ▾", width=110, height=30,
            fg_color=theme.PANEL, hover_color=theme.HOVER,
            text_color=theme.TEXT,
            command=lambda res=r: VersionsDialog(self, res)).pack()

    # ------------------------------------------------------------ install

    def _install_latest(self, result, btn):
        if self._busy:
            return
        self._busy = True
        btn.configure(state="disabled", text="…")
        self._set_status(f"Installation de {result['title']}…")
        self._save_cf_key()
        api_key = self.cf_key.get().strip()

        def work():
            try:
                path = mods_mod.install_result(
                    result, self.server_dir, self.meta["loader"],
                    self.meta["mc_version"], api_key=api_key)
                self.after(0, lambda: self._set_status(
                    f"✔ {path.name} installé dans {path.parent.name}/"))
                self.after(0, self._refresh_installed)
                self.after(0, lambda: btn.configure(text="✔ Installé"))
            except Exception as e:
                self.after(0, lambda: self._set_status(
                    f"✖ {result['title']} : {e}"))
                self.after(0, lambda: btn.configure(state="normal",
                                                    text="Installer"))
            finally:
                self._busy = False

        threading.Thread(target=work, daemon=True).start()

    def _install_version(self, result, version, btn):
        if self._busy:
            return
        self._busy = True
        btn.configure(state="disabled", text="…")
        self._set_status(f"Téléchargement {version['filename']}…")

        def work():
            try:
                path = mods_mod.download_to(
                    version["url"], version["filename"], self.server_dir,
                    self.meta["loader"], result["kind"])
                self.after(0, lambda: self._set_status(
                    f"✔ {path.name} installé dans {path.parent.name}/"))
                self.after(0, self._refresh_installed)
                self.after(0, lambda: btn.configure(text="✔"))
            except Exception as e:
                self.after(0, lambda: self._set_status(f"✖ {e}"))
                self.after(0, lambda: btn.configure(state="normal",
                                                    text="Installer"))
            finally:
                self._busy = False

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------ installés

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
            color = theme.ACCENT if it["kind"] == "mod" else theme.ORANGE
            ctk.CTkLabel(row, text=badge, width=52,
                         font=(theme.FONT, 9, "bold"), text_color=color,
                         anchor="w").pack(side="left", padx=(8, 0))
            ctk.CTkLabel(row, text=it["name"], anchor="w",
                         font=(theme.FONT, 11), text_color=theme.TEXT,
                         ).pack(side="left", padx=6, pady=6)
            ctk.CTkButton(
                row, text="Supprimer", width=80, height=26,
                fg_color=theme.RED, hover_color="#b91c1c",
                command=lambda p=it["path"]: self._remove(p),
            ).pack(side="right", padx=8)

    def _remove(self, path):
        name = Path(path).name
        if messagebox.askyesno("Supprimer", f"Supprimer {name} ?", parent=self):
            mods_mod.remove_installed(path)
            self._refresh_installed()


class VersionsDialog(ctk.CTkToplevel):
    """Liste toutes les versions compatibles d'un projet + bouton installer."""

    def __init__(self, manager: ModsManager, result: dict):
        super().__init__(manager)
        self.manager = manager
        self.result = result
        self.title(f"Versions — {result['title']}")
        self.geometry("640x480")
        self.configure(fg_color=theme.BG)
        self.transient(manager)

        ctk.CTkLabel(
            self, text=result["title"], font=(theme.FONT, 15, "bold"),
            text_color=theme.TEXT).pack(anchor="w", padx=16, pady=(14, 2))
        ctk.CTkLabel(
            self, text=f"{result['author']} · {result['description']}",
            font=(theme.FONT, 11), text_color=theme.MUTED, wraplength=600,
            justify="left").pack(anchor="w", padx=16, pady=(0, 8))

        self.frame = ctk.CTkScrollableFrame(self, fg_color=theme.PANEL,
                                          corner_radius=10)
        self.frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        self.status = ctk.CTkLabel(self, text="Chargement des versions…",
                                   text_color=theme.MUTED, font=(theme.FONT, 11))
        self.status.pack(anchor="w", padx=16, pady=(0, 10))
        self._load()

    def _load(self):
        def work():
            try:
                versions = mods_mod.version_list(
                    self.result, self.manager.meta["loader"],
                    self.manager.meta["mc_version"],
                    self.manager.cf_key.get().strip())
            except Exception as e:
                self.after(0, lambda: self.status.configure(
                    text=f"Erreur : {e}"))
                return
            self.after(0, self._show, versions)

        threading.Thread(target=work, daemon=True).start()

    def _show(self, versions):
        self.status.configure(
            text=f"{len(versions)} version(s) compatible(s) "
                 f"{self.manager.meta['mc_version']} — la plus récente en haut")
        if not versions:
            ctk.CTkLabel(self.frame, text="Aucune version compatible.",
                         text_color=theme.MUTED).pack(pady=16)
            return
        for v in versions:
            row = ctk.CTkFrame(self.frame, fg_color=theme.PANEL_2,
                               corner_radius=8)
            row.pack(fill="x", padx=4, pady=3)
            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", fill="x", expand=True, padx=10, pady=5)
            badge = v["release_type"]
            color = theme.GREEN if badge == "release" else theme.ORANGE
            ctk.CTkLabel(info, text=v["title"],
                         font=(theme.FONT, 12, "bold"), text_color=theme.TEXT,
                         anchor="w").pack(anchor="w")
            ctk.CTkLabel(
                info, text=f"{badge} · {v['date']} · MC {v['game_versions']}",
                font=(theme.FONT, 10), text_color=color, anchor="w",
            ).pack(anchor="w")
            btn = ctk.CTkButton(
                row, text="Installer", width=90, height=28,
                fg_color=theme.GREEN, hover_color="#16a34a",
                text_color="#06210f")
            btn.configure(command=lambda b=btn, ver=v:
                          self.manager._install_version(self.result, ver, b))
            btn.pack(side="right", padx=10)
