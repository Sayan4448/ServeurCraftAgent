"""Éditeur de tunnels Playit : 3 lignes par défaut (Java, Bedrock, Voice
Chat), bouton « + Ajouter » pour en mettre autant qu'on veut."""
import customtkinter as ctk

from ..core import tunnels as tn_mod
from ..i18n import t
from . import theme

_E = dict(fg_color=theme.PANEL_2, border_color=theme.BORDER,
          text_color=theme.TEXT, height=30)


class TunnelsEditor(ctk.CTkFrame):
    def __init__(self, master, tunnels=None):
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        self.rows_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.rows_frame.grid(row=0, column=0, sticky="ew")
        self.rows_frame.grid_columnconfigure(2, weight=1)
        for j, key in enumerate(("tn_name", "tn_proto", "tn_address",
                                 "tn_local")):
            ctk.CTkLabel(self.rows_frame, text=t(key), font=(theme.FONT, 10),
                         text_color=theme.MUTED, anchor="w").grid(
                row=0, column=j, sticky="w", padx=3)
        self._rows = []
        self.load(tunnels)
        ctk.CTkButton(self, text="＋  " + t("tn_add"), height=30,
                      fg_color="transparent", border_width=1,
                      border_color=theme.ACCENT, text_color=theme.ACCENT,
                      hover_color=theme.PANEL_2,
                      command=lambda: self.add_row({})).grid(
            row=1, column=0, sticky="w", pady=(6, 0))
        ctk.CTkLabel(self, text=t("tn_hint"), font=(theme.FONT, 10),
                     text_color=theme.MUTED, anchor="w", wraplength=560,
                     justify="left").grid(row=2, column=0, sticky="w",
                                          padx=3, pady=(8, 0))

    def load(self, tunnels=None):
        """(Re)remplit les lignes : les 3 tunnels par défaut, complétés par
        ceux déjà enregistrés."""
        for row in list(self._rows):
            self._remove(row)
        base = [dict(d) for d in tn_mod.DEFAULTS]
        for tn in tunnels or []:
            free = [b for b in base if b["proto"] == tn.get("proto")
                    and not b["address"]]
            match = next((b for b in free
                          if str(b["local"]) == str(tn.get("local"))), None) \
                or next((b for b in free if b["name"] == tn.get("name")),
                        None)
            if match:
                match.update(tn)
            else:
                base.append(dict(tn))
        for tn in base:
            self.add_row(tn)

    def add_row(self, tn: dict):
        r = len(self._rows) + 1
        name = ctk.CTkEntry(self.rows_frame, width=100, **_E)
        name.insert(0, tn.get("name", ""))
        proto = ctk.CTkOptionMenu(
            self.rows_frame, values=["TCP", "UDP"], width=70, height=30,
            fg_color=theme.PANEL_2, button_color=theme.ACCENT,
            button_hover_color=theme.ACCENT_HOVER, text_color=theme.TEXT)
        proto.set((tn.get("proto") or "tcp").upper())
        addr = ctk.CTkEntry(self.rows_frame, placeholder_text=t("cre_addr_ph"),
                            **_E)
        addr.insert(0, tn.get("address", ""))
        local = ctk.CTkEntry(self.rows_frame, width=70, **_E)
        local.insert(0, str(tn.get("local", "") or ""))
        row = {"name": name, "proto": proto, "address": addr, "local": local}
        rm = ctk.CTkButton(self.rows_frame, text="✕", width=30, height=30,
                           fg_color=theme.PANEL_2, hover_color=theme.RED,
                           text_color=theme.TEXT,
                           command=lambda: self._remove(row))
        row["rm"] = rm
        for j, w in enumerate((name, proto, addr, local, rm)):
            w.grid(row=r, column=j, sticky="ew", padx=3, pady=2)
        self._rows.append(row)

    def _remove(self, row):
        for k in ("name", "proto", "address", "local", "rm"):
            row[k].destroy()
        self._rows.remove(row)

    def get(self) -> list:
        return tn_mod.clean([{
            "name": r["name"].get(), "proto": r["proto"].get().lower(),
            "address": r["address"].get(), "local": r["local"].get(),
        } for r in self._rows])
