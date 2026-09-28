"""Onglet « Mes Serveurs » : liste · tableau de bord · console · joueurs.

Règle : aucun appel Tk depuis un thread. Console, joueurs et statut sont lus
dans `ServerProcess` par `_pump()` (toutes les 150 ms, thread Tk).
"""
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from ..config import load_settings
from ..core import players as pl
from ..core import server_manager as sm
from ..core.crossplay import BEDROCK_PORT
from ..core.downloader import LOADER_LABELS
from ..core.properties import load_properties
from ..core.server_net import local_ip, playit_address, public_ip
from .player_card import PlayerCard
from ..i18n import t
from . import theme
from .mods_manager import ModsManager
from .players_panel import BansView, OpsView, ctx_for
from .server_settings import ServerSettings
from .server_window import ServerWindow

_TAG_COLORS = {"err": ("#dc2626", "#f87171"), "warn": ("#b45309", "#fbbf24"),
               "info": theme.ACCENT}


def _ask(win, title, prompt, cb):
    d = ctk.CTkInputDialog(text=prompt, title=title)
    d.geometry("+%d+%d" % (win.winfo_rootx() + 80, win.winfo_rooty() + 120))
    val = d.get_input()
    if val is not None:
        cb(val)


def _sys_ram():
    try:
        import psutil
        vm = psutil.virtual_memory()
        return vm.used / 1024 ** 3, vm.total / 1024 ** 3
    except Exception:  # noqa: BLE001
        return None


class StatCard(ctk.CTkFrame):
    """Petite carte : titre, valeur, barre de progression, sous-texte."""

    def __init__(self, master, title, color):
        super().__init__(master, fg_color=theme.PANEL, corner_radius=12,
                         border_width=1, border_color=theme.BORDER)
        self.color = color
        ctk.CTkLabel(self, text=title, font=(theme.FONT, 11),
                     text_color=theme.MUTED, anchor="w").pack(
            fill="x", padx=12, pady=(10, 0))
        self.value = ctk.CTkLabel(self, text="—", font=(theme.FONT, 18, "bold"),
                                  text_color=theme.TEXT, anchor="w")
        self.value.pack(fill="x", padx=12)
        self.bar = ctk.CTkProgressBar(self, height=6, corner_radius=3,
                                      progress_color=color,
                                      fg_color=theme.PANEL_2)
        self.bar.set(0)
        self.bar.pack(fill="x", padx=12, pady=(4, 2))
        self.sub = ctk.CTkLabel(self, text=" ", font=(theme.FONT, 10),
                                text_color=theme.MUTED, anchor="w")
        self.sub.pack(fill="x", padx=12, pady=(0, 8))

    def set(self, value, frac=None, sub=" ", warn=False):
        self.value.configure(text=value)
        if frac is not None:
            self.bar.set(max(0.0, min(1.0, frac)))
            self.bar.configure(progress_color=theme.RED if warn
                               else self.color)
        self.sub.configure(text=sub)


class ServersTab(ctk.CTkFrame):
    def __init__(self, master, on_new=None):
        super().__init__(master, fg_color="transparent")
        self.on_new = on_new
        self.grid_columnconfigure(0, weight=0, minsize=230)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=0, minsize=230)
        self.grid_rowconfigure(0, weight=1)

        self.meta: dict | None = None
        self.proc: sm.ServerProcess | None = None
        self._seen = 0
        self._last_players = None
        self._last_running = None
        self._last_ui_state = None
        self._cards: dict[str, ctk.CTkFrame] = {}
        self._dots: dict[str, list] = {}
        self._pub_ip: str | None = None
        self._ip_dirty = False
        self._tick = 0
        self._max_players = 20

        self._build_list_col()
        self._build_main_col()
        self._build_players_col()

        self.refresh()
        metas = sm.list_servers()
        if metas:
            self._select(metas[0])
        else:
            self._update_state()
        self._pump()

    # ============================================================ layout
    def _build_list_col(self):
        col = theme.card(self)
        col.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        col.grid_rowconfigure(1, weight=1)
        col.grid_columnconfigure(0, weight=1)

        head = ctk.CTkFrame(col, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        ctk.CTkLabel(head, text=t("srv_my"), font=(theme.FONT, 14, "bold"),
                     text_color=theme.TEXT).pack(side="left")
        ctk.CTkButton(head, text="＋", width=32, height=28,
                      font=(theme.FONT, 14, "bold"), fg_color=theme.ACCENT,
                      hover_color=theme.ACCENT_HOVER,
                      command=lambda: self.on_new and self.on_new()).pack(
            side="right")

        self.list_scroll = ctk.CTkScrollableFrame(
            col, fg_color="transparent",
            scrollbar_button_color=theme.PANEL_2,
            scrollbar_button_hover_color=theme.HOVER)
        self.list_scroll.grid(row=1, column=0, sticky="nsew", padx=6)
        self.list_scroll.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(col, text="🗑  " + t("srv_delete"), height=32,
                      fg_color="transparent", border_width=1,
                      border_color=theme.RED, text_color=theme.RED,
                      hover_color=theme.PANEL_2, font=(theme.FONT, 12),
                      command=self._delete).grid(
            row=2, column=0, sticky="ew", padx=12, pady=12)

    def _build_main_col(self):
        col = ctk.CTkFrame(self, fg_color="transparent")
        col.grid(row=0, column=1, sticky="nsew", padx=(0, 10))
        col.grid_columnconfigure(0, weight=1)
        col.grid_rowconfigure(3, weight=1)

        # ---------------------------------------------------- en-tête
        head = theme.card(col)
        head.grid(row=0, column=0, sticky="ew")
        head.grid_columnconfigure(0, weight=1)
        top = ctk.CTkFrame(head, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 0))
        self.sel_label = ctk.CTkLabel(
            top, text=t("srv_none_sel"), font=(theme.FONT, 20, "bold"),
            text_color=theme.TEXT, anchor="w")
        self.sel_label.pack(side="left")
        self.state_pill = ctk.CTkLabel(
            top, text="", font=(theme.FONT, 11, "bold"), corner_radius=10,
            fg_color=theme.PANEL_2, text_color=theme.MUTED, height=24)
        self.state_pill.pack(side="left", padx=12)
        self.info_label = ctk.CTkLabel(head, text="", font=(theme.FONT, 12),
                                       text_color=theme.MUTED, anchor="w")
        self.info_label.grid(row=1, column=0, sticky="w", padx=16)

        self.ip_row = ctk.CTkFrame(head, fg_color="transparent")
        self.ip_row.grid(row=2, column=0, sticky="w", padx=12, pady=(6, 0))
        self._ip_chips: list[ctk.CTkButton] = []
        self.ip_hint = ctk.CTkLabel(head, text="", font=(theme.FONT, 10),
                                    text_color=theme.MUTED, anchor="w",
                                    justify="left")
        self.ip_hint.grid(row=3, column=0, sticky="w", padx=16,
                          pady=(2, 10))

        # ---------------------------------------------------- stats
        stats = ctk.CTkFrame(col, fg_color="transparent")
        stats.grid(row=1, column=0, sticky="ew", pady=10)
        stats.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="s")
        self.st_ram = StatCard(stats, t("stat_ram"), theme.ACCENT)
        self.st_cpu = StatCard(stats, t("stat_cpu"), theme.PURPLE)
        self.st_players = StatCard(stats, t("stat_players"), theme.GREEN)
        self.st_uptime = StatCard(stats, t("stat_uptime"), theme.ORANGE)
        for i, w in enumerate((self.st_ram, self.st_cpu, self.st_players,
                               self.st_uptime)):
            w.grid(row=0, column=i, sticky="nsew",
                   padx=(0 if i == 0 else 5, 0 if i == 3 else 5))

        # ---------------------------------------------------- actions
        acts = ctk.CTkFrame(col, fg_color="transparent")
        acts.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        acts.grid_columnconfigure((0, 1, 2, 3, 4, 5), weight=1, uniform="b")
        self._btns = {}
        specs = [
            ("srv_start", "▶  " + t("srv_start_lbl"), self._start),
            ("srv_stop", "■  " + t("srv_stop"), self._stop),
            ("srv_restart", "⟳  " + t("srv_restart"), self._restart),
            ("srv_mods", "🧩  " + t("srv_mods_lbl"), self._open_mods),
            ("srv_settings", "⚙  " + t("srv_settings_lbl"),
             self._open_settings),
            ("srv_folder", "📁  " + t("srv_folder"), self._open_folder),
        ]
        for i, (key, text, cmd) in enumerate(specs):
            b = ctk.CTkButton(acts, text=text, command=cmd, height=40,
                              corner_radius=10,
                              font=(theme.FONT, 12, "bold"),
                              fg_color=theme.PANEL, border_width=1,
                              border_color=theme.BORDER,
                              hover_color=theme.HOVER, text_color=theme.TEXT)
            b.grid(row=0, column=i, sticky="ew",
                   padx=(0 if i == 0 else 3, 0 if i == 5 else 3))
            self._btns[key] = b

        # ---------------------------------------------------- console
        cons = theme.card(col)
        cons.grid(row=3, column=0, sticky="nsew")
        cons.grid_rowconfigure(1, weight=1)
        cons.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(cons, text=t("win_console"),
                     font=(theme.FONT, 13, "bold"),
                     text_color=theme.TEXT).grid(
            row=0, column=0, sticky="w", padx=14, pady=(10, 4))
        self.console = ctk.CTkTextbox(
            cons, font=(theme.FONT_MONO, 11), fg_color=theme.CONSOLE_BG,
            text_color=theme.CONSOLE_TEXT, corner_radius=8, state="disabled",
            wrap="none", border_width=1, border_color=theme.BORDER)
        self.console.grid(row=1, column=0, sticky="nsew", padx=12)
        row = ctk.CTkFrame(cons, fg_color="transparent")
        row.grid(row=2, column=0, sticky="ew", padx=12, pady=10)
        row.grid_columnconfigure(0, weight=1)
        self.cmd_entry = ctk.CTkEntry(
            row, placeholder_text=t("srv_cmd_ph"), height=34,
            fg_color=theme.PANEL_2, border_color=theme.BORDER,
            text_color=theme.TEXT)
        self.cmd_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.cmd_entry.bind("<Return>", lambda _e: self._send())
        ctk.CTkButton(row, text=t("srv_send"), width=96, height=34,
                      fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                      command=self._send).grid(row=0, column=1)

    def _build_players_col(self):
        col = theme.card(self)
        col.grid(row=0, column=2, sticky="nsew")
        col.grid_rowconfigure(2, weight=1)
        col.grid_columnconfigure(0, weight=1)
        self.players_title = ctk.CTkLabel(
            col, text=t("players_online", n=0), font=(theme.FONT, 14, "bold"),
            text_color=theme.TEXT)
        self.players_title.grid(row=0, column=0, sticky="w", padx=14,
                                pady=(12, 6))
        self._pviews = [t("pv_online"), t("pv_bans"), t("pv_ops")]
        self.pview_seg = ctk.CTkSegmentedButton(
            col, values=self._pviews, command=self._show_pview,
            selected_color=theme.SEL, text_color=theme.TEXT,
            selected_hover_color=theme.SEL_HOVER,
            unselected_color=theme.PANEL_2,
            unselected_hover_color=theme.HOVER)
        self.pview_seg.set(self._pviews[0])
        self.pview_seg.grid(row=1, column=0, sticky="ew", padx=10,
                            pady=(0, 8))
        self.players_scroll = ctk.CTkScrollableFrame(
            col, fg_color="transparent",
            scrollbar_button_color=theme.PANEL_2,
            scrollbar_button_hover_color=theme.HOVER)
        self.players_scroll.grid(row=2, column=0, sticky="nsew",
                                 padx=6, pady=(0, 10))
        self.players_scroll.grid_columnconfigure(0, weight=1)
        getctx = lambda: ctx_for(self.proc)  # noqa: E731
        self.bans_view = BansView(col, getctx)
        self.ops_view = OpsView(col, getctx)
        for v in (self.bans_view, self.ops_view):
            v.grid(row=2, column=0, sticky="nsew", padx=6, pady=(0, 10))
            v.grid_remove()

    def _show_pview(self, value):
        views = {self._pviews[0]: self.players_scroll,
                 self._pviews[1]: self.bans_view,
                 self._pviews[2]: self.ops_view}
        for k, v in views.items():
            if k == value:
                v.grid()
            else:
                v.grid_remove()
        if value != self._pviews[0]:
            views[value].refresh()

    # ============================================================ liste
    def refresh(self):
        for w in self.list_scroll.winfo_children():
            w.destroy()
        self._cards.clear()
        self._dots.clear()
        metas = sm.list_servers()
        if not metas:
            ctk.CTkLabel(self.list_scroll, text=t("srv_empty"),
                         text_color=theme.MUTED, justify="left",
                         wraplength=190).grid(
                row=0, column=0, sticky="w", padx=6, pady=6)
            return
        sel = self.meta["name"] if self.meta else None
        for i, meta in enumerate(metas):
            selected = meta["name"] == sel
            card = ctk.CTkFrame(
                self.list_scroll, corner_radius=10, border_width=1,
                fg_color=theme.PANEL_2 if selected else "transparent",
                border_color=theme.ACCENT if selected else theme.BORDER)
            card.grid(row=i, column=0, sticky="ew", pady=3, padx=2)
            card.grid_columnconfigure(1, weight=1)
            self._cards[meta["name"]] = card
            running = bool(meta.get("running"))
            dot = ctk.CTkLabel(card, text="●", width=16,
                               font=(theme.FONT, 14),
                               text_color=theme.GREEN if running
                               else theme.DISABLED)
            dot.grid(row=0, column=0, rowspan=2, padx=(10, 4))
            lbl = ctk.CTkLabel(card, text=meta["name"],
                               font=(theme.FONT, 13, "bold"),
                               text_color=theme.TEXT, anchor="w")
            lbl.grid(row=0, column=1, sticky="w", pady=(8, 0))
            loader = LOADER_LABELS.get(meta["loader"], meta["loader"])
            sub = ctk.CTkLabel(
                card, text=f"{loader} · {meta['mc_version']}",
                font=(theme.FONT, 10), text_color=theme.MUTED, anchor="w")
            sub.grid(row=1, column=1, sticky="w", pady=(0, 8))
            self._dots[meta["name"]] = [dot, running]
            for w in (card, lbl, sub, dot, *card.winfo_children()):
                w.bind("<Button-1>", lambda _e, m=meta: self._select(m))

    def select_by_name(self, name: str):
        self.refresh()
        for meta in sm.list_servers():
            if meta["name"] == name:
                self._select(meta)
                return

    def _select(self, meta: dict):
        self.meta = meta
        self.proc = sm.get_process(meta["name"])
        self.proc.reload_meta()
        for name, card in self._cards.items():
            sel = name == meta["name"]
            card.configure(fg_color=theme.PANEL_2 if sel else "transparent",
                           border_color=theme.ACCENT if sel else theme.BORDER)
        self.sel_label.configure(text=meta["name"])
        self._refresh_info()
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")
        lines, self._seen = self.proc.lines_since(0)
        self._append_many(lines)
        self._last_players = None
        self._last_running = None
        self._last_ui_state = None
        self._update_state()
        self._update_stats()
        self._show_ip()
        self._refresh_players()
        self._show_pview(self.pview_seg.get())

    def _refresh_info(self):
        m = self.proc.meta
        props = load_properties(Path(m.get("dir", self.proc.path))
                                / "server.properties")
        try:
            self._max_players = int(props.get("max-players", 20))
        except ValueError:
            self._max_players = 20
        acc = {"premium": t("acc_premium"), "crack": t("acc_crack")}.get(
            m.get("accounts"), t("acc_both"))
        loader = LOADER_LABELS.get(m["loader"], m["loader"])
        parts = [loader, f"MC {m['mc_version']}", acc]
        if m.get("crossplay"):
            parts.append("Java + Bedrock")
        self.info_label.configure(text="  ·  ".join(parts))

    # ============================================================ IP
    def _show_ip(self):
        for c in self._ip_chips:
            c.destroy()
        self._ip_chips.clear()
        if not self.meta:
            self.ip_hint.configure(text="")
            return
        m = self.proc.meta
        ip = local_ip()
        port = m.get("port", 25565)
        tunnels = m.get("tunnels") or []
        java_tn = next((tn for tn in tunnels if tn["proto"] == "tcp"
                        and tn["local"] == port), None)
        bedrock_tn = (next((tn for tn in tunnels if tn["proto"] == "udp"
                            and tn["local"] == BEDROCK_PORT), None)
                      if m.get("crossplay") else None)
        legacy = (playit_address(Path(self.meta["dir"]))
                  if not tunnels else None)
        net_addr = (java_tn or {}).get("address") or legacy
        chips = [("Java", f"{ip}:{port}")]
        if m.get("crossplay"):
            chips.append(("Bedrock", f"{ip}:{BEDROCK_PORT}"))
        if net_addr:
            chips.append((t("ip_internet"), net_addr))
        elif self._pub_ip:
            chips.append((t("ip_public_short"), f"{self._pub_ip}:{port}"))
        else:
            chips.append((t("ip_public_short"), "…"))
        if bedrock_tn:
            chips.append((t("ip_bedrock_net"), bedrock_tn["address"]))
        for tn in tunnels:
            if tn is java_tn or tn is bedrock_tn:
                continue
            chips.append((f"Playit · {tn['name']}", tn["address"]))
        for i, (label, value) in enumerate(chips):
            b = ctk.CTkButton(
                self.ip_row, text=f"{label}   {value}", height=26,
                corner_radius=13, font=(theme.FONT_MONO, 11),
                fg_color=theme.PANEL_2, hover_color=theme.HOVER,
                text_color=theme.TEXT, width=0)
            b.configure(command=lambda v=value, w=b: self._copy(v, w))
            b.grid(row=i // 3, column=i % 3, sticky="w", padx=4, pady=2)
            self._ip_chips.append(b)
        self.ip_hint.configure(
            text=t("ip_hint_ok") if net_addr
            else t("ip_hint_wan", port=port))
        if not net_addr and not self._pub_ip and self._pub_ip is None:
            self._pub_ip = ""

            def _fetch():             # thread : pas de Tk
                self._pub_ip = public_ip() or ""
                self._ip_dirty = True
            threading.Thread(target=_fetch, daemon=True).start()

    def _copy(self, value, widget):
        if value == "…":
            return
        self.clipboard_clear()
        self.clipboard_append(value)
        old = widget.cget("text")
        widget.configure(text=f"✔ {t('copied')}")
        self.after(1200, lambda: widget.winfo_exists()
                   and widget.configure(text=old))

    # ============================================================ état
    def _update_state(self):
        proc = self.proc
        running = bool(proc and proc.is_running())
        starting = bool(proc and proc._starting)
        state = (proc is not None, running, starting)
        if state == self._last_ui_state:
            return
        self._last_ui_state = state
        if not proc:
            self.state_pill.configure(text="")
        elif running:
            self.state_pill.configure(text=f"  ● {t('srv_running')}  ",
                                      fg_color=theme.GREEN,
                                      text_color=theme.ON_GREEN)
        elif starting:
            self.state_pill.configure(
                text=f"  ◌ {t('srv_starting_short')}  ",
                fg_color=theme.ORANGE, text_color="#ffffff")
        else:
            self.state_pill.configure(text=f"  ○ {t('srv_stopped')}  ",
                                      fg_color=theme.PANEL_2,
                                      text_color=theme.MUTED)
        has = proc is not None
        theme.action_button(self._btns["srv_start"],
                            has and not running and not starting,
                            theme.GREEN, theme.GREEN_HOVER, theme.ON_GREEN)
        theme.action_button(self._btns["srv_stop"], running,
                            theme.RED, theme.RED_HOVER)
        theme.action_button(self._btns["srv_restart"], running,
                            theme.ORANGE, theme.ORANGE_HOVER)
        for k in ("srv_mods", "srv_settings", "srv_folder"):
            if has:
                self._btns[k].configure(state="normal", fg_color=theme.PANEL,
                                        text_color=theme.TEXT)
            else:
                theme.action_button(self._btns[k], False, None, None)

    def _update_stats(self):
        proc = self.proc
        limit_gb = (int(proc.meta.get("ram_mb", 4096)) / 1024) if proc else 0
        sysr = _sys_ram()
        sys_txt = (t("sys_ram", used=f"{sysr[0]:.1f}", total=f"{sysr[1]:.0f}")
                   if sysr else " ")
        st = proc.stats() if proc else None
        if st:
            used = st["ram_mb"] / 1024
            frac = used / limit_gb if limit_gb else 0
            self.st_ram.set(f"{used:.1f} / {limit_gb:g} Go", frac, sys_txt,
                            warn=frac > 0.9)
            self.st_cpu.set(f"{st['cpu']:.0f} %", st["cpu"] / 100,
                            t("cpu_hint"), warn=st["cpu"] > 90)
            self.st_uptime.set(theme.fmt_duration(st["uptime"]), 1.0, " ")
        else:
            self.st_ram.set(f"0 / {limit_gb:g} Go" if proc else "—", 0,
                            sys_txt)
            self.st_cpu.set("0 %" if proc else "—", 0, " ")
            self.st_uptime.set("—", 0, " ")
        n = len(proc.tracker.players) if proc else 0
        mx = self._max_players or 20
        self.st_players.set(f"{n} / {mx}", n / mx, " ")

    # ============================================================ actions
    def _start(self):
        proc = self.proc
        if not proc or proc.is_running() or proc._starting:
            return
        proc._starting = True
        proc.log(t("srv_starting", name=proc.name))
        self._update_state()

        def work():                   # thread : Java peut être téléchargé
            try:
                proc.start()
            except Exception as e:  # noqa: BLE001
                proc.log(f"✖ {t('srv_start_err')} : {e}")
            finally:
                proc._starting = False
        threading.Thread(target=work, daemon=True).start()
        if load_settings().get("server_interface", True):
            ServerWindow.open(self, proc.name)

    def _stop(self):
        if self.proc and self.proc.is_running():
            self.proc.log(t("srv_stop_req"))
            self.proc.stop()

    def _restart(self):
        if self.proc and self.proc.is_running():
            self.proc.log(t("srv_stop_req"))
            self.proc.restart()

    def _send(self):
        cmd = self.cmd_entry.get().strip()
        if not cmd:
            return
        self.cmd_entry.delete(0, "end")
        if not self.proc or not self.proc.send(cmd):
            self._append_many([t("srv_not_running")], "err")
            return
        self.proc.log(f"> {cmd}")

    def _open_mods(self):
        if self.meta:
            ModsManager(self, self.meta)

    def _open_settings(self):
        if self.meta:
            ServerSettings(self, self.meta, on_saved=self._settings_saved)

    def _settings_saved(self):
        if self.proc:
            self.proc.reload_meta()
            self._refresh_info()
            self._show_ip()
            self._update_stats()

    def _open_folder(self):
        if self.meta:
            subprocess.Popen(["explorer", str(Path(self.meta["dir"]))])

    def _delete(self):
        if not self.meta:
            return
        if not messagebox.askyesno(
                t("srv_del_title"),
                t("srv_del_confirm", name=self.meta["name"])):
            return
        try:
            sm.delete_server(self.meta["name"])
        except sm.ServerError as e:
            messagebox.showwarning(t("srv_del_title"), str(e))
            return
        self.meta = None
        self.proc = None
        self.refresh()
        metas = sm.list_servers()
        if metas:
            self._select(metas[0])
            return
        self.sel_label.configure(text=t("srv_none_sel"))
        self.info_label.configure(text="")
        self._show_ip()
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")
        self._update_state()
        self._update_stats()
        self._refresh_players()

    # ============================================================ console
    @staticmethod
    def _tag(line):
        up = line.upper()
        if "ERROR" in up or "EXCEPTION" in up or line.startswith("✖"):
            return "err"
        if "WARN" in up:
            return "warn"
        if line.startswith(("──", ">")):
            return "info"
        return None

    def _append_many(self, lines, tag=None):
        if not lines:
            return
        for name, color in _TAG_COLORS.items():
            self.console.tag_config(name, foreground=theme.c(color))
        self.console.configure(state="normal")
        for line in lines:
            if line.startswith(sm.QUIET_MARK):
                continue            # réponse de commande interne (list…)
            self.console.insert("end", line + "\n", tag or self._tag(line))
        if int(self.console.index("end-1c").split(".")[0]) > 6000:
            self.console.delete("1.0", "1000.0")
        self.console.see("end")
        self.console.configure(state="disabled")

    # ============================================================ joueurs
    def _refresh_players(self):
        tr = self.proc.tracker if self.proc else None
        names = sorted((tr.players if tr else {}), key=str.lower)
        self.players_title.configure(text=t("players_online", n=len(names)))
        for w in self.players_scroll.winfo_children():
            w.destroy()
        if not names:
            ctk.CTkLabel(self.players_scroll, text=t("no_players"),
                         text_color=theme.MUTED, wraplength=190,
                         justify="left").grid(
                row=0, column=0, sticky="w", padx=6, pady=6)
            return
        for i, name in enumerate(names):
            card = ctk.CTkFrame(self.players_scroll, fg_color=theme.PANEL_2,
                                corner_radius=10)
            card.grid(row=i, column=0, sticky="ew", pady=3, padx=2)
            card.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(card, text=name[:1].upper(), width=30, height=30,
                         corner_radius=8, fg_color=theme.ACCENT,
                         text_color="#ffffff",
                         font=(theme.FONT, 12, "bold")).grid(
                row=0, column=0, padx=8, pady=6)
            ctk.CTkLabel(card, text=name, font=(theme.FONT, 12, "bold"),
                         text_color=theme.TEXT, anchor="w").grid(
                row=0, column=1, sticky="w")
            btn = ctk.CTkButton(card, text="⋯", width=30, height=26,
                                fg_color=theme.PANEL, corner_radius=8,
                                hover_color=theme.HOVER,
                                text_color=theme.TEXT)
            btn.grid(row=0, column=2, padx=6)
            btn.configure(command=lambda b=btn, n=name: self._player_menu(n, b))

    def _player_menu(self, name, widget):
        proc = self.proc
        style = dict(tearoff=0, bg=theme.c(theme.PANEL_2),
                     fg=theme.c(theme.TEXT),
                     activebackground=theme.c(theme.ACCENT),
                     activeforeground="#ffffff")
        menu = tk.Menu(self, **style)

        def act(fn, *args):
            fn(proc, *args)
            proc.log(f"> {fn.__name__} {' '.join(str(a) for a in args)}")

        menu.add_command(label="🗺 " + t("pm_card"),
                         command=lambda: PlayerCard(self, proc, name))
        menu.add_separator()
        menu.add_command(label=t("pm_msg"), command=lambda: _ask(
            self, t("pm_title"), t("pm_to", name=name),
            lambda m: act(pl.message, name, m)))
        menu.add_separator()
        menu.add_command(label=t("kick"), command=lambda: _ask(
            self, t("reason_title"), t("kick_reason", name=name),
            lambda r: act(pl.kick, name, r or "Expulsé")))
        menu.add_command(label=t("ban"), command=lambda: _ask(
            self, t("reason_title"), t("ban_reason", name=name),
            lambda r: act(pl.ban, name, r or "Banni")))
        menu.add_command(label=t("unban"),
                         command=lambda: act(pl.pardon, name))
        menu.add_separator()
        menu.add_command(label=t("op"), command=lambda: act(pl.op, name))
        menu.add_command(label=t("deop"), command=lambda: act(pl.deop, name))
        gm = tk.Menu(menu, **style)
        for mode in ("survival", "creative", "adventure", "spectator"):
            gm.add_command(label=t("gamemode", mode=mode),
                           command=lambda m=mode: act(pl.gamemode, name, m))
        menu.add_cascade(label="Gamemode", menu=gm)
        menu.add_separator()
        menu.add_command(label=t("kill"), command=lambda: act(pl.kill, name))
        try:
            menu.tk_popup(widget.winfo_rootx(),
                          widget.winfo_rooty() + widget.winfo_height())
        finally:
            menu.grab_release()

    # ============================================================ boucle
    def _pump(self):
        """Toutes les 150 ms, thread Tk : console, statut, stats, joueurs."""
        try:
            if self.proc:
                lines, self._seen = self.proc.lines_since(self._seen)
                self._append_many(lines)
                running = self.proc.is_running()
                if running != self._last_running:
                    if self._last_running and not running:
                        self._append_many(
                            [t("srv_proc_end", code=self.proc.exit_code)],
                            "warn")
                    self._last_running = running
                players = frozenset(self.proc.tracker.players)
                if players != self._last_players:
                    self._last_players = players
                    self._refresh_players()
                if running:
                    self.proc.request_list()
            self._update_state()
            if self._tick % 7 == 0:                         # ~1 s
                self._update_stats()
                for name, slot in self._dots.items():
                    p = sm.PROCESSES.get(name)
                    on = bool(p and p.is_running())
                    if on != slot[1]:
                        slot[1] = on
                        slot[0].configure(text_color=theme.GREEN if on
                                          else theme.DISABLED)
            if self._ip_dirty:
                self._ip_dirty = False
                self._show_ip()
            self._tick += 1
        except Exception:  # noqa: BLE001 — la boucle ne doit jamais mourir
            import traceback
            traceback.print_exc()
        finally:
            try:
                self.after(150, self._pump)
            except RuntimeError:
                pass
