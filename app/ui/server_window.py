"""Fenêtre 'Interface serveur' : console live + joueurs (têtes, grades, catégories)."""
import threading
import tkinter as tk
from collections import deque
from io import BytesIO
from pathlib import Path

import customtkinter as ctk
import requests
from PIL import Image

from ..core import players as pl
from ..core import ranks as ranks_mod
from ..core import server_manager as sm
from ..core.downloader import LOADER_LABELS
from ..i18n import t
from . import theme

MINOTAR = "https://minotar.net/helm/{}/40.png"


class ServerWindow(ctk.CTkToplevel):
    _instances = {}   # name -> fenêtre (une seule par serveur)
    _buffers = {}     # name -> deque de lignes console
    _trackers = {}    # name -> PlayerTracker

    @classmethod
    def open(cls, master, name: str):
        inst = cls._instances.get(name)
        try:
            if inst and inst.winfo_exists():
                inst.lift()
                inst.focus_force()
                return inst
        except Exception:
            pass
        inst = cls(master, name)
        cls._instances[name] = inst
        return inst

    def __init__(self, master, name: str):
        super().__init__(master)
        self.name = name
        self.proc = sm.get_process(name)
        self.dir = Path(self.proc.path)
        self._head_cache = {}
        self.buffer = self._buffers.setdefault(name, deque(maxlen=4000))

        tracker = self._trackers.get(name)
        if tracker is None:
            tracker = pl.PlayerTracker(name)
            self._trackers[name] = tracker
            self.proc.add_listener(on_line=tracker.feed)
        tracker.on_change = lambda _ps, s=self: s._safe_render()
        self.proc.add_listener(on_line=self._feed, on_exit=self._exit)

        meta = self.proc.meta
        loader = LOADER_LABELS.get(meta.get("loader"), meta.get("loader", ""))
        self.title(t("win_title", name=name))
        self.geometry("980x640")
        self.minsize(760, 480)
        self.configure(fg_color=theme.BG)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ------------------------------------------------------------- haut
        head = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=10)
        head.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=10)
        self.status_lbl = ctk.CTkLabel(
            head, text=f"●  {name}  ·  {loader}  ·  MC {meta.get('mc_version')}",
            font=(theme.FONT, 14, "bold"), text_color=theme.GREEN)
        self.status_lbl.pack(side="left", padx=14, pady=10)
        btn = dict(fg_color=theme.PANEL_2, hover_color=theme.HOVER,
                   text_color=theme.TEXT, height=30, width=110)
        ctk.CTkButton(head, text=t("srv_restart"), command=self._restart,
                      **btn).pack(side="right", padx=(4, 12))
        ctk.CTkButton(head, text=t("srv_stop"), fg_color=theme.RED,
                      hover_color="#b91c1c", height=30, width=110,
                      command=self._stop).pack(side="right", padx=4)

        # ----------------------------------------------------------- console
        left = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=10)
        left.grid(row=1, column=0, sticky="nsew", padx=(10, 5), pady=(0, 10))
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(left, text=t("win_console"),
                     font=(theme.FONT, 13, "bold"),
                     text_color=theme.TEXT).grid(
            row=0, column=0, sticky="w", padx=12, pady=(10, 4))
        self.console = ctk.CTkTextbox(
            left, font=(theme.FONT_MONO, 12), fg_color="#0a0d12",
            text_color="#c9d1d9", wrap="word", state="disabled")
        self.console.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 6))
        self.console.tag_config("err", foreground="#f87171")
        self.console.tag_config("warn", foreground="#fbbf24")
        self.console.tag_config("ok", foreground="#4ade80")

        cmdrow = ctk.CTkFrame(left, fg_color="transparent")
        cmdrow.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 12))
        cmdrow.grid_columnconfigure(0, weight=1)
        self.cmd_entry = ctk.CTkEntry(
            cmdrow, placeholder_text=t("srv_cmd_ph"), fg_color=theme.PANEL_2,
            border_color=theme.BORDER, text_color=theme.TEXT)
        self.cmd_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.cmd_entry.bind("<Return>", lambda e: self._send())
        ctk.CTkButton(cmdrow, text=t("srv_send"), width=90,
                      fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                      command=self._send).grid(row=0, column=1)

        # ----------------------------------------------------------- joueurs
        right = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=10,
                             width=300)
        right.grid(row=1, column=1, sticky="ns", padx=(5, 10), pady=(0, 10))
        right.grid_propagate(False)
        right.grid_rowconfigure(1, weight=1)
        self.players_header = ctk.CTkLabel(
            right, text=t("players_online", n=0),
            font=(theme.FONT, 13, "bold"), text_color=theme.TEXT)
        self.players_header.grid(row=0, column=0, sticky="w", padx=12, pady=10)
        self.players_frame = ctk.CTkScrollableFrame(
            right, fg_color="transparent")
        self.players_frame.grid(row=1, column=0, sticky="nsew", padx=6,
                                pady=(0, 8))

        self._redraw_console()
        self._render_players()
        self._poll_list()
        if not self.proc.is_running():
            self._mark_offline()

    # ------------------------------------------------------------ console

    def _feed(self, name, line):
        if name != self.name:
            return
        self.buffer.append(line)
        try:
            self.after(0, self._append, line)
        except RuntimeError:
            pass

    def _exit(self, name, code):
        try:
            self.after(0, self._mark_offline)
            self.after(0, self._append,
                       t("srv_proc_end", code=code), "warn")
        except RuntimeError:
            pass

    def _append(self, line, tag=None):
        try:
            if tag is None:
                up = line.upper()
                tag = ("err" if ("ERROR" in up or "EXCEPTION" in up)
                       else "warn" if "WARN" in up else None)
            self.console.configure(state="normal")
            self.console.insert("end", line + "\n", tag)
            self.console.see("end")
            self.console.configure(state="disabled")
        except RuntimeError:
            pass

    def _redraw_console(self):
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        for line in self.buffer:
            self.console.insert("end", line + "\n")
        self.console.see("end")
        self.console.configure(state="disabled")

    def _send(self):
        cmd = self.cmd_entry.get().strip()
        if not cmd:
            return
        if self.proc.send(cmd):
            self._append(f"> {cmd}")
        else:
            self._append(t("srv_not_running"), "err")
        self.cmd_entry.delete(0, "end")

    def _stop(self):
        self.proc.stop()
        self._append(t("srv_stop_req"), "warn")

    def _restart(self):
        self.proc.restart()

    def _mark_offline(self):
        self.status_lbl.configure(
            text=f"○  {self.name}  ·  {t('win_offline')}",
            text_color=theme.MUTED)
        tracker = self._trackers.get(self.name)
        if tracker:
            tracker.players.clear()
        self._render_players()

    # ------------------------------------------------------------ joueurs

    def _poll_list(self):
        if self.proc.is_running():
            self.proc.send("list")
        try:
            self.after(8000, self._poll_list)
        except RuntimeError:
            pass

    def _safe_render(self):
        try:
            self.after(0, self._render_players)
        except RuntimeError:
            pass

    def _render_players(self):
        for w in self.players_frame.winfo_children():
            w.destroy()
        tracker = self._trackers.get(self.name)
        players = sorted((tracker.players if tracker else {}),
                         key=str.lower)
        self.players_header.configure(
            text=t("players_online", n=len(players)))
        data = ranks_mod.load(self.dir)
        ops = ranks_mod.read_ops(self.dir)
        admins = [p for p in players
                  if p in ops or ranks_mod.get(data, p)["category"]
                  == ranks_mod.CAT_ADMIN]
        regular = [p for p in players if p not in admins]
        if not players:
            ctk.CTkLabel(self.players_frame, text=t("no_players"),
                         text_color=theme.MUTED,
                         font=(theme.FONT, 11)).pack(pady=12)
            return
        self._group(t("cat_admins"), admins, theme.ORANGE)
        self._group(t("cat_players"), regular, theme.TEXT)

    def _group(self, title, players, color):
        if not players:
            return
        ctk.CTkLabel(self.players_frame, text=title,
                     font=(theme.FONT, 11, "bold"), text_color=color,
                     anchor="w").pack(fill="x", padx=4, pady=(8, 2))
        for p in players:
            self._player_row(p)

    def _player_row(self, name):
        data = ranks_mod.load(self.dir)
        entry = ranks_mod.get(data, name)
        row = ctk.CTkFrame(self.players_frame, fg_color=theme.PANEL_2,
                           corner_radius=8)
        row.pack(fill="x", pady=2, padx=2)
        face = ctk.CTkLabel(row, text=name[:2].upper(), width=40, height=40,
                            fg_color=theme.PANEL, corner_radius=6,
                            font=(theme.FONT, 12, "bold"))
        face.pack(side="left", padx=6, pady=6)
        self._load_head(name, face)
        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True, padx=4)
        ctk.CTkLabel(info, text=name, font=(theme.FONT, 12, "bold"),
                     text_color=theme.TEXT, anchor="w").pack(anchor="w")
        rank = entry["rank"] or t("rank_none")
        rcolor = theme.ACCENT if entry["category"] == ranks_mod.CAT_ADMIN \
            else theme.MUTED
        ctk.CTkLabel(info, text=rank, font=(theme.FONT, 10),
                     text_color=rcolor, anchor="w").pack(anchor="w")
        btn = ctk.CTkButton(row, text="⋯", width=28, height=26,
                            fg_color=theme.PANEL, hover_color=theme.HOVER)
        btn.configure(command=lambda b=btn, n=name: self._player_menu(n, b))
        btn.pack(side="right", padx=6)

    def _load_head(self, name, label):
        if name in self._head_cache:
            label.configure(image=self._head_cache[name], text="")
            return

        def work():
            try:
                data = requests.get(MINOTAR.format(name), timeout=10).content
                img = Image.open(BytesIO(data)).convert("RGBA")
                cimg = ctk.CTkImage(light_image=img, dark_image=img,
                                    size=(40, 40))
                self._head_cache[name] = cimg
                self.after(0, lambda: label.configure(image=cimg, text=""))
            except Exception:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _player_menu(self, name, widget):
        menu = tk.Menu(self, tearoff=0, bg=theme.PANEL_2, fg=theme.TEXT,
                       activebackground=theme.ACCENT,
                       activeforeground="#ffffff")

        def act(fn, *args, ok=None):
            fn(self.proc, *args)
            if ok:
                self._append(ok, "warn")

        menu.add_command(
            label=t("set_rank"),
            command=lambda: self._set_rank(name))
        menu.add_separator()
        menu.add_command(
            label=t("op"),
            command=lambda: self._set_admin(name, True))
        menu.add_command(
            label=t("deop"),
            command=lambda: self._set_admin(name, False))
        menu.add_separator()
        menu.add_command(
            label=t("pm_msg"),
            command=lambda: self._player_message(name))
        menu.add_command(
            label=t("kick"),
            command=lambda: act(pl.kick, name, "Expulsé par l'admin",
                                ok=f"kick {name}"))
        menu.add_command(
            label=t("ban"),
            command=lambda: act(pl.ban, name, "Banni par l'admin",
                                ok=f"ban {name}"))
        menu.add_command(
            label=t("unban"),
            command=lambda: act(pl.pardon, name, ok=f"pardon {name}"))
        menu.add_separator()
        for mode in ("survival", "creative", "adventure", "spectator"):
            menu.add_command(
                label=t("gamemode", mode=mode),
                command=lambda m=mode: act(pl.gamemode, name, m,
                                           ok=f"gamemode {m} {name}"))
        menu.add_separator()
        menu.add_command(
            label=t("kill"),
            command=lambda: act(pl.kill, name, ok=f"kill {name}"))
        try:
            menu.tk_popup(widget.winfo_rootx(),
                          widget.winfo_rooty() + widget.winfo_height())
        finally:
            menu.grab_release()

    def _set_admin(self, name, admin: bool):
        if admin:
            self.proc.send(f"op {name}")
            ranks_mod.set_category(self.dir, name, ranks_mod.CAT_ADMIN)
            self._append(f"op {name}", "warn")
        else:
            self.proc.send(f"deop {name}")
            ranks_mod.set_category(self.dir, name, ranks_mod.CAT_PLAYER)
            self._append(f"deop {name}", "warn")
        self._render_players()

    def _set_rank(self, name):
        dlg = ctk.CTkInputDialog(text=t("rank_prompt", name=name),
                                 title=t("rank_title"))
        rank = dlg.get_input()
        if rank is not None:
            ranks_mod.set_rank(self.dir, name, rank.strip())
            self._render_players()

    def _player_message(self, name):
        dlg = ctk.CTkInputDialog(text=t("pm_to", name=name),
                                 title=t("pm_title"))
        text = dlg.get_input()
        if text:
            pl.message(self.proc, name, text)
            self._append(f"→ {name} : {text}")

    def _on_close(self):
        tracker = self._trackers.get(self.name)
        if tracker:
            tracker.on_change = None
        self._instances.pop(self.name, None)
        self.destroy()
