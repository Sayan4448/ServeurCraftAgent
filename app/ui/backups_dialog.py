"""Fenêtre « Sauvegardes » : liste, restauration (avec confirmation),
sauvegarde manuelle, suppression."""
import subprocess
import threading
from tkinter import messagebox

import customtkinter as ctk

from ..core import backups as bk
from ..core import server_manager as sm
from ..i18n import t
from . import theme
from .uithread import ui_call


class BackupsDialog(ctk.CTkToplevel):
    def __init__(self, master, name: str):
        super().__init__(master)
        self.name = name
        self.proc = sm.get_process(name)
        self._busy = False
        self.title(t("bk_title", name=name))
        self.geometry("620x520")
        self.minsize(520, 380)
        self.configure(fg_color=theme.BG)
        self.transient(master)
        self.after(100, self.lift)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        self.now_btn = ctk.CTkButton(
            top, text=t("bk_now"), height=34, fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER, font=(theme.FONT, 12, "bold"),
            command=self._backup_now)
        self.now_btn.pack(side="left")
        ctk.CTkButton(top, text=t("bk_open"), height=34,
                      fg_color=theme.PANEL_2, hover_color=theme.HOVER,
                      text_color=theme.TEXT,
                      command=self._open_folder).pack(side="left", padx=8)

        self.body = ctk.CTkScrollableFrame(self, fg_color=theme.PANEL,
                                           corner_radius=10)
        self.body.grid(row=1, column=0, sticky="nsew", padx=12, pady=6)
        self.body.grid_columnconfigure(0, weight=1)

        self.status = ctk.CTkLabel(self, text="", font=(theme.FONT, 11),
                                   text_color=theme.MUTED, anchor="w",
                                   justify="left", wraplength=580)
        self.status.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 4))
        ctk.CTkLabel(self, text=t("ss_bk_hint"), font=(theme.FONT, 10),
                     text_color=theme.MUTED, anchor="w", justify="left",
                     wraplength=580).grid(row=3, column=0, sticky="ew",
                                          padx=16, pady=(0, 12))
        self._refresh()

    # ------------------------------------------------------------ liste
    def _refresh(self):
        for w in self.body.winfo_children():
            w.destroy()
        items = bk.list_backups(self.name)
        if not items:
            ctk.CTkLabel(self.body, text=t("bk_empty"),
                         text_color=theme.MUTED).grid(
                row=0, column=0, sticky="w", padx=10, pady=10)
            return
        for i, b in enumerate(items):
            row = ctk.CTkFrame(self.body, fg_color=theme.PANEL_2,
                               corner_radius=8)
            row.grid(row=i, column=0, sticky="ew", padx=4, pady=2)
            row.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(row, text=b["date"], font=(theme.FONT, 12, "bold"),
                         text_color=theme.TEXT, anchor="w").grid(
                row=0, column=0, sticky="w", padx=10, pady=(6, 0))
            ctk.CTkLabel(row, text=f"{bk.reason_label(b['reason'])}  ·  "
                                   f"{bk.fmt_size(b['size'])}",
                         font=(theme.FONT, 10), text_color=theme.MUTED,
                         anchor="w").grid(row=1, column=0, sticky="w",
                                          padx=10, pady=(0, 6))
            ctk.CTkButton(row, text=t("bk_restore"), width=96, height=28,
                          fg_color=theme.ORANGE,
                          hover_color=theme.ORANGE_HOVER,
                          text_color="#ffffff",
                          command=lambda b=b: self._restore(b)).grid(
                row=0, column=1, rowspan=2, padx=4)
            ctk.CTkButton(row, text="🗑", width=32, height=28,
                          fg_color=theme.PANEL, hover_color=theme.RED,
                          text_color=theme.TEXT,
                          command=lambda b=b: self._delete(b)).grid(
                row=0, column=2, rowspan=2, padx=(0, 8))

    def _set_status(self, text, color=None):
        self.status.configure(text=text, text_color=color or theme.MUTED)

    def _set_busy(self, busy: bool):
        self._busy = busy
        self.now_btn.configure(state="disabled" if busy else "normal")

    # ------------------------------------------------------------ actions
    def _backup_now(self):
        if self._busy:
            return
        self._set_busy(True)
        self._set_status(t("bk_running"), theme.ORANGE)
        proc = self.proc

        def work():                   # thread : zip + save-off/save-on
            path = proc.backup("manual")
            ui_call(self, self._backup_done, path)
        threading.Thread(target=work, daemon=True).start()

    def _backup_done(self, path):
        self._set_busy(False)
        if path:
            self._set_status(t("bk_done", file=path.name,
                               size=bk.fmt_size(path.stat().st_size)),
                             theme.GREEN)
        else:
            self._set_status(t("bk_error", e=self.proc.backup_error),
                             theme.RED)
        self._refresh()

    def _restore(self, b):
        if self._busy:
            return
        if self.proc.is_running() or self.proc._starting:
            messagebox.showwarning(t("bk_restore"), t("bk_stop_first"),
                                   parent=self)
            return
        if not messagebox.askyesno(
                t("bk_restore"), t("bk_restore_confirm", date=b["date"]),
                icon="warning", parent=self):
            return
        self._set_busy(True)
        self._set_status(t("bk_restoring"), theme.ORANGE)
        proc = self.proc
        keep = int(proc.meta.get("backup_keep", bk.DEFAULT_KEEP))

        def work():
            try:
                bk.restore(self.name, proc.path, b["path"], keep=keep,
                           log=proc.log)
                proc.log(t("bk_restored", date=b["date"]))
                ui_call(self, self._restore_done, None, b["date"])
            except Exception as e:  # noqa: BLE001
                ui_call(self, self._restore_done, e, b["date"])
        threading.Thread(target=work, daemon=True).start()

    def _restore_done(self, err, date):
        self._set_busy(False)
        if err:
            self._set_status(t("bk_error", e=err), theme.RED)
        else:
            self._set_status(t("bk_restored", date=date), theme.GREEN)
        self._refresh()

    def _delete(self, b):
        if not messagebox.askyesno(t("srv_del_title"),
                                   t("bk_delete_confirm", date=b["date"]),
                                   parent=self):
            return
        try:
            bk.delete(b["path"])
        except OSError as e:
            self._set_status(t("bk_error", e=e), theme.RED)
        self._refresh()

    def _open_folder(self):
        d = bk.backup_dir(self.name)
        d.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer", str(d)])
