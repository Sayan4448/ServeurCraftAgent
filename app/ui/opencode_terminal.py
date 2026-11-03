"""Mini terminal OpenCode : messages envoyés à `opencode run`, réponses et
outils utilisés affichés au fil de l'eau. Le pont MCP (outils du serveur et
des tunnels) vit tant que la fenêtre est ouverte.

Les threads (téléchargement, opencode) ne touchent aucun widget : ils
remplissent `self._q`, vidée par `_pump()` dans le thread Tk.
"""
import queue
import threading

import customtkinter as ctk

from ..ai import opencode
from ..ai.mcp_bridge import INSTRUCTIONS, Bridge
from ..core import server_manager as sm
from ..i18n import t
from . import theme

_MENU = dict(fg_color=theme.PANEL_2, button_color=theme.ACCENT,
             button_hover_color=theme.ACCENT_HOVER, text_color=theme.TEXT)
_BTN = dict(fg_color=theme.PANEL_2, hover_color=theme.HOVER,
            text_color=theme.TEXT)


class OpenCodeTerminal(ctk.CTkToplevel):
    _open = None

    @classmethod
    def show(cls, master):
        win = cls._open
        if win is not None and win.winfo_exists():
            win.lift()
            return win
        cls._open = cls(master)
        return cls._open

    def __init__(self, master):
        super().__init__(master)
        self.title(t("oc_title"))
        self.geometry("860x580")
        self.minsize(640, 400)
        self.configure(fg_color=theme.BG)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._q: queue.Queue = queue.Queue()
        self._exe = None
        self._proc = None
        self._sessions: dict = {}      # serveur -> id de session OpenCode
        self._busy = True
        self.bridge = Bridge()
        self._cfg = opencode.write_config(self.bridge.url, self.bridge.token,
                                          INSTRUCTIONS)

        top = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=10)
        top.pack(fill="x", padx=12, pady=(12, 6))
        ctk.CTkLabel(top, text=t("oc_server"), text_color=theme.MUTED).pack(
            side="left", padx=(12, 6), pady=10)
        names = [s["name"] for s in sm.list_servers()]
        self._names = names
        self.server_menu = ctk.CTkOptionMenu(
            top, width=160, values=names or [t("oc_no_server")], **_MENU,
            command=self._server_changed)
        self.server_menu.pack(side="left")
        ctk.CTkLabel(top, text=t("oc_model"), text_color=theme.MUTED).pack(
            side="left", padx=(14, 6))
        self.model_box = ctk.CTkComboBox(
            top, width=250, values=[""], fg_color=theme.PANEL_2,
            border_color=theme.BORDER, button_color=theme.ACCENT,
            button_hover_color=theme.ACCENT_HOVER, text_color=theme.TEXT,
            dropdown_fg_color=theme.PANEL_2, dropdown_text_color=theme.TEXT)
        self.model_box.set("")
        self.model_box.pack(side="left")
        self.full_btn = ctk.CTkButton(top, text=t("oc_full"), width=0,
                                      command=self._open_full, **_BTN)
        self.full_btn.pack(side="right", padx=12)

        self.out = ctk.CTkTextbox(
            self, font=(theme.FONT_MONO, 12), wrap="word",
            fg_color=theme.CONSOLE_BG, text_color=theme.CONSOLE_TEXT,
            corner_radius=10)
        self.out.pack(fill="both", expand=True, padx=12)

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=12, pady=(6, 0))
        self.entry = ctk.CTkEntry(
            bottom, height=34, placeholder_text=t("oc_input_ph"),
            fg_color=theme.PANEL, border_color=theme.BORDER,
            text_color=theme.TEXT)
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.entry.bind("<Return>", lambda _e: self._send())
        self.send_btn = ctk.CTkButton(
            bottom, text=t("ai_send"), width=100, height=34,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            command=self._send)
        self.send_btn.pack(side="left")
        self.stop_btn = ctk.CTkButton(
            bottom, text=t("srv_stop"), width=90, height=34,
            fg_color=theme.PANEL_2, hover_color=theme.RED,
            text_color=theme.TEXT, command=self._stop)
        self.stop_btn.pack(side="left", padx=(8, 0))
        self.status = ctk.CTkLabel(self, text="", font=(theme.FONT, 11),
                                   text_color=theme.MUTED, anchor="w",
                                   justify="left", wraplength=820)
        self.status.pack(fill="x", padx=14, pady=(4, 8))

        self._append(t("oc_welcome"))
        self._server_changed(self.server_menu.get())
        self._set_busy(True)
        self._pump()
        threading.Thread(target=self._prepare, daemon=True).start()

    # ------------------------------------------------------------ thread Tk
    def _pump(self):
        try:
            while True:
                kind, val = self._q.get_nowait()
                if kind == "line":
                    self._append(val)
                elif kind == "status":
                    self.status.configure(text=val)
                elif kind == "models":
                    self.model_box.configure(values=[""] + val)
                elif kind == "exe":
                    self._exe = val
                elif kind == "done":
                    self._set_busy(False)
        except queue.Empty:
            pass
        self._pump_id = self.after(100, self._pump)

    def _append(self, text):
        self.out.configure(state="normal")
        self.out.insert("end", text + "\n")
        self.out.configure(state="disabled")
        self.out.see("end")

    def _set_busy(self, busy, running=False):
        self._busy = busy
        ready = not busy and self._exe is not None
        self.send_btn.configure(state="normal" if ready else "disabled")
        self.full_btn.configure(
            state="normal" if self._exe is not None else "disabled")
        self.server_menu.configure(state="disabled" if busy else "normal")
        self.stop_btn.configure(state="normal" if running else "disabled")

    def _server_changed(self, name):
        self.bridge.server = name if name in self._names else ""

    def _server(self):
        name = self.server_menu.get()
        if name not in self._names:
            self._append(t("oc_need_server"))
            return None
        return name

    def _send(self):
        msg = self.entry.get().strip()
        if not msg or self._busy or self._exe is None:
            return
        server = self._server()
        if not server:
            return
        self.entry.delete(0, "end")
        self._append(f"\n> {msg}")
        self._set_busy(True, running=True)
        threading.Thread(target=self._run, daemon=True, args=(
            server, msg, self.model_box.get().strip())).start()

    def _stop(self):
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()

    def _open_full(self):
        server = self._server()
        if not server or self._exe is None:
            return
        try:
            opencode.open_tui(self._exe, sm.server_dir(server), self._cfg,
                              self.model_box.get().strip(),
                              self._sessions.get(server, ""))
            self.status.configure(text=t("oc_full_hint"))
        except OSError as e:
            self._append(t("oc_err_start", e=e))

    def _close(self):
        try:
            self.after_cancel(self._pump_id)
        except (AttributeError, ValueError):
            pass
        self._stop()
        self.bridge.close()
        type(self)._open = None
        self.destroy()

    # --------------------------------------------------------------- threads
    def _prepare(self):
        """Trouve / télécharge opencode puis liste les modèles."""
        self._q.put(("status", t("oc_preparing")))
        last = [-1]

        def progress(done, total):
            pct = done * 100 // total if total else 0
            if pct != last[0]:
                last[0] = pct
                self._q.put(("status", t("oc_downloading", pct=pct)))
        try:
            exe = opencode.ensure_exe(progress)
        except opencode.OpenCodeError as e:
            self._q.put(("line", f"✖ {e}"))
            self._q.put(("status", str(e)))
            self._q.put(("done", None))
            return
        self._q.put(("exe", exe))
        self._q.put(("status", t("oc_models_loading")))
        models = opencode.list_models(exe, self._cfg)
        self._q.put(("models", models))
        self._q.put(("status", t("oc_ready") if models
                     else t("oc_no_models")))
        self._q.put(("done", None))

    def _run(self, server, msg, model):
        try:
            proc = opencode.run(self._exe, msg, sm.server_dir(server),
                                self._cfg, model,
                                self._sessions.get(server, ""))
        except OSError as e:
            self._q.put(("line", t("oc_err_start", e=e)))
            self._q.put(("done", None))
            return
        self._proc = proc
        got_session = False
        for line in proc.stdout:
            text, sid = opencode.parse_event(line)
            if sid:
                self._sessions[server] = sid
                got_session = True
            if text:
                self._q.put(("line", text))
        code = proc.wait()
        self._proc = None
        if code:
            self._q.put(("line", t("oc_exit", code=code)))
            if not got_session:     # session supprimée ? nouvelle au prochain
                self._sessions.pop(server, None)
        self._q.put(("done", None))
