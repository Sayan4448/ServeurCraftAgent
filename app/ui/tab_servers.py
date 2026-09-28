"""Onglet « Mes Serveurs » : liste / console / joueurs."""
import subprocess
import threading
import tkinter as tk
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
from .server_settings import ServerSettings
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
        self._seen = 0                 # lignes console déjà affichées
        self._last_players = None
        self._last_running = None
        self._cards: dict[str, ctk.CTkFrame] = {}
        self._dots: dict[str, list] = {}     # nom -> [label, état affiché]
        self._pub_ip: str | None = None
        self._ip_dirty = False
        self._list_tick = 0

        self._build_list_col()
        self._build_console_col()
        self._build_players_col()

        self.refresh()
        metas = sm.list_servers()
        if metas:
            self._select(metas[0])
        else:
            self._update_state()
        self._pump()

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

        # boutons d'action sur leurs propres lignes — jamais masqués
        btnrow = ctk.CTkFrame(col, fg_color="transparent")
        btnrow.grid(row=3, column=0, columnspan=2, sticky="ew", padx=10,
                    pady=(4, 2))
        for r in (0, 1):
            btnrow.grid_rowconfigure(r, weight=0)
        btnrow.grid_columnconfigure((0, 1, 2), weight=1, uniform="b")
        self._btns = {}

        def _btn(key, cmd, color, row, col_, text_color=None):
            b = ctk.CTkButton(
                btnrow, text=t(key), command=cmd, fg_color=color,
                hover_color=theme.HOVER if color == theme.PANEL_2 else None,
                text_color=text_color or theme.TEXT,
                font=(theme.FONT, 13, "bold"), height=38)
            padx = (0, 4) if col_ == 0 else (4, 0) if col_ == 2 else (4, 4)
            b.grid(row=row, column=col_, sticky="ew", padx=padx, pady=2)
            self._btns[key] = b

        _btn("srv_start", self._start, theme.GREEN, 0, 0, "#06210f")
        _btn("srv_stop", self._stop, theme.RED, 0, 1)
        _btn("srv_restart", self._restart, theme.ORANGE, 0, 2)
        _btn("srv_mods", self._open_mods, theme.PANEL_2, 1, 0)
        _btn("srv_settings", self._open_settings, theme.PANEL_2, 1, 1)
        _btn("srv_folder", self._open_folder, theme.PANEL_2, 1, 2)

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
        self._cards.clear()
        self._dots.clear()
        metas = sm.list_servers()
        if not metas:
            ctk.CTkLabel(self.list_scroll, text=t("srv_empty"),
                         text_color=theme.MUTED, justify="left").grid(
                row=0, column=0, sticky="w", padx=4, pady=4)
            return
        sel = self.meta["name"] if self.meta else None
        for i, meta in enumerate(metas):
            selected = meta["name"] == sel
            card = ctk.CTkFrame(
                self.list_scroll, corner_radius=8, border_width=2,
                fg_color=theme.HOVER if selected else theme.PANEL_2,
                border_color=theme.ACCENT if selected else theme.PANEL_2)
            card.grid(row=i, column=0, sticky="ew", pady=3)
            card.grid_columnconfigure(0, weight=1)
            self._cards[meta["name"]] = card
            lbl = ctk.CTkLabel(card, text=meta["name"],
                               font=(theme.FONT, 12, "bold"),
                               text_color=theme.TEXT, anchor="w")
            lbl.grid(row=0, column=0, sticky="w", padx=8, pady=(6, 0))
            running = meta.get("running")
            state = ctk.CTkLabel(
                card, text="●" if running else "○",
                text_color=theme.GREEN if running else theme.MUTED,
                font=(theme.FONT, 12))
            state.grid(row=0, column=1, padx=(0, 8))
            self._dots[meta["name"]] = [state, bool(running)]
            sub = ctk.CTkLabel(
                card,
                text=f"{meta['loader']} · MC {meta['mc_version']}",
                font=(theme.FONT, 10), text_color=theme.MUTED, anchor="w")
            sub.grid(row=1, column=0, columnspan=2, sticky="w", padx=8,
                     pady=(0, 6))
            # clic n'importe où sur la carte (frame + labels + canvas interne)
            for w in (card, lbl, state, sub, *card.winfo_children()):
                w.bind("<Button-1>", lambda _e, m=meta: self._select(m))

    # ------------------------------------------------------------ sélection
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
            card.configure(fg_color=theme.HOVER if sel else theme.PANEL_2,
                           border_color=theme.ACCENT if sel
                           else theme.PANEL_2)
        self.sel_label.configure(text=meta["name"])
        m = self.proc.meta
        self.info_label.configure(
            text=f"{m['loader']} {m['mc_version']} · port {m['port']} · "
                 f"{round(int(m['ram_mb']) / 1024, 1):g} Go")
        # console : on rejoue l'historique du serveur sélectionné
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")
        lines, self._seen = self.proc.lines_since(0)
        for line in lines:
            self._append(line)
        self._last_players = None
        self._last_running = None
        self._update_state()
        self._show_ip()
        self._refresh_players()

    def _tracker(self):
        return self.proc.tracker if self.proc else None

    # ------------------------------------------------------------------- IP
    def _show_ip(self):
        if not self.meta:
            return
        ip = local_ip()
        port = (self.proc.meta if self.proc else self.meta).get("port", 25565)
        playit = playit_address(Path(self.meta["dir"]))
        pub = playit or self._pub_ip
        self.ip_label.configure(
            text=f"{t('ip_local', ip=ip, port=port)}    " +
                 (t('ip_public', ip=pub) if pub else t('ip_public_wait')))
        if not pub and self._pub_ip is None:
            self._pub_ip = ""          # une seule requête en cours

            def _fetch():             # thread : ne touche pas à Tk
                self._pub_ip = public_ip() or ""
                self._ip_dirty = True
            threading.Thread(target=_fetch, daemon=True).start()

    # -------------------------------------------------------------- actions
    def _update_state(self):
        running = bool(self.proc and self.proc.is_running())
        starting = bool(self.proc and getattr(self.proc, "_starting", False))
        if not self.proc:
            self.state_label.configure(text="")
        elif starting and not running:
            self.state_label.configure(text="◌ " + t("srv_starting_short"),
                                       text_color=theme.ORANGE)
        else:
            self.state_label.configure(
                text=("● " + t("srv_running")) if running
                else ("○ " + t("srv_stopped")),
                text_color=theme.GREEN if running else theme.MUTED)
        has = self.proc is not None
        self._btns["srv_start"].configure(
            state="normal" if has and not running and not starting
            else "disabled")
        self._btns["srv_stop"].configure(
            state="normal" if running else "disabled")
        self._btns["srv_restart"].configure(
            state="normal" if running else "disabled")
        for k in ("srv_mods", "srv_settings", "srv_folder"):
            self._btns[k].configure(state="normal" if has else "disabled")

    def _start(self):
        proc = self.proc
        if not proc or proc.is_running() or getattr(proc, "_starting", False):
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
        self._update_state()

    def _restart(self):
        if self.proc and self.proc.is_running():
            self.proc.log(t("srv_stop_req"))
            self.proc.restart()
        self._update_state()

    def _send(self):
        cmd = self.cmd_entry.get().strip()
        if not cmd:
            return
        self.cmd_entry.delete(0, "end")
        if not self.proc or not self.proc.send(cmd):
            self._append(t("srv_not_running"), "err")
            return
        self.proc.log(f"> {cmd}")

    def _open_mods(self):
        if self.meta:
            ModsManager(self, self.meta)

    def _open_settings(self):
        if self.meta:
            ServerSettings(self, self.meta)

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
        self.sel_label.configure(text=t("srv_none_sel"))
        self.info_label.configure(text="")
        self.ip_label.configure(text="")
        self.state_label.configure(text="")
        self._refresh_players()

    # -------------------------------------------------------------- console
    def _append(self, line: str, tag: str | None = None):
        if tag is None:
            up = line.upper()
            tag = ("err" if ("ERROR" in up or "EXCEPTION" in up
                             or line.startswith("✖"))
                   else "warn" if "WARN" in up
                   else "info" if line.startswith(("──", ">")) else None)
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
    def _pump(self):
        """Toutes les 150 ms, depuis le thread Tk : console, statut, joueurs."""
        try:
            if self.proc:
                lines, self._seen = self.proc.lines_since(self._seen)
                for line in lines:
                    self._append(line)
                running = self.proc.is_running()
                if running != self._last_running:
                    if self._last_running and not running:
                        self._append(t("srv_proc_end",
                                       code=self.proc.exit_code), "warn")
                    self._last_running = running
                self._update_state()
                players = frozenset(self.proc.tracker.players)
                if players != self._last_players:
                    self._last_players = players
                    self._refresh_players()
                self._list_tick += 1
                if running and self._list_tick % 60 == 0:   # ~9 s
                    self.proc.send("list")
            # pastilles ●/○ mises à jour en place (sans recréer la liste)
            for name, slot in self._dots.items():
                p = sm.PROCESSES.get(name)
                on = bool(p and p.is_running())
                if on != slot[1]:
                    slot[1] = on
                    slot[0].configure(text="●" if on else "○",
                                      text_color=theme.GREEN if on
                                      else theme.MUTED)
            if self._ip_dirty:
                self._ip_dirty = False
                self._show_ip()
        except Exception:  # noqa: BLE001 — la boucle ne doit jamais mourir
            import traceback
            traceback.print_exc()
        finally:
            try:
                self.after(150, self._pump)
            except RuntimeError:
                pass
