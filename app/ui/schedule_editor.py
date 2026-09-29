"""Éditeur des commandes planifiées : une ligne par commande
(« toutes les N min » ou « à HH:MM »), bouton « + Ajouter »."""
import customtkinter as ctk

from ..core.scheduler import clean_tasks
from ..i18n import t
from . import theme

_E = dict(fg_color=theme.PANEL_2, border_color=theme.BORDER,
          text_color=theme.TEXT, height=30)


class ScheduleEditor(ctk.CTkFrame):
    def __init__(self, master, tasks=None):
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        self._modes = {"every": t("sch_every"), "at": t("sch_at")}
        self.rows_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.rows_frame.grid(row=0, column=0, sticky="ew")
        self.rows_frame.grid_columnconfigure(2, weight=1)
        for j, key in enumerate(("sch_mode", "sch_value", "sch_cmd")):
            ctk.CTkLabel(self.rows_frame, text=t(key), font=(theme.FONT, 10),
                         text_color=theme.MUTED, anchor="w").grid(
                row=0, column=j, sticky="w", padx=3)
        self._rows = []
        for task in tasks or []:
            self.add_row(task)
        ctk.CTkButton(self, text="＋  " + t("sch_add"), height=30,
                      fg_color="transparent", border_width=1,
                      border_color=theme.ACCENT, text_color=theme.ACCENT,
                      hover_color=theme.PANEL_2,
                      command=lambda: self.add_row({})).grid(
            row=1, column=0, sticky="w", pady=(6, 0))
        ctk.CTkLabel(self, text=t("sch_hint"), font=(theme.FONT, 10),
                     text_color=theme.MUTED, anchor="w", wraplength=560,
                     justify="left").grid(row=2, column=0, sticky="w",
                                          padx=3, pady=(8, 0))

    def add_row(self, task: dict):
        r = len(self._rows) + 1
        mode = ctk.CTkOptionMenu(
            self.rows_frame, values=list(self._modes.values()), width=140,
            height=30, fg_color=theme.PANEL_2, button_color=theme.ACCENT,
            button_hover_color=theme.ACCENT_HOVER, text_color=theme.TEXT)
        mode.set(self._modes.get(task.get("mode"), self._modes["every"]))
        value = ctk.CTkEntry(self.rows_frame, width=70, **_E)
        value.insert(0, str(task.get("value", "") or ""))
        cmd = ctk.CTkEntry(self.rows_frame, placeholder_text=t("sch_cmd_ph"),
                           **_E)
        cmd.insert(0, task.get("cmd", ""))
        row = {"mode": mode, "value": value, "cmd": cmd}
        rm = ctk.CTkButton(self.rows_frame, text="✕", width=30, height=30,
                           fg_color=theme.PANEL_2, hover_color=theme.RED,
                           text_color=theme.TEXT,
                           command=lambda: self._remove(row))
        row["rm"] = rm
        for j, w in enumerate((mode, value, cmd, rm)):
            w.grid(row=r, column=j, sticky="ew", padx=3, pady=2)
        self._rows.append(row)

    def _remove(self, row):
        for k in ("mode", "value", "cmd", "rm"):
            row[k].destroy()
        self._rows.remove(row)

    def get(self) -> list:
        """Liste normalisée ; lève ValueError (message traduit) si invalide."""
        at = self._modes["at"]
        return clean_tasks([{
            "mode": "at" if r["mode"].get() == at else "every",
            "value": r["value"].get(), "cmd": r["cmd"].get(),
        } for r in self._rows])
