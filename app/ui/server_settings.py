"""Fenêtre de configuration d'un serveur : server.properties, RAM/port,
mode de comptes (premium/crack), et Simple Voice Chat."""
import json
import threading
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from ..core import crossplay, scheduler
from ..core import server_manager as sm
from ..core import tunnels as tunnels_mod
from ..core.backups import DEFAULT_KEEP
from ..core.properties import (load_properties, parse_count, parse_port,
                               parse_ram_mb, update_properties)
from ..i18n import t
from . import theme
from .schedule_editor import ScheduleEditor
from .playit_panel import PlayitPanel
from .tunnels_editor import TunnelsEditor
from .uithread import ui_call

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
    def __init__(self, master, meta: dict, on_saved=None):
        super().__init__(master)
        self.meta = dict(meta)
        self.on_saved = on_saved
        self.dir = Path(meta["dir"])
        try:                          # métas à jour depuis le disque
            disk = json.loads((self.dir / sm.META_FILE).read_text(
                encoding="utf-8"))
            self.meta.update(disk)
            self.meta["dir"] = str(self.dir)
        except (OSError, ValueError):
            pass
        meta = self.meta
        self.title(t("ss_title", name=meta["name"]))
        self.geometry("640x680")
        self.minsize(560, 480)
        self.configure(fg_color=theme.BG)
        self.transient(master)
        self.after(100, self.lift)

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

        # ------------------------------------------- joueurs & plateformes
        self._section(scroll, t("ss_players_platforms"))
        box = ctk.CTkFrame(scroll, fg_color=theme.PANEL, corner_radius=8)
        box.pack(fill="x", padx=4, pady=3)
        ctk.CTkLabel(box, text=t("ss_accounts"), anchor="w",
                     text_color=theme.MUTED).pack(fill="x", padx=12,
                                                  pady=(10, 4))
        acc_init = meta.get("accounts") or (
            "premium" if self.props.get("online-mode") == "true" else "both")
        self._acc_init = acc_init
        self.accounts_seg = ctk.CTkSegmentedButton(
            box, values=[t("acc_crack"), t("acc_premium"), t("acc_both")],
            selected_color=theme.SEL, text_color=theme.TEXT,
            selected_hover_color=theme.SEL_HOVER,
            unselected_color=theme.PANEL_2,
            unselected_hover_color=theme.HOVER,
            command=lambda _v: self._acc_hint_update())
        self.accounts_seg.set(
            {"premium": t("acc_premium"), "crack": t("acc_crack")}
            .get(acc_init, t("acc_both")))
        self.accounts_seg.pack(fill="x", padx=12)
        self.acc_hint = ctk.CTkLabel(
            box, text="", font=(theme.FONT, 10), text_color=theme.MUTED,
            wraplength=540, justify="left", anchor="w")
        self.acc_hint.pack(fill="x", padx=12, pady=(4, 8))

        self._cp_init = bool(meta.get("crossplay")) or \
            crossplay.installed(self.dir)
        self.cp_switch = ctk.CTkSwitch(
            box, text=t("cp_switch"), text_color=theme.TEXT,
            font=(theme.FONT, 12, "bold"), progress_color=theme.GREEN)
        if self._cp_init:
            self.cp_switch.select()
        if not crossplay.supported(meta.get("loader", "")):
            self.cp_switch.configure(state="disabled")
        self.cp_switch.pack(anchor="w", padx=12)
        ctk.CTkLabel(
            box, text=t("cp_hint") if crossplay.supported(
                meta.get("loader", "")) else t("cp_unsupported"),
            font=(theme.FONT, 10), text_color=theme.MUTED, wraplength=540,
            justify="left", anchor="w").pack(fill="x", padx=12, pady=(2, 10))
        self._acc_hint_update()

        # ------------------------------------------------ tunnels Playit
        self._section(scroll, t("tn_section"))
        tbox = ctk.CTkFrame(scroll, fg_color=theme.PANEL, corner_radius=8)
        tbox.pack(fill="x", padx=4, pady=3)
        auto = ctk.CTkFrame(tbox, fg_color="transparent")
        auto.pack(fill="x", padx=10, pady=(10, 0))
        self.playit_switch = ctk.CTkSwitch(
            auto, text=t("pl_auto_switch"), text_color=theme.TEXT,
            progress_color=theme.ACCENT)
        if meta.get("playit_auto"):
            self.playit_switch.select()
        self.playit_switch.pack(side="left")
        ctk.CTkButton(auto, text=t("pl_auto_btn"), height=30, width=0,
                      fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                      text_color=theme.ON_ACCENT,
                      command=self._playit_now).pack(side="right")
        self.tunnels_editor = TunnelsEditor(tbox, meta.get("tunnels") or [])
        self.tunnels_editor.pack(fill="x", padx=10, pady=(10, 10))

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

        # ------------------------------------------------------ sauvegardes
        self._section(scroll, t("ss_backups"))
        self._switch(scroll, t("ss_bk_on_stop"), "backup_on_stop",
                     meta.get("backup_on_stop", True))
        self._field(scroll, t("ss_bk_interval"), "backup_interval_min",
                    str(meta.get("backup_interval_min", 0)))
        self._field(scroll, t("ss_bk_keep"), "backup_keep",
                    str(meta.get("backup_keep", DEFAULT_KEEP)))
        self._hint(scroll, t("ss_bk_hint"))

        # ------------------------------------------------ tâches planifiées
        self._section(scroll, t("ss_sched"))
        self._field(scroll, t("ss_restart_time"), "restart_time",
                    meta.get("restart_time", ""))
        self._hint(scroll, t("ss_restart_hint"))
        sbox = ctk.CTkFrame(scroll, fg_color=theme.PANEL, corner_radius=8)
        sbox.pack(fill="x", padx=4, pady=3)
        self.schedule_editor = ScheduleEditor(
            sbox, meta.get("scheduled_commands") or [])
        self.schedule_editor.pack(fill="x", padx=10, pady=10)

        # ------------------------------------------------ détection de crash
        self._section(scroll, t("ss_crash"))
        row = ctk.CTkFrame(scroll, fg_color=theme.PANEL, corner_radius=8)
        row.pack(fill="x", padx=4, pady=3)
        ctk.CTkLabel(row, text=t("ss_crash_action"), width=170, anchor="w",
                     text_color=theme.MUTED).pack(side="left", padx=10)
        self._crash_labels = {a: t(f"cr_act_{a}") for a in sm.CRASH_ACTIONS}
        self.crash_seg = ctk.CTkSegmentedButton(
            row, values=list(self._crash_labels.values()),
            selected_color=theme.SEL, text_color=theme.TEXT,
            selected_hover_color=theme.SEL_HOVER,
            unselected_color=theme.PANEL_2,
            unselected_hover_color=theme.HOVER)
        self.crash_seg.set(self._crash_labels.get(
            meta.get("crash_action"), self._crash_labels["ask"]))
        self.crash_seg.pack(side="left", padx=8, pady=8)
        self._field(scroll, t("ss_crash_max"), "crash_max_restarts",
                    str(meta.get("crash_max_restarts",
                                 sm.DEFAULT_CRASH_MAX)))
        self._hint(scroll, t("ss_crash_hint", min=sm.CRASH_WINDOW // 60))

        # ------------------------------------------------------------ bas
        self.status = ctk.CTkLabel(self, text="", text_color=theme.GREEN,
                                   font=(theme.FONT, 11))
        self.status.pack(anchor="w", padx=16)
        ctk.CTkButton(self, text=t("ss_apply"), height=38,
                      font=(theme.FONT, 13, "bold"), fg_color=theme.GREEN,
                      hover_color=theme.GREEN_HOVER, text_color=theme.ON_GREEN,
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

    def _switch(self, parent, label, key, value):
        row = ctk.CTkFrame(parent, fg_color=theme.PANEL, corner_radius=8)
        row.pack(fill="x", padx=4, pady=3)
        w = ctk.CTkSwitch(row, text=label, text_color=theme.TEXT,
                          progress_color=theme.ACCENT)
        if value:
            w.select()
        w.pack(side="left", padx=10, pady=8)
        self._widgets[key] = w

    def _hint(self, parent, text):
        ctk.CTkLabel(parent, text=text, font=(theme.FONT, 10),
                     text_color=theme.MUTED, wraplength=560, justify="left",
                     anchor="w").pack(fill="x", padx=10, pady=(2, 4))

    def _int(self, key, default, lo=0):
        try:
            return max(lo, int(float(self._widgets[key].get().strip()
                                     .replace(",", "."))))
        except ValueError:
            return default

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
        v = self.accounts_seg.get()
        key = ("acc_premium_hint" if v == t("acc_premium")
               else "acc_crack_hint" if v == t("acc_crack")
               else "acc_both_hint")
        self.acc_hint.configure(text=t(key))

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
        restart_raw = self._widgets["restart_time"].get().strip()
        restart_hm = scheduler.parse_hhmm(restart_raw)
        try:
            if restart_raw and not restart_hm:
                raise ValueError(t("sch_bad_time", v=restart_raw))
            tasks = self.schedule_editor.get()
        except ValueError as e:
            messagebox.showerror(t("ss_sched"), str(e), parent=self)
            return
        # rien n'est écrit tant qu'une valeur est invalide : un port non
        # numérique ou une RAM à 0 empêchait le serveur de démarrer
        ram_mb = parse_ram_mb(self._widgets["ram"].get())
        port = parse_port(self._widgets["port"].get().strip() or "25565")
        max_players = parse_count(
            self._widgets["max_players"].get().strip() or "20")
        for value, message in ((ram_mb, t("cre_bad_ram")),
                               (port, t("cre_bad_port")),
                               (max_players, t("ss_bad_players"))):
            if value is None:
                messagebox.showerror(t("ss_title", name=self.meta["name"]),
                                     message, parent=self)
                return
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
        changes["server-port"] = str(port)
        changes["max-players"] = str(max_players)
        try:
            update_properties(self.dir / "server.properties", changes)
        except OSError as e:
            messagebox.showerror(t("ss_title", name=self.meta["name"]), str(e),
                                 parent=self)
            return

        # métadonnées (RAM + port pour le lancement)
        self.meta["ram_mb"] = ram_mb
        self.meta["accounts"] = accounts
        self.meta["online_mode"] = accounts == "premium"
        self.meta["port"] = port
        want_cp = bool(self.cp_switch.get())
        cp_locked = False
        if not want_cp and crossplay.installed(self.dir):
            try:
                crossplay.uninstall(self.dir, self.meta.get("loader", ""))
            except crossplay.CrossplayError:
                # jars utilisés par le serveur lancé : le cross-play reste
                # activé, le reste de la configuration est enregistré
                want_cp = cp_locked = True
                self.cp_switch.select()
        self.meta["crossplay"] = want_cp
        self.meta["tunnels"] = self.tunnels_editor.get()
        self.meta["playit_auto"] = bool(self.playit_switch.get())
        self.meta["backup_on_stop"] = bool(
            self._widgets["backup_on_stop"].get())
        self.meta["backup_interval_min"] = self._int("backup_interval_min", 0)
        self.meta["backup_keep"] = self._int("backup_keep", DEFAULT_KEEP, 1)
        self.meta["restart_time"] = (scheduler.fmt_hhmm(restart_hm)
                                     if restart_hm else "")
        self.meta["scheduled_commands"] = tasks
        self.meta["crash_action"] = next(
            (a for a, lbl in self._crash_labels.items()
             if lbl == self.crash_seg.get()), "ask")
        self.meta["crash_max_restarts"] = self._int(
            "crash_max_restarts", sm.DEFAULT_CRASH_MAX, 1)
        self._write_meta()
        tunnels_mod.apply(self.dir, self.meta.get("loader", ""),
                          self.meta["tunnels"], java_port=self.meta["port"],
                          voice=self.meta.get("voice", "none"))

        # voice chat
        if self.vc_path:
            update_properties(self.vc_path, {
                "port": self._widgets["vc_port"].get().strip() or "24454",
                "voice_host": self._widgets["vc_host"].get().strip(),
            })

        # cross-play / sécurité : téléchargements en arrière-plan
        loader, mc = self.meta.get("loader", ""), self.meta.get("mc_version")
        jobs = []
        if want_cp and not crossplay.installed(self.dir):
            jobs.append(lambda log: crossplay.install(self.dir, loader, mc,
                                                      log=log))
        if accounts == "both" and not self._has_auth():
            jobs.append(lambda log: crossplay.install_auth(self.dir, loader,
                                                           mc, log=log))
        if jobs:
            self.status.configure(text=t("cp_installing"),
                                  text_color=theme.ORANGE)

            def work():
                msgs = []
                ok = True
                for job in jobs:
                    try:
                        job(msgs.append)
                    except Exception as e:  # noqa: BLE001
                        ok = False
                        msgs.append(f"✖ {e}")
                if not ok and want_cp:
                    self.meta["crossplay"] = crossplay.installed(self.dir)
                    self._write_meta()
                ui_call(self, self._jobs_done, ok, msgs[-1] if msgs else "")
            threading.Thread(target=work, daemon=True).start()
        elif cp_locked:
            self.status.configure(text=t("cp_locked"),
                                  text_color=theme.ORANGE)
        else:
            self.status.configure(text=t("ss_saved"), text_color=theme.GREEN)
        if self.on_saved:
            self.on_saved()

    def _jobs_done(self, ok, last):
        self.status.configure(
            text=(t("ss_saved") if ok else last),
            text_color=theme.GREEN if ok else theme.RED)
        if self.on_saved:
            self.on_saved()

    def _has_auth(self) -> bool:
        for sub in ("plugins", "mods"):
            d = self.dir / sub
            if d.exists() and any(f.name.lower().startswith(
                    ("authme", "easyauth")) for f in d.glob("*.jar")):
                return True
        return False

    def _playit_now(self):
        """Tunnels TCP/UDP créés automatiquement (panneau Playit) ; l'éditeur
        et l'interrupteur reprennent ensuite ce qui a été enregistré."""
        def done():
            try:
                disk = json.loads((self.dir / sm.META_FILE).read_text(
                    encoding="utf-8"))
            except (OSError, ValueError):
                return
            self.meta["tunnels"] = disk.get("tunnels") or []
            self.meta["playit_auto"] = True
            if self.winfo_exists():
                self.tunnels_editor.load(self.meta["tunnels"])
                self.playit_switch.select()
        PlayitPanel.show(self, sm.get_process(self.meta["name"]),
                         on_done=done)

    def _write_meta(self):
        (self.dir / sm.META_FILE).write_text(
            json.dumps({k: v for k, v in self.meta.items()
                        if k not in ("dir", "running")},
                       indent=2), encoding="utf-8")
