"""Fenêtre 'Mods & Plugins' : navigation Modrinth/CurseForge style ATLauncher —
icônes, descriptions, galerie, choix de version, lien vers la page du projet."""
import threading
import webbrowser
from io import BytesIO
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk
import requests
from PIL import Image

from ..config import curseforge_key, load_settings, save_settings
from ..core import mods as mods_mod
from ..core.downloader import LOADER_LABELS
from ..i18n import t
from . import theme
from .uithread import ui_call

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
        self._more_btn = None

        loader_label = LOADER_LABELS.get(meta["loader"], meta["loader"])
        self.title(t("mods_title", name=meta["name"], mc=meta["mc_version"]))
        self.geometry("880x720")
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
            **theme.SEG,
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
            **theme.SEG,
            command=lambda _v: self._search(reset=True))
        self.kind_seg.set(
            "Plugins" if mods_mod.default_kind(meta["loader"]) == "plugin"
            else "Mods")
        self.kind_seg.pack(side="left", padx=6, pady=10)

        self.search_entry = ctk.CTkEntry(
            ctrl, placeholder_text=t("mods_search_ph"),
            fg_color=theme.PANEL_2, border_color=theme.BORDER,
            text_color=theme.TEXT, width=220)
        self.search_entry.pack(side="left", padx=10)
        self.search_entry.bind("<Return>", lambda e: self._search(reset=True))
        ctk.CTkButton(ctrl, text=t("mods_search"), width=100,
                      fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                      command=lambda: self._search(reset=True),
                      ).pack(side="left", padx=4, pady=10)
        ctk.CTkButton(ctrl, text=t("mp_import"), width=170,
                      fg_color=theme.PANEL_2, hover_color=theme.HOVER,
                      text_color=theme.TEXT,
                      command=self._import_modpack).pack(
            side="left", padx=6, pady=10)

        # clé CurseForge (affichée seulement si source=CurseForge)
        self.cf_box = ctk.CTkFrame(ctrl, fg_color="transparent")
        ctk.CTkLabel(self.cf_box, text=t("mods_cf_key"),
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

        ctk.CTkLabel(body, text=t("mods_browse"), font=(theme.FONT, 13, "bold"),
                     text_color=theme.TEXT).grid(
            row=0, column=0, sticky="w", pady=(2, 4))
        self.results_frame = ctk.CTkScrollableFrame(body, fg_color=theme.PANEL,
                                                  corner_radius=10)
        self.results_frame.grid(row=1, column=0, sticky="nsew")

        head = ctk.CTkFrame(body, fg_color="transparent")
        head.grid(row=2, column=0, sticky="ew", pady=(8, 4))
        ctk.CTkLabel(head, text=t("mods_installed"),
                     font=(theme.FONT, 13, "bold"),
                     text_color=theme.TEXT).pack(side="left")
        self.check_btn = ctk.CTkButton(
            head, width=0, height=26, fg_color=theme.PANEL_2,
            hover_color=theme.HOVER, text_color=theme.TEXT,
            command=self._check,
            **theme.labelled("shield", t("mods_check"), "🩺", 14))
        self.check_btn.pack(side="right")
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
        """Enregistre la clé saisie (thread Tk uniquement)."""
        key = self.cf_key.get().strip()
        if key != self.settings.get("curseforge_api_key", ""):
            self.settings = load_settings()
            self.settings["curseforge_api_key"] = key
            save_settings(self.settings)

    def _api_key(self) -> str:
        """Clé saisie ici, sinon celle de l'environnement."""
        return self.cf_key.get().strip() or curseforge_key({})

    # ------------------------------------------------------------ icônes

    def _load_icon(self, url: str, label, size=(44, 44)):
        if not url:
            return
        if url in self._icon_cache:
            label.configure(image=self._icon_cache[url], text="")
            return

        def work():                   # thread : télécharge seulement
            try:
                data = requests.get(url, timeout=10).content
                img = Image.open(BytesIO(data)).convert("RGBA")
            except Exception:  # noqa: BLE001 — icône facultative
                return
            ui_call(self, self._icon_ready, url, img, size, label)

        threading.Thread(target=work, daemon=True).start()

    def _icon_ready(self, url, img, size, label):
        cimg = ctk.CTkImage(light_image=img, dark_image=img, size=size)
        self._icon_cache[url] = cimg
        if label.winfo_exists():
            label.configure(image=cimg, text="")

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
        self._set_status(t("mods_searching"))
        query = self._last_query
        source = self.source_seg.get()
        kind = self._kind()
        api_key = self._api_key()
        offset = self._offset
        if source == "CurseForge":
            self._save_cf_key()

        def work():                   # thread : aucun appel Tk
            try:
                if source == "CurseForge":
                    res = mods_mod.search_curseforge(
                        query, self.meta["loader"], self.meta["mc_version"],
                        kind, api_key, limit=PAGE_SIZE, offset=offset)
                else:
                    res = mods_mod.search_modrinth(
                        query, self.meta["loader"], self.meta["mc_version"],
                        kind, limit=PAGE_SIZE, offset=offset)
                ui_call(self, self._show_results, res)
            except Exception as e:  # noqa: BLE001
                ui_call(self, self._set_status,
                        t("mods_error", e=mods_mod.explain(e)))
            finally:
                self._busy = False

        threading.Thread(target=work, daemon=True).start()

    def _show_results(self, results):
        if self._more_btn is not None:      # l'ancien « Charger plus »
            if self._more_btn.winfo_exists():
                self._more_btn.destroy()
            self._more_btn = None
        self._offset += len(results)
        self._set_status(t("mods_results", n=self._offset))
        if not results and self._offset == 0:
            ctk.CTkLabel(self.results_frame, text=t("mods_no_result"),
                         text_color=theme.MUTED).pack(pady=12)
            return
        for r in results:
            self._add_result_card(r)
        if len(results) >= PAGE_SIZE:
            self._more_btn = ctk.CTkButton(
                self.results_frame, text=t("mods_load_more"), height=30,
                fg_color=theme.PANEL_2, hover_color=theme.HOVER,
                text_color=theme.TEXT, command=self._search)
            self._more_btn.pack(pady=8)

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
            text_color=theme.MUTED, anchor="w", wraplength=520,
            justify="left").pack(anchor="w")

        # clic sur la carte → fiche détaillée
        for w in (card, icon_lbl, info):
            w.bind("<Button-1>", lambda e, res=r: ModDetailDialog(self, res))

        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.pack(side="right", padx=8, pady=8)
        inst = ctk.CTkButton(
            btns, text=t("mods_install"), width=110, height=30,
            fg_color=theme.GREEN, hover_color=theme.GREEN_HOVER,
            text_color=theme.ON_GREEN)
        inst.configure(command=lambda b=inst, res=r: self._install_latest(res, b))
        inst.pack(pady=(0, 6))
        ctk.CTkButton(
            btns, text=t("mods_details"), width=110, height=30,
            fg_color=theme.PANEL, hover_color=theme.HOVER,
            text_color=theme.TEXT,
            command=lambda res=r: ModDetailDialog(self, res)).pack()

    # ------------------------------------------------------------ install

    def _install_latest(self, result, btn):
        if self._busy:
            return
        self._busy = True
        btn.configure(state="disabled", text="…")
        self._set_status(t("mods_installing", name=result["title"]))
        self._save_cf_key()
        api_key = self._api_key()

        def work():
            replaced = []
            try:
                path = mods_mod.install_result(
                    result, self.server_dir, self.meta["loader"],
                    self.meta["mc_version"], api_key=api_key,
                    replaced=replaced)
                ui_call(self, self._installed, path, replaced, btn,
                        t("mods_installed_btn"))
            except Exception as e:  # noqa: BLE001
                ui_call(self, self._install_failed, btn,
                        f"{result['title']} : {mods_mod.explain(e)}")
            finally:
                self._busy = False

        threading.Thread(target=work, daemon=True).start()

    def _install_version(self, result, version, btn):
        if self._busy:
            return
        self._busy = True
        btn.configure(state="disabled", text="…")
        self._set_status(f"⬇ {version['filename']}…")

        def work():
            replaced = []
            try:
                path = mods_mod.download_to(
                    version["url"], version["filename"], self.server_dir,
                    self.meta["loader"], result["kind"], result=result,
                    replaced=replaced, deps=version.get("deps"),
                    mc_version=self.meta["mc_version"])
                ui_call(self, self._installed, path, replaced, btn, "✔")
            except Exception as e:  # noqa: BLE001
                ui_call(self, self._install_failed, btn, mods_mod.explain(e))
            finally:
                self._busy = False

        threading.Thread(target=work, daemon=True).start()

    def _installed(self, path, replaced, btn, btn_text):
        text = t("mods_installed_in", file=path.name, dir=path.parent.name)
        if replaced:
            text += f"  ({t('mods_replaced', old=', '.join(replaced))})"
        self._set_status(text)
        self._refresh_installed()
        if btn.winfo_exists():
            btn.configure(text=btn_text)

    def _install_failed(self, btn, message):
        self._set_status(t("mods_error", e=message))
        if btn.winfo_exists():
            btn.configure(state="normal", text=t("mods_install"))

    # ------------------------------------------------------------ installés

    def _refresh_installed(self):
        for w in self.installed_frame.winfo_children():
            w.destroy()
        items = mods_mod.list_installed(self.server_dir, self.meta["loader"])
        if not items:
            ctk.CTkLabel(self.installed_frame, text=t("mods_none_installed"),
                         text_color=theme.MUTED).pack(pady=10)
            return
        for it in items:
            off = bool(it.get("disabled"))
            row = ctk.CTkFrame(self.installed_frame, fg_color=theme.PANEL_2,
                               corner_radius=8)
            row.pack(fill="x", padx=4, pady=3)
            badge = "MOD" if it["kind"] == "mod" else "PLUGIN"
            color = theme.MUTED if off else (
                theme.ACCENT if it["kind"] == "mod" else theme.ORANGE)
            ctk.CTkLabel(row, text=badge, width=52,
                         font=(theme.FONT, 9, "bold"), text_color=color,
                         anchor="w").pack(side="left", padx=(8, 0))
            name = it["name"] + (f"   ({t('mods_disabled_tag')})" if off
                                 else "")
            ctk.CTkLabel(row, text=name, anchor="w",
                         font=(theme.FONT, 11),
                         text_color=theme.MUTED if off else theme.TEXT,
                         ).pack(side="left", padx=6, pady=6)
            ctk.CTkButton(
                row, text=t("mods_del"), width=80, height=26,
                fg_color=theme.RED, hover_color=theme.RED_HOVER,
                command=lambda p=it["path"]: self._remove(p),
            ).pack(side="right", padx=8)
            ctk.CTkButton(
                row, text=t("mods_enable" if off else "mods_disable"),
                width=90, height=26, fg_color=theme.PANEL,
                hover_color=theme.HOVER, text_color=theme.TEXT,
                command=lambda p=it["path"], on=off: self._toggle(p, on),
            ).pack(side="right")

    def _toggle(self, path, enabled: bool) -> bool:
        """Active / désactive un fichier (renommage, rien n'est supprimé)."""
        try:
            mods_mod.set_enabled(path, enabled)
        except OSError:               # jar verrouillé par le serveur lancé
            self._set_status(t("mods_locked", name=Path(path).name))
            return False
        self._refresh_installed()
        return True

    # ------------------------------------------------------ vérification
    def _check(self):
        """Cherche les fichiers qui ne peuvent pas marcher sur ce serveur."""
        self.check_btn.configure(state="disabled")
        self._set_status(t("mods_checking"))
        loader, mc = self.meta["loader"], self.meta["mc_version"]

        def work():                   # thread : aucun appel Tk
            try:
                issues = mods_mod.audit(self.server_dir, loader, mc)
                n = len(mods_mod.list_installed(self.server_dir, loader))
                ui_call(self, self._checked, issues, n)
            except Exception as e:  # noqa: BLE001
                ui_call(self, self._checked, None, 0, mods_mod.explain(e))
        threading.Thread(target=work, daemon=True).start()

    def _checked(self, issues, n, error=""):
        self.check_btn.configure(state="normal")
        if issues is None:
            self._set_status(t("mods_error", e=error))
        elif not issues:
            self._set_status(t("mods_check_ok", n=n))
        else:
            self._set_status("")
            AuditDialog(self, issues)

    def _remove(self, path):
        name = Path(path).name
        if messagebox.askyesno(t("mods_del"),
                               t("mods_del_confirm", name=name), parent=self):
            try:
                mods_mod.remove_installed(path)
            except OSError:           # jar verrouillé par le serveur lancé
                self._set_status(t("mods_locked", name=name))
            self._refresh_installed()

    # ---------------------------------------------------------- modpack
    def _import_modpack(self):
        path = pick_modpack(self)
        if not path:
            return
        self._set_status(t("mp_analyzing"))
        cf_key = self._api_key() or curseforge_key()

        def work():
            from ..core import modpack
            try:
                pack = modpack.read_pack(path)
                result = modpack.plan(pack, cf_key=cf_key,
                                      log=lambda m: ui_call(
                                          self, self._set_status, m))
                ui_call(self, self._show_modpack_result, result)
            except Exception as e:  # noqa: BLE001
                ui_call(self, self._set_status,
                        t("mods_error", e=mods_mod.explain(e)))
        threading.Thread(target=work, daemon=True).start()

    def _show_modpack_result(self, result: dict):
        self._set_status("")
        n = sum(len(result[k]) for k in ("server", "client", "unknown"))
        if not n:
            self._set_status(t("mp_none"))
            return
        ModpackDialog(self, result, self.server_dir,
                      on_done=self._refresh_installed)


def pick_modpack(parent):
    """Fichier .mrpack/.zip ou dossier d'instance (Prism, MultiMC…)."""
    from tkinter import filedialog
    choice = messagebox.askyesnocancel(t("mp_pick"), t("mp_pick_kind"),
                                       parent=parent)
    if choice is None:
        return None
    if choice:
        return filedialog.askopenfilename(
            parent=parent, title=t("mp_pick"),
            filetypes=[("Modpack", "*.mrpack *.zip"), ("Tous", "*.*")])
    return filedialog.askdirectory(parent=parent, title=t("mp_pick_folder"))


class AuditDialog(ctk.CTkToplevel):
    """Fichiers à problème trouvés par la vérification, à désactiver."""

    def __init__(self, manager: ModsManager, issues: list):
        super().__init__(manager)
        self.manager = manager
        self.title(t("mods_check_title", n=len(issues)))
        self.geometry("640x460")
        self.configure(fg_color=theme.BG)
        self.transient(manager)
        self.after(100, self.lift)
        ctk.CTkLabel(self, text=t("mods_check_hint"), font=(theme.FONT, 11),
                     text_color=theme.MUTED, wraplength=600,
                     justify="left").pack(fill="x", padx=14, pady=(12, 6))
        body = ctk.CTkScrollableFrame(self, fg_color=theme.PANEL,
                                      corner_radius=10)
        body.pack(fill="both", expand=True, padx=12, pady=4)
        loader, mc = manager.meta["loader"], manager.meta["mc_version"]
        self._rows = []
        for issue in issues:
            row = ctk.CTkFrame(body, fg_color=theme.PANEL_2, corner_radius=8)
            row.pack(fill="x", padx=4, pady=3)
            btn = ctk.CTkButton(row, text=t("mods_disable"), width=96,
                                height=28, fg_color=theme.ORANGE,
                                hover_color=theme.ORANGE_HOVER)
            btn.configure(command=lambda i=issue, b=btn: self._disable(i, b))
            btn.pack(side="right", padx=8, pady=6)
            ctk.CTkLabel(row, text=issue["name"], anchor="w",
                         font=(theme.FONT, 11, "bold"),
                         text_color=theme.TEXT).pack(
                fill="x", padx=10, pady=(6, 0))
            ctk.CTkLabel(row, text=mods_mod.audit_text(issue, loader, mc),
                         anchor="w", justify="left", wraplength=440,
                         font=(theme.FONT, 10),
                         text_color=theme.ORANGE).pack(
                fill="x", padx=10, pady=(0, 6))
            self._rows.append((issue, btn))
        ctk.CTkButton(self, text=t("mods_disable_all"), height=34,
                      fg_color=theme.ORANGE, hover_color=theme.ORANGE_HOVER,
                      command=self._disable_all).pack(
            fill="x", padx=12, pady=(6, 12))

    def _disable(self, issue, btn):
        if btn.cget("state") != "disabled" and \
                self.manager._toggle(issue["path"], False):
            btn.configure(state="disabled", text="✔", fg_color=theme.DISABLED)

    def _disable_all(self):
        for issue, btn in self._rows:
            self._disable(issue, btn)


class ModpackDialog(ctk.CTkToplevel):
    """Résultat de l'analyse : mods serveur / mods client / indéterminés."""

    def __init__(self, master, result: dict, server_dir, on_done=None):
        super().__init__(master)
        self.manager = master
        self.server_dir = Path(server_dir)
        self.on_done = on_done
        self.result = result
        self.title(t("mp_result", n=sum(len(result[k]) for k in
                                        ("server", "client", "unknown"))))
        self.geometry("660x600")
        self.configure(fg_color=theme.BG)
        self.transient(master)
        self.after(100, self.lift)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(self, text=t("mp_client_hint"),
                     font=(theme.FONT, 11), text_color=theme.MUTED,
                     wraplength=590, justify="left").grid(
            row=0, column=0, sticky="w", padx=14, pady=(12, 0))
        self.inc_client = ctk.CTkCheckBox(
            self, text=t("mp_inc_client"), text_color=theme.TEXT,
            fg_color=theme.ACCENT)
        self.inc_client.grid(row=1, column=0, sticky="w", padx=14, pady=6)

        body = ctk.CTkScrollableFrame(self, fg_color=theme.PANEL,
                                      corner_radius=10)
        body.grid(row=2, column=0, sticky="nsew", padx=12, pady=6)
        self._section(body, t("mp_server", n=len(result["server"])),
                      result["server"], theme.GREEN)
        self._section(body, t("mp_client", n=len(result["client"])),
                      result["client"], theme.ORANGE)
        self._section(body, t("mp_unknown", n=len(result["unknown"])),
                      result["unknown"], theme.MUTED)

        self.status = ctk.CTkLabel(self, text="", text_color=theme.GREEN,
                                   font=(theme.FONT, 11))
        self.status.grid(row=3, column=0, sticky="w", padx=16)
        self.install_btn = ctk.CTkButton(
            self, text=t("mp_install"), height=36,
            font=(theme.FONT, 13, "bold"), fg_color=theme.GREEN,
            hover_color=theme.GREEN_HOVER, text_color=theme.ON_GREEN,
            command=self._install)
        self.install_btn.grid(row=4, column=0, sticky="ew", padx=12,
                              pady=(4, 12))

    def _section(self, parent, title, items, color):
        if not items:
            return
        ctk.CTkLabel(parent, text=title, font=(theme.FONT, 12, "bold"),
                     text_color=color, anchor="w").pack(
            fill="x", padx=6, pady=(10, 2))
        for it in items:
            row = ctk.CTkFrame(parent, fg_color=theme.PANEL_2,
                               corner_radius=6)
            row.pack(fill="x", padx=4, pady=1)
            ctk.CTkLabel(row, text=it.get("title") or it["name"],
                         font=(theme.FONT, 11),
                         text_color=theme.TEXT, anchor="w").pack(
                side="left", padx=8, pady=5)
            ctk.CTkLabel(row, text=it["name"],
                         font=(theme.FONT, 9), text_color=theme.MUTED,
                         anchor="e").pack(side="right", padx=8)

    def _install(self):
        from ..core import modpack
        self.install_btn.configure(state="disabled")
        self.status.configure(text=t("cp_installing"),
                              text_color=theme.ORANGE)
        inc = bool(self.inc_client.get())

        def work():
            try:
                res = modpack.apply_plan(self.result, self.server_dir,
                                         include_client=inc,
                                         log=lambda m: ui_call(
                                             self, self._status, m))
                ui_call(self, self._done, res)
            except Exception as e:  # noqa: BLE001
                ui_call(self, self._status, t("mods_error", e=e))
        threading.Thread(target=work, daemon=True).start()

    def _status(self, text):
        self.status.configure(text=text)

    def _done(self, res):
        self.status.configure(
            text=t("mp_done", n=res["installed"], c=res["client_skipped"],
                   f=res["configs"]), text_color=theme.GREEN)
        if self.on_done:
            self.on_done()


class ModDetailDialog(ctk.CTkToplevel):
    """Fiche projet style ATLauncher : icône, description complète, galerie,
    lien vers la page, et liste des versions compatibles avec installation."""

    def __init__(self, manager: ModsManager, result: dict):
        super().__init__(manager)
        self.manager = manager
        self.result = result
        self._gallery_imgs = []
        self.title(result["title"])
        self.geometry("720x640")
        self.configure(fg_color=theme.BG)
        self.transient(manager)

        scroll = ctk.CTkScrollableFrame(self, fg_color=theme.BG)
        scroll.pack(fill="both", expand=True, padx=10, pady=10)

        # ------------------------------------------------------------- tête
        head = ctk.CTkFrame(scroll, fg_color=theme.PANEL, corner_radius=10)
        head.pack(fill="x", padx=4, pady=4)
        self.icon_lbl = ctk.CTkLabel(head, text="…", width=72, height=72,
                                     fg_color=theme.PANEL_2, corner_radius=10)
        self.icon_lbl.pack(side="left", padx=12, pady=12)
        self.manager._load_icon(result.get("icon", ""), self.icon_lbl,
                                size=(72, 72))
        info = ctk.CTkFrame(head, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True, padx=4, pady=10)
        ctk.CTkLabel(info, text=result["title"],
                     font=(theme.FONT, 16, "bold"),
                     text_color=theme.TEXT, anchor="w").pack(anchor="w")
        self.meta_lbl = ctk.CTkLabel(
            info, text=f"{result['author']} · ⬇ {_fmt(result['downloads'])}",
            font=(theme.FONT, 11), text_color=theme.ACCENT, anchor="w")
        self.meta_lbl.pack(anchor="w")
        self.tags_lbl = ctk.CTkLabel(info, text="", font=(theme.FONT, 10),
                                     text_color=theme.MUTED, anchor="w")
        self.tags_lbl.pack(anchor="w", pady=(2, 0))

        btns = ctk.CTkFrame(head, fg_color="transparent")
        btns.pack(side="right", padx=12)
        url = result.get("url", "")
        if url:
            ctk.CTkButton(
                btns, text=t("mods_open_page"), width=150, height=30,
                fg_color=theme.PANEL_2, hover_color=theme.HOVER,
                text_color=theme.TEXT,
                command=lambda: webbrowser.open(url)).pack(pady=3)
        inst = ctk.CTkButton(
            btns, text=t("mods_install"), width=150, height=30,
            fg_color=theme.GREEN, hover_color=theme.GREEN_HOVER,
            text_color=theme.ON_GREEN)
        inst.configure(command=lambda b=inst:
                       manager._install_latest(result, b))
        inst.pack(pady=3)

        # ---------------------------------------------------- description
        self.desc_box = ctk.CTkTextbox(
            scroll, font=(theme.FONT, 12), fg_color=theme.PANEL,
            text_color=theme.TEXT, wrap="word", height=180,
            state="normal")
        self.desc_box.insert("1.0", result["description"])
        self.desc_box.configure(state="disabled")
        self.desc_box.pack(fill="x", padx=4, pady=4)

        # ---------------------------------------------------------- galerie
        self.gallery_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self.gallery_frame.pack(fill="x", padx=4, pady=4)

        # --------------------------------------------------------- versions
        ctk.CTkLabel(scroll, text=t("mods_versions_tab"),
                     font=(theme.FONT, 13, "bold"),
                     text_color=theme.TEXT).pack(anchor="w", padx=8, pady=(8, 2))
        self.versions_frame = ctk.CTkFrame(scroll, fg_color=theme.PANEL,
                                           corner_radius=10)
        self.versions_frame.pack(fill="x", padx=4, pady=(0, 6))
        self.vstatus = ctk.CTkLabel(
            self, text=t("mods_versions_loading"), text_color=theme.MUTED,
            font=(theme.FONT, 11))
        self.vstatus.pack(anchor="w", padx=16, pady=(0, 8))
        self._load_details()

    def _load_details(self):
        api_key = self.manager._api_key()

        def work():
            details, error = {}, ""
            try:
                details = mods_mod.project_details(self.result, api_key)
            except Exception:  # noqa: BLE001 — fiche facultative
                pass
            try:
                versions = mods_mod.version_list(
                    self.result, self.manager.meta["loader"],
                    self.manager.meta["mc_version"], api_key)
            except Exception as e:  # noqa: BLE001
                error = t("mods_error", e=mods_mod.explain(e))
                versions = []
            ui_call(self, self._populate, details, versions, error)

        threading.Thread(target=work, daemon=True).start()

    def _populate(self, details, versions, error=""):
        if details.get("body"):
            self.desc_box.configure(state="normal")
            self.desc_box.delete("1.0", "end")
            self.desc_box.insert("1.0", details["body"][:8000])
            self.desc_box.configure(state="disabled")
        if details.get("icon"):
            self.manager._load_icon(details["icon"], self.icon_lbl,
                                    size=(72, 72))
        tags = details.get("categories") or []
        if tags:
            self.tags_lbl.configure(text=" · ".join(tags[:8]))
        for url in details.get("gallery", []):
            self._gallery_thumb(url)
        mc = self.manager.meta["mc_version"]
        self.vstatus.configure(
            text=error or t("mods_versions_count", n=len(versions), mc=mc),
            text_color=theme.RED if error else theme.MUTED)
        if not versions:
            ctk.CTkLabel(self.versions_frame, text=t("mods_no_compat"),
                         text_color=theme.MUTED).pack(pady=14)
            return
        for v in versions:
            row = ctk.CTkFrame(self.versions_frame, fg_color=theme.PANEL_2,
                               corner_radius=8)
            row.pack(fill="x", padx=6, pady=3)
            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", fill="x", expand=True, padx=10, pady=5)
            badge = v["release_type"]
            color = theme.GREEN if badge == "release" else theme.ORANGE
            ctk.CTkLabel(info, text=v["title"],
                         font=(theme.FONT, 12, "bold"), text_color=theme.TEXT,
                         anchor="w").pack(anchor="w")
            ctk.CTkLabel(
                info,
                text=f"{badge} · {v['date']} · MC {v['game_versions']}",
                font=(theme.FONT, 10), text_color=color, anchor="w",
            ).pack(anchor="w")
            btn = ctk.CTkButton(
                row, text=t("mods_install"), width=90, height=28,
                fg_color=theme.GREEN, hover_color=theme.GREEN_HOVER,
                text_color=theme.ON_GREEN)
            btn.configure(command=lambda b=btn, ver=v:
                          self.manager._install_version(self.result, ver, b))
            btn.pack(side="right", padx=10)

    def _gallery_thumb(self, url):
        holder = ctk.CTkLabel(self.gallery_frame, text="", width=120,
                              height=70, fg_color=theme.PANEL,
                              corner_radius=8)
        holder.pack(side="left", padx=4, pady=4)

        def work():                   # thread : télécharge seulement
            try:
                data = requests.get(url, timeout=10).content
                img = Image.open(BytesIO(data)).convert("RGBA")
                img.thumbnail((240, 140))
            except Exception:  # noqa: BLE001 — miniature facultative
                img = None
            ui_call(self, self._thumb_ready, holder, img, url)

        threading.Thread(target=work, daemon=True).start()

    def _thumb_ready(self, holder, img, url):
        if not holder.winfo_exists():
            return
        if img is None:
            holder.pack_forget()
            return
        cimg = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
        self._gallery_imgs.append(cimg)  # garde la référence
        holder.configure(image=cimg, text="", cursor="hand2")
        holder.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))
