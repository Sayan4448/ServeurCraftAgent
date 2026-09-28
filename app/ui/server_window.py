"""Fenêtre 'Interface serveur' : console live + joueurs (têtes, grades, catégories).

Toutes les données viennent de `ServerProcess` (backlog console, tracker de
joueurs) et sont lues par `_pump()` dans le thread Tk — aucun appel Tkinter
depuis les threads de lecture.
"""
import threading
import tkinter as tk
from io import BytesIO
from pathlib import Path

import customtkinter as ctk
import requests
from PIL import Image

from ..core import players as pl
from ..core import ranks as ranks_mod
from ..core import server_manager as sm
from ..core.downloader import LOADER_LABELS
from ..core.server_net import local_ip, playit_address, public_ip
from .player_card import PlayerCard
from ..i18n import t
from . import theme

MINOTAR = "https://minotar.net/helm/{}/40.png"


class ServerWindow(ctk.CTkToplevel):
    _instances = {}   # name -> fenêtre (une seule par serveur)

    @classmethod
    def open(cls, master, name: str):
        inst = cls._instances.get(name)
        try:
            if inst and inst.winfo_exists():
                inst.deiconify()
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
        self._heads = {}              # pseudo -> CTkImage
        self._pending_heads = {}      # pseudo -> Image PIL (rempli par thread)
        self._head_labels = {}        # pseudo -> [labels]
        self._seen = 0
        self._last_players = None
        self._last_running = None
        self._alive = True
        self._pub_ip = None
        self._tick_n = 0

        meta = self.proc.meta
        self._loader = LOADER_LABELS.get(meta.get("loader"),
                                         meta.get("loader", ""))
        self.title(t("win_title", name=name))
        self.geometry("1000x660")
        self.minsize(780, 480)
        self.configure(fg_color=theme.BG)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ------------------------------------------------------------- haut
        head = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=10)
        head.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=10)
        head.grid_columnconfigure(0, weight=1)
        self.status_lbl = ctk.CTkLabel(head, text="",
                                       font=(theme.FONT, 14, "bold"),
                                       anchor="w")
        self.status_lbl.grid(row=0, column=0, sticky="w", padx=14,
                             pady=(10, 0))
        self.ip_lbl = ctk.CTkLabel(head, text="", font=(theme.FONT_MONO, 11),
                                   text_color=theme.MUTED, anchor="w")
        self.ip_lbl.grid(row=1, column=0, sticky="w", padx=14)
        self.stats_lbl = ctk.CTkLabel(head, text="", font=(theme.FONT, 11),
                                      text_color=theme.MUTED, anchor="w")
        self.stats_lbl.grid(row=2, column=0, sticky="w", padx=14,
                            pady=(0, 10))

        btns = ctk.CTkFrame(head, fg_color="transparent")
        btns.grid(row=0, column=1, rowspan=3, sticky="e", padx=10)
        bstyle = dict(height=32, width=110, font=(theme.FONT, 12, "bold"))
        self.start_btn = ctk.CTkButton(
            btns, text=t("srv_start"), fg_color=theme.GREEN,
            hover_color=theme.GREEN_HOVER, text_color=theme.ON_GREEN,
            command=self._start, **bstyle)
        self.stop_btn = ctk.CTkButton(
            btns, text=t("srv_stop"), fg_color=theme.RED,
            hover_color=theme.RED_HOVER, command=self._stop, **bstyle)
        self.restart_btn = ctk.CTkButton(
            btns, text=t("srv_restart"), fg_color=theme.ORANGE,
            hover_color=theme.ORANGE_HOVER, command=self._restart, **bstyle)
        self.settings_btn = ctk.CTkButton(
            btns, text=t("srv_settings"), fg_color=theme.PANEL_2,
            hover_color=theme.HOVER, text_color=theme.TEXT,
            command=self._open_settings, **bstyle)
        for b in (self.start_btn, self.stop_btn, self.restart_btn,
                  self.settings_btn):
            b.pack(side="left", padx=3, pady=8)

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
            left, font=(theme.FONT_MONO, 12), fg_color=theme.CONSOLE_BG,
            text_color=theme.CONSOLE_TEXT, wrap="word", state="disabled")
        self.console.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 6))
        self.console.tag_config("err", foreground=theme.c(("#dc2626", "#f87171")))
        self.console.tag_config("warn", foreground=theme.c(("#b45309", "#fbbf24")))
        self.console.tag_config("info", foreground=theme.c(theme.ACCENT))

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
        right.grid_rowconfigure(2, weight=1)
        right.grid_columnconfigure(0, weight=1)
        self.players_header = ctk.CTkLabel(
            right, text=t("players_online", n=0),
            font=(theme.FONT, 13, "bold"), text_color=theme.TEXT)
        self.players_header.grid(row=0, column=0, sticky="w", padx=12, pady=10)
        self._pviews = [t("pv_online"), t("pv_bans"), t("pv_ops")]
        seg = ctk.CTkSegmentedButton(
            right, values=self._pviews, command=self._show_pview,
            selected_color=theme.SEL, text_color=theme.TEXT,
            selected_hover_color=theme.SEL_HOVER,
            unselected_color=theme.PANEL_2,
            unselected_hover_color=theme.HOVER)
        seg.set(self._pviews[0])
        seg.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 8))
        self.players_frame = ctk.CTkScrollableFrame(
            right, fg_color="transparent")
        self.players_frame.grid(row=2, column=0, sticky="nsew", padx=6,
                                pady=(0, 8))
        from .players_panel import BansView, OpsView, ctx_for
        self.bans_view = BansView(right, lambda: ctx_for(self.proc))
        self.ops_view = OpsView(right, lambda: ctx_for(self.proc))
        for v in (self.bans_view, self.ops_view):
            v.grid(row=2, column=0, sticky="nsew", padx=6, pady=(0, 8))
            v.grid_remove()

        self._show_ip()
        self._pump()

    # ------------------------------------------------------------ boucle

    def _pump(self):
        if not self._alive:
            return
        try:
            lines, self._seen = self.proc.lines_since(self._seen)
            if lines:
                self._append_many(lines)
            running = self.proc.is_running()
            starting = getattr(self.proc, "_starting", False)
            if (running, starting) != self._last_running:
                self._last_running = (running, starting)
                self._update_state(running, starting)
            players = frozenset(self.proc.tracker.players)
            if players != self._last_players:
                self._last_players = players
                self._render_players()
            if self._pending_heads:
                self._apply_heads()
            self._tick_n += 1
            if running:
                self.proc.request_list()
            if self._tick_n % 20 == 0:
                self._show_ip()
            if self._tick_n % 7 == 0:
                st = self.proc.stats()
                limit = int(self.proc.meta.get("ram_mb", 4096)) / 1024
                self.stats_lbl.configure(
                    text=(f"RAM {st['ram_mb'] / 1024:.1f} / {limit:g} Go   ·   "
                          f"CPU {st['cpu']:.0f} %   ·   "
                          f"{theme.fmt_duration(st['uptime'])}")
                    if st else "")
        except Exception:  # noqa: BLE001
            import traceback
            traceback.print_exc()
        try:
            self.after(150, self._pump)
        except RuntimeError:
            pass

    def _update_state(self, running, starting):
        if running:
            self.status_lbl.configure(
                text=f"●  {self.name}  ·  {self._loader}  ·  "
                     f"MC {self.proc.meta.get('mc_version')}  ·  "
                     f"{t('srv_running')}",
                text_color=theme.GREEN)
        elif starting:
            self.status_lbl.configure(
                text=f"◌  {self.name}  ·  {t('srv_starting_short')}",
                text_color=theme.ORANGE)
        else:
            self.status_lbl.configure(
                text=f"○  {self.name}  ·  {t('srv_stopped')}",
                text_color=theme.MUTED)
        theme.action_button(self.start_btn, not running and not starting,
                            theme.GREEN, theme.GREEN_HOVER, theme.ON_GREEN)
        theme.action_button(self.stop_btn, running, theme.RED,
                            theme.RED_HOVER)
        theme.action_button(self.restart_btn, running, theme.ORANGE,
                            theme.ORANGE_HOVER)

    def _show_ip(self):
        meta = self.proc.meta
        port = meta.get("port", 25565)
        tunnels = meta.get("tunnels") or []
        java_tn = next((tn for tn in tunnels if tn["proto"] == "tcp"
                        and tn["local"] == port), None)
        net_addr = ((java_tn or {}).get("address")
                    or (playit_address(self.dir) if not tunnels else None))
        if net_addr:
            right = f"{t('ip_internet')} : {net_addr}"
            hint = t("ip_hint_ok")
        else:
            pub = self._pub_ip
            right = (t("ip_public_port", ip=pub, port=port) if pub
                     else t("ip_public_wait"))
            hint = t("ip_hint_wan", port=port)
        self.ip_lbl.configure(
            text=f"{t('ip_local', ip=local_ip(), port=port)}    {right}\n"
                 f"{hint}")
        if not net_addr and not self._pub_ip and self._pub_ip is None:
            self._pub_ip = ""

            def _fetch():             # thread : pas de Tk ici
                self._pub_ip = public_ip() or ""
            threading.Thread(target=_fetch, daemon=True).start()

    # ------------------------------------------------------------ console

    @staticmethod
    def _tag(line):
        up = line.upper()
        if "ERROR" in up or "EXCEPTION" in up or line.startswith("✖"):
            return "err"
        if "WARN" in up:
            return "warn"
        if line.startswith(("──", ">", "→")):
            return "info"
        return None

    def _append_many(self, lines):
        self.console.configure(state="normal")
        for line in lines:
            self.console.insert("end", line + "\n", self._tag(line))
        # limite la taille pour garder l'UI fluide
        if int(self.console.index("end-1c").split(".")[0]) > 6000:
            self.console.delete("1.0", "1000.0")
        self.console.see("end")
        self.console.configure(state="disabled")

    def _send(self):
        cmd = self.cmd_entry.get().strip()
        if not cmd:
            return
        if self.proc.send(cmd):
            self.proc.log(f"> {cmd}")
        else:
            self._append_many([t("srv_not_running")])
        self.cmd_entry.delete(0, "end")

    def _start(self):
        proc = self.proc
        if proc.is_running() or getattr(proc, "_starting", False):
            return
        proc._starting = True
        proc.log(t("srv_starting", name=proc.name))

        def work():
            try:
                proc.start()
            except Exception as e:  # noqa: BLE001
                proc.log(f"✖ {t('srv_start_err')} : {e}")
            finally:
                proc._starting = False
        threading.Thread(target=work, daemon=True).start()

    def _stop(self):
        if self.proc.is_running():
            self.proc.log(t("srv_stop_req"))
            self.proc.stop()

    def _restart(self):
        if self.proc.is_running():
            self.proc.log(t("srv_stop_req"))
            self.proc.restart()

    def _open_settings(self):
        from .server_settings import ServerSettings
        meta = dict(self.proc.meta)
        meta["dir"] = str(self.dir)
        meta["name"] = self.name
        ServerSettings(self, meta, on_saved=self._settings_saved)

    def _settings_saved(self):
        self.proc.reload_meta()
        self._show_ip()

    # ------------------------------------------------------------ joueurs

    def _show_pview(self, value):
        views = {self._pviews[0]: self.players_frame,
                 self._pviews[1]: self.bans_view,
                 self._pviews[2]: self.ops_view}
        for k, v in views.items():
            if k == value:
                v.grid()
            else:
                v.grid_remove()
        if value != self._pviews[0]:
            views[value].refresh()

    def _render_players(self):
        for w in self.players_frame.winfo_children():
            w.destroy()
        self._head_labels.clear()
        players = sorted(self.proc.tracker.players, key=str.lower)
        self.players_header.configure(
            text=t("players_online", n=len(players)))
        if not players:
            ctk.CTkLabel(self.players_frame, text=t("no_players"),
                         text_color=theme.MUTED,
                         font=(theme.FONT, 11)).pack(pady=12)
            return
        data = ranks_mod.load(self.dir)
        ops = ranks_mod.read_ops(self.dir)
        admins = [p for p in players
                  if p in ops or ranks_mod.get(data, p)["category"]
                  == ranks_mod.CAT_ADMIN]
        regular = [p for p in players if p not in admins]
        self._group(t("cat_admins"), admins, theme.ORANGE, data)
        self._group(t("cat_players"), regular, theme.TEXT, data)

    def _group(self, title, players, color, data):
        if not players:
            return
        ctk.CTkLabel(self.players_frame, text=title,
                     font=(theme.FONT, 11, "bold"), text_color=color,
                     anchor="w").pack(fill="x", padx=4, pady=(8, 2))
        for p in players:
            self._player_row(p, data)

    def _player_row(self, name, data):
        entry = ranks_mod.get(data, name)
        row = ctk.CTkFrame(self.players_frame, fg_color=theme.PANEL_2,
                           corner_radius=8)
        row.pack(fill="x", pady=2, padx=2)
        face = ctk.CTkLabel(row, text=name[:2].upper(), width=40, height=40,
                            fg_color=theme.PANEL, corner_radius=6,
                            font=(theme.FONT, 12, "bold"),
                            text_color=theme.TEXT)
        face.pack(side="left", padx=6, pady=6)
        self._head_labels.setdefault(name, []).append(face)
        self._load_head(name)
        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True, padx=4)
        ctk.CTkLabel(info, text=name, font=(theme.FONT, 12, "bold"),
                     text_color=theme.TEXT, anchor="w").pack(anchor="w")
        rank = entry["rank"] or t("rank_none")
        rcolor = theme.ACCENT if entry["category"] == ranks_mod.CAT_ADMIN \
            else theme.MUTED
        ctk.CTkLabel(info, text=rank, font=(theme.FONT, 10),
                     text_color=rcolor, anchor="w").pack(anchor="w")
        btn = ctk.CTkButton(row, text="⋯", width=30, height=28,
                            fg_color=theme.PANEL, hover_color=theme.HOVER,
                            text_color=theme.TEXT)
        btn.configure(command=lambda b=btn, n=name: self._player_menu(n, b))
        btn.pack(side="right", padx=6)

    def _load_head(self, name):
        if name in self._heads:
            for lbl in self._head_labels.get(name, []):
                lbl.configure(image=self._heads[name], text="")
            return
        if name in self._pending_heads:
            return

        def work():                   # thread : télécharge seulement
            try:
                data = requests.get(MINOTAR.format(name), timeout=10).content
                self._pending_heads[name] = Image.open(
                    BytesIO(data)).convert("RGBA")
            except Exception:  # noqa: BLE001
                pass
        threading.Thread(target=work, daemon=True).start()

    def _apply_heads(self):
        for name, img in list(self._pending_heads.items()):
            if img is None:
                continue
            self._heads[name] = ctk.CTkImage(light_image=img, dark_image=img,
                                             size=(40, 40))
            self._pending_heads[name] = None
            for lbl in self._head_labels.get(name, []):
                try:
                    lbl.configure(image=self._heads[name], text="")
                except tk.TclError:
                    pass

    def _player_menu(self, name, widget):
        menu = tk.Menu(self, tearoff=0, bg=theme.c(theme.PANEL_2), fg=theme.c(theme.TEXT),
                       activebackground=theme.c(theme.ACCENT),
                       activeforeground="#ffffff")

        def act(fn, *args):
            fn(self.proc, *args)
            self.proc.log(f"> {fn.__name__} {name} {' '.join(args[1:])}")

        menu.add_command(
            label="🗺 " + t("pm_card"),
            command=lambda: PlayerCard(self, self.proc, name))
        menu.add_command(label=t("set_rank"),
                         command=lambda: self._set_rank(name))
        menu.add_separator()
        menu.add_command(label=t("op"),
                         command=lambda: self._set_admin(name, True))
        menu.add_command(label=t("deop"),
                         command=lambda: self._set_admin(name, False))
        menu.add_separator()
        menu.add_command(label=t("pm_msg"),
                         command=lambda: self._player_message(name))
        menu.add_command(label=t("kick"), command=lambda: self._ask_reason(
            name, t("kick_reason", name=name), pl.kick))
        menu.add_command(label=t("ban"), command=lambda: self._ask_reason(
            name, t("ban_reason", name=name), pl.ban))
        menu.add_command(label=t("unban"),
                         command=lambda: act(pl.pardon, name))
        menu.add_separator()
        for mode in ("survival", "creative", "adventure", "spectator"):
            menu.add_command(label=t("gamemode", mode=mode),
                             command=lambda m=mode: act(pl.gamemode, name, m))
        menu.add_separator()
        menu.add_command(label=t("kill"), command=lambda: act(pl.kill, name))
        try:
            menu.tk_popup(widget.winfo_rootx(),
                          widget.winfo_rooty() + widget.winfo_height())
        finally:
            menu.grab_release()

    def _set_admin(self, name, admin: bool):
        self.proc.send(f"{'op' if admin else 'deop'} {name}")
        ranks_mod.set_category(
            self.dir, name,
            ranks_mod.CAT_ADMIN if admin else ranks_mod.CAT_PLAYER)
        self.proc.log(f"> {'op' if admin else 'deop'} {name}")
        self._render_players()

    def _set_rank(self, name):
        dlg = ctk.CTkInputDialog(text=t("rank_prompt", name=name),
                                 title=t("rank_title"))
        rank = dlg.get_input()
        if rank is not None:
            ranks_mod.set_rank(self.dir, name, rank.strip())
            self._render_players()

    def _ask_reason(self, name, prompt, fn):
        dlg = ctk.CTkInputDialog(text=prompt, title=t("reason_title"))
        reason = dlg.get_input()
        if reason is not None:
            fn(self.proc, name, reason.strip() or fn.__name__)
            self.proc.log(f"> {fn.__name__} {name} {reason}")

    def _player_message(self, name):
        dlg = ctk.CTkInputDialog(text=t("pm_to", name=name),
                                 title=t("pm_title"))
        text = dlg.get_input()
        if text:
            pl.message(self.proc, name, text)
            self.proc.log(f"→ {name} : {text}")

    def _on_close(self):
        self._alive = False
        self._instances.pop(self.name, None)
        self.destroy()
