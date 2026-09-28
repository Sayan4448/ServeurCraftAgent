"""Fenêtre de configuration d'un serveur : server.properties, RAM/port,
mode de comptes (premium/crack), et Simple Voice Chat."""
import json
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from ..core import server_manager as sm
from ..core.properties import load_properties, update_properties
from ..i18n import t
from . import theme

_ENTRY = dict(fg_color=theme.PANEL_2, border_color=theme.BORDER,
              text_color=theme.TEXT)

# (clé server.properties, i18n, type)  type: entry|bool|menu
_PROPS = [
    ("motd", "ss_motd", "entry", None),
    ("difficulty", "ss_difficulty", "menu",
     ["peaceful", "easy", "normal", "hard"]),
    ("gamemode", "ss_gamemode", "menu",
     ["survival", "creative", "adventure", "spectator"]),
    ("pvp", "ss_pvp", "bool", None),
    ("enable-command-block", "ss_cmdblock", "bool", None),
    ("white-list", "ss_whitelist", "bool", None),
    ("allow-nether", "ss_nether", "bool", None),
    ("spawn-monsters", "ss_monsters", "bool", None),
    ("allow-flight", "ss_flight", "bool", None),
    ("view-distance", "ss_view", "entry", None),
    ("simulation-distance", "ss_sim", "entry", None),
    ("spawn-protection", "ss_spawnprot", "entry", None),
    ("hardcore", "ss_hardcore", "bool", None),
    ("force-gamemode", "ss_forcegm", "bool", None),
]


def _voicechat_props(server_dir: Path):
    for rel in ("plugins/voicechat/voicechat-server.properties",
                "config/voicechat/voicechat-server.properties"):
        p = server_dir / rel
        if p.exists():
            return p
    return None


class ServerSettings(ctk.CTkToplevel):
    def __init__(self, master, meta: dict):
        super().__init__(master)
        self.meta = meta
        self.dir = Path(meta["dir"])
        self.title(t("ss_title", name=meta["name"]))
        self.geometry("560x620")
        self.configure(fg_color=theme.BG)
        self.transient(master)

        self.props = load_properties(self.dir / "server.properties")
        self._widgets = {}

        scroll = ctk.CTkScrollableFrame(self, fg_color=theme.BG)
        scroll.pack(fill="both", expand=True, padx=10, pady=10)

        # -------------------------------------------------------- général
        self._section(scroll, t("ss_general"))
        self._field(scroll, t("ss_ram"), "ram",
                    str(round(int(meta.get("ram_mb", 4096)) / 1024, 1)
                        ).rstrip("0").rstrip("."))
        self._field(scroll, t("ss_port"), "port", str(meta.get("port", 25565)))
        self._field(scroll, t("ss_max_players"), "max_players",
                    self.props.get("max-players", "20"))

        row = ctk.CTkFrame(scroll, fg_color=theme.PANEL, corner_radius=8)
        row.pack(fill="x", padx=4, pady=3)
        ctk.CTkLabel(row, text=t("ss_accounts"), width=170, anchor="w",
                     text_color=theme.MUTED).pack(side="left", padx=10)
        acc_init = meta.get("accounts") or (
            "premium" if self.props.get("online-mode") == "true" else "both")
        self.accounts_seg = ctk.CTkSegmentedButton(
            row, values=[t("acc_premium"), t("acc_crack"), t("acc_both")],
            selected_color=theme.ACCENT,
            selected_hover_color=theme.ACCENT_HOVER,
            unselected_color=theme.PANEL_2,
            unselected_hover_color=theme.HOVER,
            command=lambda _v: self._acc_hint_update())
        self.accounts_seg.set(
            {"premium": t("acc_premium"), "crack": t("acc_crack")}
            .get(acc_init, t("acc_both")))
        self.accounts_seg.pack(side="left", padx=8, pady=8)
        self.acc_hint = ctk.CTkLabel(
            scroll, text=t("acc_both_hint"), font=(theme.FONT, 10),
            text_color=theme.ORANGE, wraplength=480, justify="left")
        self.acc_hint.pack(anchor="w", padx=10, pady=(0, 4))
        self._acc_hint_update()

        # -------------------------------------------------------- gameplay
        self._section(scroll, t("ss_gameplay"))
        for key, label, kind, values in _PROPS[:7]:
            self._prop_row(scroll, key, label, kind, values)

        # ------------------------------------------------------------- monde
        self._section(scroll, t("ss_world"))
        for key, label, kind, values in _PROPS[7:]:
            self._prop_row(scroll, key, label, kind, values)

        # propriété libre
        row = ctk.CTkFrame(scroll, fg_color=theme.PANEL, corner_radius=8)
        row.pack(fill="x", padx=4, pady=3)
        self._free_props = {}
        self.free_entry = ctk.CTkEntry(
            row, placeholder_text=t("ss_advanced"), **_ENTRY)
        self.free_entry.pack(side="left", fill="x", expand=True,
                             padx=8, pady=8)
        ctk.CTkButton(row, text=t("ss_advanced_add"), width=80, height=28,
                      fg_color=theme.PANEL_2, hover_color=theme.HOVER,
                      command=self._add_free).pack(side="right", padx=8)
        self.free_list = ctk.CTkLabel(
            scroll, text="", text_color=theme.MUTED,
            font=(theme.FONT, 10), justify="left", wraplength=480)
        self.free_list.pack(anchor="w", padx=10)

        # ------------------------------------------------------ voice chat
        self._section(scroll, t("ss_voice"))
        self.vc_path = _voicechat_props(self.dir)
        if self.vc_path:
            vc = load_properties(self.vc_path)
            self._field(scroll, t("ss_vc_port"), "vc_port",
                        vc.get("port", "24454"))
            self._field(scroll, t("ss_vc_host"), "vc_host",
                        vc.get("voice_host", ""))
        else:
            ctk.CTkLabel(scroll, text=t("ss_vc_none"), text_color=theme.MUTED,
                         font=(theme.FONT, 11)).pack(anchor="w", padx=10,
                                                    pady=4)

        # ------------------------------------------------------------ bas
        self.status = ctk.CTkLabel(self, text="", text_color=theme.GREEN,
                                   font=(theme.FONT, 11))
        self.status.pack(anchor="w", padx=16)
        ctk.CTkButton(self, text=t("ss_apply"), height=38,
                      font=(theme.FONT, 13, "bold"), fg_color=theme.GREEN,
                      hover_color="#16a34a", text_color="#06210f",
                      command=self._save).pack(fill="x", padx=14,
                                               pady=(4, 12))

    def _section(self, parent, text):
        ctk.CTkLabel(parent, text=text, font=(theme.FONT, 13, "bold"),
                     text_color=theme.ACCENT, anchor="w").pack(
            fill="x", padx=4, pady=(12, 4))

    def _field(self, parent, label, key, value):
        row = ctk.CTkFrame(parent, fg_color=theme.PANEL, corner_radius=8)
        row.pack(fill="x", padx=4, pady=3)
        ctk.CTkLabel(row, text=label, width=170, anchor="w",
                     text_color=theme.MUTED).pack(side="left", padx=10)
        e = ctk.CTkEntry(row, **_ENTRY)
        e.insert(0, value)
        e.pack(side="left", fill="x", expand=True, padx=8, pady=8)
        self._widgets[key] = e

    def _prop_row(self, parent, key, label, kind, values):
        row = ctk.CTkFrame(parent, fg_color=theme.PANEL, corner_radius=8)
        row.pack(fill="x", padx=4, pady=3)
        ctk.CTkLabel(row, text=t(label), width=170, anchor="w",
                     text_color=theme.MUTED).pack(side="left", padx=10)
        cur = self.props.get(key, "")
        if kind == "bool":
            w = ctk.CTkSwitch(row, text="", progress_color=theme.ACCENT)
            if cur == "true":
                w.select()
            w.pack(side="left", padx=8, pady=8)
        elif kind == "menu":
            w = ctk.CTkOptionMenu(
                row, values=values, width=180, fg_color=theme.PANEL_2,
                button_color=theme.ACCENT,
                button_hover_color=theme.ACCENT_HOVER,
                text_color=theme.TEXT)
            w.set(cur if cur in values else values[0])
            w.pack(side="left", padx=8, pady=8)
        else:
            w = ctk.CTkEntry(row, **_ENTRY)
            w.insert(0, cur)
            w.pack(side="left", fill="x", expand=True, padx=8, pady=8)
        self._widgets[key] = w

    def _acc_hint_update(self):
        if self.accounts_seg.get() == t("acc_both"):
            self.acc_hint.configure(text=t("acc_both_hint"))
        else:
            self.acc_hint.configure(text="")

    def _add_free(self):
        text = self.free_entry.get().strip()
        if "=" in text:
            k, _, v = text.partition("=")
            self._free_props[k.strip()] = v.strip()
            self.free_list.configure(
                text="  ·  ".join(f"{k}={v}" for k, v
                                 in self._free_props.items()))
            self.free_entry.delete(0, "end")

    def _save(self):
        changes = dict(self._free_props)
        for key, label, kind, _v in _PROPS:
            w = self._widgets[key]
            if kind == "bool":
                changes[key] = "true" if w.get() else "false"
            elif kind == "menu":
                changes[key] = w.get()
            else:
                changes[key] = w.get().strip()
        # comptes : premium → online-mode true ; crack / les deux → false
        acc_label = self.accounts_seg.get()
        accounts = ("premium" if acc_label == t("acc_premium")
                    else "crack" if acc_label == t("acc_crack") else "both")
        changes["online-mode"] = "true" if accounts == "premium" else "false"
        changes["server-port"] = self._widgets["port"].get().strip() or "25565"
        changes["max-players"] = (
            self._widgets["max_players"].get().strip() or "20")
        try:
            update_properties(self.dir / "server.properties", changes)
        except OSError as e:
            messagebox.showerror(t("ss_title", name=self.meta["name"]), str(e),
                                 parent=self)
            return

        # métadonnées (RAM + port pour le lancement)
        try:
            self.meta["ram_mb"] = int(
                float(self._widgets["ram"].get().replace(",", ".")) * 1024)
        except ValueError:
            self.meta["ram_mb"] = 4096
        self.meta["accounts"] = accounts
        self.meta["online_mode"] = accounts == "premium"
        self.meta["port"] = int(changes["server-port"])
        (self.dir / sm.META_FILE).write_text(
            json.dumps({k: v for k, v in self.meta.items()
                        if k not in ("dir", "running")},
                       indent=2), encoding="utf-8")

        # voice chat
        if self.vc_path:
            update_properties(self.vc_path, {
                "port": self._widgets["vc_port"].get().strip() or "24454",
                "voice_host": self._widgets["vc_host"].get().strip(),
            })
        self.status.configure(text=t("ss_saved"))
