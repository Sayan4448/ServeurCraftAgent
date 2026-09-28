"""Onglet « Mes Serveurs » : liste / console / joueurs."""
import threading
import tkinter as tk
from collections import deque
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from ..config import load_settings
from ..core import players as pl
from ..core import server_manager as sm
from ..core.server_net import local_ip, public_ip, playit_address
from ..i18n import t
from . import theme
from .mods_manager import ModsManager
from .server_window import ServerWindow

BTN = dict(height=34, font=(theme.FONT, 12), corner_radius=8)


def _ask(win, title, prompt, cb):
    d = ctk.CTkInputDialog(text=prompt, title=title)
    d.geometry("+%d+%d" % (win.winfo_rootx() + 80, win.winfo_rooty() + 120))
    val = d.get_input()
    if val is not None:
        cb(val)


class ServersTab(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(0, weight=0, minsize=230)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=0, minsize=210)
        self.grid_rowconfigure(0, weight=1)

        self.meta: dict | None = None
        self.proc: sm.ServerProcess | None = None
        self.buffer = deque(maxlen=4000)
        self._wired_trackers: set[str] = set()
        self._pub_ip: str | None = None

        self._build_list_col()
        self._build_console_col()
        self._build_players_col()

        self.refresh()
        self._poll()

    # ------------------------------------------------------------ colonnes
    def _build_list_col(self):
        col = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=10)
        col.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        col.grid_rowconfigure(1, weight=1)
        col.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(col, text=t("srv_my"), font=(theme.FONT, 13, "bold"),
                     text_color=theme.TEXT).grid(
            row=0, column=0, sticky="w", padx=12, pady=(10, 4))

        self.list_scroll = ctk.CTkScrollableFrame(col, fg_color=theme.BG)
        self.list_scroll.grid(row=1, column=0, sticky="nsew",
                              padx=8, pady=(0, 8))
        self.list_scroll.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(col, text=t("srv_delete"), fg_color=theme.RED,
                      hover_color="#b91c1c", command=self._delete,
                      **BTN).grid(row=2, column=0, sticky="ew", padx=10,
                                  pady=(0, 10))

    def _build_console_col(self):
        col = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=10)
        col.grid(row=0, column=1, sticky="nsew", padx=(0, 8))
        col.grid_rowconfigure(4, weight=1)
        col.grid_columnconfigure(0, weight=1)
        col.grid_columnconfigure(1, weight=0)

        self.sel_label = ctk.CTkLabel(
            col, text=t("srv_none_sel"), font=(theme.FONT, 15, "bold"),
            text_color=theme.TEXT, anchor="w")
        self.sel_label.grid(row=0, column=0, sticky="w", padx=12, pady=(10, 0))
        self.state_label = ctk.CTkLabel(
            col, text="", font=(theme.FONT, 12, "bold"))
        self.state_label.grid(row=0, column=1, sticky="e", padx=10,
                              pady=(10, 0))

        # ligne IP
        self.ip_label = ctk.CTkLabel(col, text="", font=(theme.FONT_MONO, 11),
                                     text_color=theme.MUTED, anchor="w")
        self.ip_label.grid(row=1, column=0, columnspan=2, sticky="w",
                           padx=14, pady=(2, 0))

        self.info_label = ctk.CTkLabel(col, text="", font=(theme.FONT, 11),
                                       text_color=theme.MUTED, anchor="w")
        self.info_label.grid(row=2, column=0, columnspan=2, sticky="w",
                             padx=14, pady=2)

        # 3 boutons d'action sur leur propre ligne — jamais masqués
        btnrow = ctk.CTkFrame(col, fg_color="transparent")
        btnrow.grid(row=3, column=0, columnspan=2, sticky="ew", padx=10,
                    pady=(4, 2))
        btnrow.grid_columnconfigure((0, 1, 2), weight=1, uniform="b")
        self._btns = {}
        self._btns["srv_start"] = ctk.CTkButton(
            btnrow, text=t("srv_start"), command=self._start,
            fg_color=theme.GREEN, hover_color="#16a34a",
            text_color="#06210f", font=(theme.FONT, 13, "bold"), height=38)
        self._btns["srv_stop"] = ctk.CTkButton(
            btnrow, text=t("srv_stop"), command=self._stop,
            fg_color=theme.RED, hover_color="#b91c1c",
            font=(theme.FONT, 13, "bold"), height=38)
        self._btns["srv_mods"] = ctk.CTkButton(
            btnrow, text=t("srv_mods"), command=self._open_mods,
            fg_color=theme.PANEL_2, hover_color=theme.HOVER,
            text_color=theme.TEXT, font=(theme.FONT, 13, "bold"), height=38)
        self._btns["srv_start"].grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self._btns["srv_stop"].grid(row=0, column=1, sticky="ew", padx=4)
        self._btns["srv_mods"].grid(row=0, column=2, sticky="ew",
                                  padx=(4, 0))

        self.console = ctk.CTkTextbox(
            col, font=(theme.FONT_MONO, 11), fg_color=theme.CONSOLE_BG,
            text_color=theme.CONSOLE_TEXT, corner_radius=8, state="disabled",
            wrap="none")
        self.console.grid(row=4, column=0, columnspan=2, sticky="nsew",
                          padx=10, pady=10)

        row = ctk.CTkFrame(col, fg_color="transparent")
        row.grid(row=5, column=0, columnspan=2, sticky="ew", padx=10,
                 pady=(0, 10))
        row.grid_columnconfigure(0, weight=1)
        self.cmd_entry = ctk.CTkEntry(
            row, placeholder_text=t("srv_cmd_ph"), fg_color=theme.PANEL_2,
            border_color=theme.BORDER, text_color=theme.TEXT)
        self.cmd_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.cmd_entry.bind("<Return>", lambda _e: self._send())
        ctk.CTkButton(row, text=t("srv_send"), width=90,
                      command=self._send).grid(row=0, column=1)

    def _build_players_col(self):
        col = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=10)
        col.grid(row=0, column=2, sticky="nsew")
        col.grid_rowconfigure(1, weight=1)
        col.grid_columnconfigure(0, weight=1)

        self.players_title = ctk.CTkLabel(
            col, text=t("players_online", n=0), font=(theme.FONT, 13, "bold"),
            text_color=theme.TEXT)
        self.players_title.grid(row=0, column=0, sticky="w", padx=12,
                                pady=(10, 4))

        self.players_scroll = ctk.CTkScrollableFrame(col, fg_color=theme.BG)
        self.players_scroll.grid(row=1, column=0, sticky="nsew",
                                 padx=8, pady=(0, 10))
        self.players_scroll.grid_columnconfigure(0, weight=1)

    # ---------------------------------------------------------------- liste
    def refresh(self):
        for w in self.list_scroll.winfo_children():
            w.destroy()
        metas = sm.list_servers()
        if not metas:
            ctk.CTkLabel(self.list_scroll, text=t("srv_empty"),
                         text_color=theme.MUTED, justify="left").grid(
                row=0, column=0, sticky="w", padx=4, pady=4)
            return
        for i, meta in enumerate(metas):
            card = ctk.CTkFrame(self.list_scroll, fg_color=theme.PANEL_2,
                                corner_radius=8)
            card.grid(row=i, column=0, sticky="ew", pady=3)
            card.grid_columnconfigure(0, weight=1)
            card.bind("<Button-1>", lambda _e, m=meta: self._select(m))
            lbl = ctk.CTkLabel(card, text=meta["name"],
                               font=(theme.FONT, 12, "bold"),
                               text_color=theme.TEXT, anchor="w")
            lbl.grid(row=0, column=0, sticky="w", padx=8, pady=(6, 0))
            lbl.bind("<Button-1>", lambda _e, m=meta: self._select(m))
            dot = "●" if meta.get("running") else "○"
            dot_color = theme.GREEN if meta.get("running") else theme.MUTED
            state = ctk.CTkLabel(card, text=dot, text_color=dot_color,
                                 font=(theme.FONT, 12))
            state.grid(row=0, column=1, padx=(0, 8))
            sub = ctk.CTkLabel(
                card,
                text=f"{meta['loader']} · MC {meta['mc_version']}",
                font=(theme.FONT, 10), text_color=theme.MUTED, anchor="w")
            sub.grid(row=1, column=0, columnspan=2, sticky="w", padx=8,
                     pady=(0, 6))
            sub.bind("<Button-1>", lambda _e, m=meta: self._select(m))

    # ------------------------------------------------------------ sélection
    def _select(self, meta: dict):
        self.meta = meta
        self.proc = sm.get_process(meta["name"])
        # tracker partagé avec ServerWindow (alimenté via listener)
        trackers = ServerWindow._trackers
        tr = trackers.get(meta["name"])
        if tr is None:
            tr = pl.PlayerTracker(meta["name"])
            trackers[meta["name"]] = tr
        if meta["name"] not in self._wired_trackers:
            self.proc.add_listener(on_line=tr.feed)
            self._wired_trackers.add(meta["name"])
        tr.on_change = lambda _ps, s=self: s.after(0, s._refresh_players)
        self.sel_label.configure(text=meta["name"])
        self.info_label.configure(
            text=f"{meta['loader']} {meta['mc_version']} · port "
                 f"{meta['port']} · {meta['ram_mb']} Mo")
        self._update_state()
        self._show_ip()
        self._refresh_players()

    def _tracker(self):
        if not self.meta:
            return None
        return ServerWindow._trackers.get(self.meta["name"])

    # ------------------------------------------------------------------- IP
    def _show_ip(self):
        if not self.meta:
            return
        ip = local_ip()
        port = self.meta.get("port", 25565)
        playit = playit_address(Path(self.meta["dir"]))
        if playit:
            self.ip_label.configure(
                text=f"{t('ip_local', ip=ip, port=port)}    "
                     f"{t('ip_public', ip=playit)}")
            return
        if self._pub_ip:
            self.ip_label.configure(
                text=f"{t('ip_local', ip=ip, port=port)}    "
                     f"{t('ip_public', ip=self._pub_ip)}")
            return
        self.ip_label.configure(
            text=f"{t('ip_local', ip=ip, port=port)}    "
                 f"{t('ip_public_wait')}")

        def _fetch():
            pub = public_ip()
            if pub:
                self._pub_ip = pub
                try:
                    self.after(0, self._show_ip)
                except RuntimeError:
                    pass
        threading.Thread(target=_fetch, daemon=True).start()

    # -------------------------------------------------------------- actions
    def _update_state(self):
        if not self.proc:
            return
        running = self.proc.is_running()
        self.state_label.configure(
            text=("● " + t("srv_running")) if running
            else ("○ " + t("srv_stopped")),
            text_color=theme.GREEN if running else theme.MUTED)
        self._btns["srv_start"].configure(
            state="disabled" if running else "normal")
        self._btns["srv_stop"].configure(
            state="normal" if running else "disabled")

    def _start(self):
        if not self.proc or self.proc.is_running():
            return
        self._append(t("srv_starting", name=self.meta["name"]), "info")
        self._btns["srv_start"].configure(state="disabled")

        def work():
            try:
                self.proc.start(on_line=self._on_console_line,
                                on_exit=self._on_exit)
            except Exception as e:  # noqa: BLE001
                try:
                    self.after(0, self._append,
                               f"{t('srv_start_err')} : {e}", "err")
                except RuntimeError:
                    pass
            try:
                self.after(0, self._update_state)
            except RuntimeError:
                pass
        threading.Thread(target=work, daemon=True).start()
        if load_settings().get("server_interface", True):
            ServerWindow.open(self, self.meta["name"])

    def _stop(self):
        if self.proc and self.proc.is_running():
            self._append(t("srv_stop_req"), "warn")
            self.proc.stop()
        self._update_state()

    def _send(self):
        cmd = self.cmd_entry.get().strip()
        if not cmd:
            return
        self.cmd_entry.delete(0, "end")
        if not self.proc or not self.proc.send(cmd):
            self._append(t("srv_not_running"), "err")
            return
        self._append(f"> {cmd}")

    def _open_mods(self):
        if self.meta:
            ModsManager(self, self.meta)

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
        self.sel_label.configure(text=t("srv_none_sel"))
        self.info_label.configure(text="")
        self.ip_label.configure(text="")
        self.state_label.configure(text="")
        self._refresh_players()

    # -------------------------------------------------------------- console
    def _on_console_line(self, name: str, line: str):
        if self.meta and name == self.meta["name"]:
            self.buffer.append(line)
            try:
                self.after(0, self._append, line)
            except RuntimeError:
                pass

    def _append(self, line: str, tag: str | None = None):
        if tag is None:
            up = line.upper()
            tag = ("err" if ("ERROR" in up or "EXCEPTION" in up)
                   else "warn" if "WARN" in up else None)
        colors = {"err": "#f87171", "warn": "#fbbf24", "info": theme.ACCENT,
                  "ok": "#4ade80"}
        tag = tag or "def"
        self.console.tag_config(tag,
                                foreground=colors.get(tag,
                                                      theme.CONSOLE_TEXT))
        self.console.configure(state="normal")
        self.console.insert("end", line + "\n", tag)
        self.console.see("end")
        self.console.configure(state="disabled")

    def _on_exit(self, name: str, code: int):
        if self.meta and name == self.meta["name"]:
            try:
                self.after(0, self._append,
                           t("srv_proc_end", code=code), "warn")
                self.after(0, self._update_state)
                self.after(0, self.refresh)
                self.after(0, self._refresh_players)
            except RuntimeError:
                pass
            tr = self._tracker()
            if tr:
                tr.reset()

    # -------------------------------------------------------------- joueurs
    def _refresh_players(self):
        tr = self._tracker()
        names = sorted((tr.players if tr else {}), key=str.lower)
        self.players_title.configure(text=t("players_online", n=len(names)))
        for w in self.players_scroll.winfo_children():
            w.destroy()
        if not names:
            ctk.CTkLabel(self.players_scroll, text=t("no_players"),
                         text_color=theme.MUTED).grid(
                row=0, column=0, sticky="w", padx=4, pady=4)
            return
        for i, name in enumerate(names):
            card = ctk.CTkFrame(self.players_scroll, fg_color=theme.PANEL_2,
                                corner_radius=8)
            card.grid(row=i, column=0, sticky="ew", pady=3)
            card.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(card, text=name, font=(theme.FONT, 12),
                         text_color=theme.TEXT, anchor="w").grid(
                row=0, column=0, sticky="w", padx=8, pady=6)
            btn = ctk.CTkButton(card, text="⋯", width=28, height=24,
                                fg_color=theme.HOVER, corner_radius=6,
                                text_color=theme.TEXT)
            btn.grid(row=0, column=1, padx=6)
            btn.configure(command=lambda b=btn, n=name: self._player_menu(n, b))

    def _player_menu(self, name, widget):
        proc = self.proc
        menu = tk.Menu(self, tearoff=0, bg=theme.PANEL_2, fg=theme.TEXT,
                       activebackground=theme.ACCENT,
                       activeforeground="#ffffff")

        def act(fn, *args):
            fn(proc, *args)

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
        gm = tk.Menu(menu, tearoff=0, bg=theme.PANEL_2, fg=theme.TEXT,
                     activebackground=theme.ACCENT,
                     activeforeground="#ffffff")
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

    # ---------------------------------------------------------------- boucle
    def _poll(self):
        try:
            if self.proc and self.proc.is_running():
                tr = self._tracker()
                if tr is not None and not tr.players:
                    self.proc.send("list")
            self._update_state()
        finally:
            try:
                self.after(2000, self._poll)
            except RuntimeError:
                pass
