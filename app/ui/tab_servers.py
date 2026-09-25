"""Onglet 'Mes Serveurs' : liste, démarrage/arrêt, console en direct."""
import os
import queue
import subprocess
import sys
from collections import deque
from tkinter import messagebox

import customtkinter as ctk

from ..core import server_manager as sm
from ..core.downloader import LOADER_LABELS
from . import theme


class ServersTab(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master, fg_color="transparent")
        self.selected = None
        self.buffers = {}          # name -> deque de lignes console
        self.events = queue.Queue()
        self._cards = {}

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ------------------------------------------------------------- gauche
        left = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=10, width=300)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 8))
        left.grid_propagate(False)
        left.grid_rowconfigure(1, weight=1)

        head = ctk.CTkFrame(left, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        ctk.CTkLabel(head, text="Mes serveurs", font=(theme.FONT, 15, "bold"),
                     text_color=theme.TEXT).pack(side="left")
        ctk.CTkButton(head, text="⟳", width=34, fg_color=theme.PANEL_2,
                      hover_color=theme.HOVER, command=self.refresh).pack(side="right")

        self.list_frame = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self.list_frame.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)

        # ------------------------------------------------------------- droite
        right = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=10)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)

        toolbar = ctk.CTkFrame(right, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        self.sel_label = ctk.CTkLabel(
            toolbar, text="Aucun serveur sélectionné",
            font=(theme.FONT, 14, "bold"), text_color=theme.TEXT,
        )
        self.sel_label.pack(side="left")

        btn = dict(fg_color=theme.PANEL_2, hover_color=theme.HOVER,
                   text_color=theme.TEXT, height=30, width=90)
        self.btn_delete = ctk.CTkButton(
            toolbar, text="Supprimer", fg_color=theme.RED,
            hover_color="#b91c1c", height=30, width=90,
            command=self.delete_selected)
        self.btn_delete.pack(side="right", padx=(6, 0))
        ctk.CTkButton(toolbar, text="Dossier", command=self.open_folder,
                      **btn).pack(side="right", padx=6)
        ctk.CTkButton(toolbar, text="Redémarrer", command=self.restart_selected,
                      **btn).pack(side="right", padx=6)
        self.btn_stop = ctk.CTkButton(
            toolbar, text="Arrêter", command=self.stop_selected, **btn)
        self.btn_stop.pack(side="right", padx=6)
        self.btn_start = ctk.CTkButton(
            toolbar, text="▶ Lancer", fg_color=theme.GREEN,
            hover_color="#16a34a", text_color="#06210f",
            height=30, width=90, command=self.start_selected)
        self.btn_start.pack(side="right")

        self.console = ctk.CTkTextbox(
            right, font=(theme.FONT_MONO, 12), fg_color="#0a0d12",
            text_color="#c9d1d9", wrap="word", state="disabled",
        )
        self.console.grid(row=1, column=0, sticky="nsew", padx=12, pady=6)
        self.console.tag_config("err", foreground="#f87171")
        self.console.tag_config("warn", foreground="#fbbf24")
        self.console.tag_config("ok", foreground="#4ade80")

        cmdrow = ctk.CTkFrame(right, fg_color="transparent")
        cmdrow.grid(row=2, column=0, sticky="ew", padx=12, pady=(4, 10))
        cmdrow.grid_columnconfigure(0, weight=1)
        self.cmd_entry = ctk.CTkEntry(
            cmdrow, placeholder_text="Commande console (ex: say Bonjour, op pseudo)…",
            fg_color=theme.PANEL_2, border_color=theme.BORDER, text_color=theme.TEXT)
        self.cmd_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.cmd_entry.bind("<Return>", lambda e: self.send_command())
        ctk.CTkButton(cmdrow, text="Envoyer", width=90, fg_color=theme.ACCENT,
                      hover_color=theme.ACCENT_HOVER,
                      command=self.send_command).grid(row=0, column=1)

        self.refresh()
        self.after(250, self._poll)

    # ------------------------------------------------------------- liste/cartes

    def refresh(self):
        for w in self.list_frame.winfo_children():
            w.destroy()
        self._cards.clear()
        servers = sm.list_servers()
        if not servers:
            ctk.CTkLabel(
                self.list_frame,
                text="Aucun serveur.\nCréez-en un dans l'onglet « Créateur Rapide ».",
                text_color=theme.MUTED, justify="left",
            ).pack(padx=10, pady=20, anchor="w")
            return
        for meta in servers:
            self._add_card(meta)
        if not self.selected:
            self._select(servers[0]["name"])
        elif self.selected not in [s["name"] for s in servers]:
            self.selected = None
            self._select(servers[0]["name"])

    def _add_card(self, meta: dict):
        running = meta.get("running")
        card = ctk.CTkFrame(self.list_frame, fg_color=theme.PANEL_2,
                            corner_radius=8, border_width=1,
                            border_color=theme.BORDER)
        card.pack(fill="x", pady=4)

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(8, 2))
        dot = ctk.CTkLabel(top, text="●", font=(theme.FONT, 14),
                           text_color=theme.GREEN if running else theme.MUTED,
                           width=16)
        dot.pack(side="left")
        name_lbl = ctk.CTkLabel(top, text=meta["name"],
                                font=(theme.FONT, 13, "bold"),
                                text_color=theme.TEXT)
        name_lbl.pack(side="left", padx=4)

        loader_lbl = LOADER_LABELS.get(meta["loader"], meta["loader"])
        sub = ctk.CTkLabel(
            card,
            text=f"{loader_lbl} · MC {meta['mc_version']} · {meta['ram_mb']} Mo · :{meta['port']}",
            font=(theme.FONT, 11), text_color=theme.MUTED,
        )
        sub.pack(anchor="w", padx=30, pady=(0, 8))

        for w in (card, top, dot, name_lbl, sub):
            w.bind("<Button-1>", lambda e, n=meta["name"]: self._select(n))
        self._cards[meta["name"]] = (card, dot)

    def _select(self, name: str):
        self.selected = name
        for n, (card, _dot) in self._cards.items():
            card.configure(
                border_color=theme.ACCENT if n == name else theme.BORDER)
        self.sel_label.configure(text=name)
        self._redraw_console()

    # --------------------------------------------------------------- console

    def _enqueue(self, kind, name, text):
        self.events.put((kind, name, text))

    def _poll(self):
        try:
            while True:
                kind, name, text = self.events.get_nowait()
                if kind == "line":
                    buf = self.buffers.setdefault(name, deque(maxlen=4000))
                    buf.append(text)
                    if name == self.selected:
                        self._append(text)
                elif kind == "exit":
                    if name == self.selected:
                        self._append(f"── Processus terminé (code {text}) ──", "warn")
                    self.refresh()
        except queue.Empty:
            pass
        self.after(250, self._poll)

    def _append(self, line: str, tag: str = None):
        if tag is None:
            up = line.upper()
            tag = "err" if ("ERROR" in up or "EXCEPTION" in up) else \
                  "warn" if "WARN" in up else None
        self.console.configure(state="normal")
        self.console.insert("end", line + "\n", tag)
        self.console.see("end")
        self.console.configure(state="disabled")

    def _redraw_console(self):
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        for line in self.buffers.get(self.selected, []):
            self.console.insert("end", line + "\n")
        self.console.see("end")
        self.console.configure(state="disabled")

    # ------------------------------------------------------------ actions

    def start_selected(self):
        if not self.selected:
            return
        name = self.selected
        proc = sm.get_process(name)
        try:
            proc.start(on_line=lambda n, l: self._enqueue("line", n, l),
                       on_exit=lambda n, c: self._enqueue("exit", n, c))
            self._append(f"── Démarrage de {name} ──", "ok")
            self.refresh()
        except Exception as e:
            messagebox.showerror("Démarrage impossible", str(e))

    def stop_selected(self):
        if self.selected:
            sm.get_process(self.selected).stop()
            self._append("── Arrêt demandé (stop) ──", "warn")

    def restart_selected(self):
        if self.selected:
            sm.get_process(self.selected).restart()

    def send_command(self):
        cmd = self.cmd_entry.get().strip()
        if not cmd or not self.selected:
            return
        if sm.get_process(self.selected).send(cmd):
            self._append(f"> {cmd}")
        else:
            self._append("Serveur non lancé.", "err")
        self.cmd_entry.delete(0, "end")

    def open_folder(self):
        if not self.selected:
            return
        path = sm.server_dir(self.selected)
        try:
            if sys.platform == "win32":
                os.startfile(path)  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError as e:
            messagebox.showerror("Ouverture impossible", str(e))

    def delete_selected(self):
        if not self.selected:
            return
        if not messagebox.askyesno(
                "Supprimer", f"Supprimer définitivement '{self.selected}' ?"):
            return
        try:
            sm.delete_server(self.selected)
        except sm.ServerError as e:
            messagebox.showwarning("Suppression impossible", str(e))
            return
        self.buffers.pop(self.selected, None)
        self.selected = None
        self._redraw_console()
        self.refresh()
