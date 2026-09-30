"""Petite fenêtre Playit, collée à droite de l'app : liaison du compte dans le
navigateur puis création automatique des tunnels TCP/UDP d'un serveur, avec
l'avancement étape par étape et les adresses à copier."""
import threading
import webbrowser

import customtkinter as ctk

from ..core import playit
from ..core import server_manager as sm
from ..i18n import t
from . import theme
from .uithread import ui_call

W, H = 380, 420
_SPIN = "◐◓◑◒"


class PlayitPanel(ctk.CTkToplevel):
    _open: dict = {}

    @classmethod
    def show(cls, master, proc=None, on_done=None):
        """Ouvre (ou ramène devant) le panneau. `proc` : ServerProcess dont
        il faut créer les tunnels ; None = liaison du compte seule."""
        key = proc.name if proc else ""
        panel = cls._open.get(key)
        if panel is not None and panel.winfo_exists():
            panel.lift()
            return panel
        panel = cls(master, proc, on_done)
        cls._open[key] = panel
        return panel

    def __init__(self, master, proc=None, on_done=None):
        super().__init__(master)
        self.proc = proc
        self.on_done = on_done
        self._key = proc.name if proc else ""
        self._cancel = threading.Event()
        self._url = ""
        self._busy = True
        self._spin_i = 0
        self.title(t("pl_title_srv", name=proc.name) if proc
                   else t("pl_title"))
        self.configure(fg_color=theme.BG)
        self.resizable(False, True)
        self.minsize(W, 300)
        self._place(master)
        self.attributes("-topmost", True)
        self.protocol("WM_DELETE_WINDOW", self._close)

        ctk.CTkLabel(self, text="🌐  " + t("pl_title"),
                     font=(theme.FONT, 15, "bold"), text_color=theme.TEXT,
                     anchor="w").pack(fill="x", padx=16, pady=(14, 2))
        if proc:
            ctk.CTkLabel(self, text=proc.name, font=(theme.FONT, 11),
                         text_color=theme.MUTED, anchor="w").pack(
                fill="x", padx=16)

        box = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=10)
        box.pack(fill="x", padx=12, pady=(10, 6))
        self._box = box
        box.grid_columnconfigure(1, weight=1)
        self._steps = {}
        steps = [("link", t("pl_step_link"))]
        if proc:
            for kind, _local in playit.wanted_for(proc.meta):
                _p, proto, label = playit.KINDS[kind]
                steps.append((label, t("pl_step_tunnel", proto=proto.upper(),
                                       name=label)))
            steps.append(("agent", t("pl_step_agent")))
        for i, (key, text) in enumerate(steps):
            icon = ctk.CTkLabel(box, text="○", width=22,
                                font=(theme.FONT, 14), text_color=theme.MUTED)
            icon.grid(row=2 * i, column=0, sticky="nw", padx=(10, 4),
                      pady=(8 if i == 0 else 4, 0))
            ctk.CTkLabel(box, text=text, font=(theme.FONT, 12, "bold"),
                         text_color=theme.TEXT, anchor="w").grid(
                row=2 * i, column=1, sticky="w", padx=4,
                pady=(8 if i == 0 else 4, 0))
            detail = ctk.CTkLabel(box, text="", font=(theme.FONT, 10),
                                  text_color=theme.MUTED, anchor="w",
                                  justify="left", wraplength=W - 80)
            detail.grid(row=2 * i + 1, column=1, sticky="w", padx=4,
                        pady=(0, 8 if i == len(steps) - 1 else 0))
            self._steps[key] = {"icon": icon, "detail": detail,
                                "state": "wait"}

        self.link_bar = ctk.CTkFrame(self, fg_color="transparent")
        for text, cmd in (("↗  " + t("pl_reopen"), self._reopen),
                          ("📋  " + t("pl_copy_link"), self._copy_link)):
            ctk.CTkButton(self.link_bar, text=text, height=28, width=0,
                          fg_color=theme.PANEL_2, hover_color=theme.HOVER,
                          text_color=theme.TEXT, command=cmd).pack(
                side="left", padx=(0, 6))

        self.result = ctk.CTkFrame(self, fg_color="transparent")
        self.result.pack(fill="both", expand=True, padx=12)
        self.msg = ctk.CTkLabel(self, text="", font=(theme.FONT, 11),
                                text_color=theme.MUTED, anchor="w",
                                justify="left", wraplength=W - 30)
        self.msg.pack(fill="x", padx=16, pady=(4, 4))
        self.close_btn = ctk.CTkButton(
            self, text=t("pl_cancel"), height=32, fg_color=theme.PANEL_2,
            hover_color=theme.HOVER, text_color=theme.TEXT,
            command=self._close)
        self.close_btn.pack(fill="x", padx=12, pady=(4, 12))

        self._tick()
        threading.Thread(target=self._work, daemon=True).start()

    # ------------------------------------------------------------ fenêtre
    def _place(self, master):
        top = master.winfo_toplevel()
        s = self._get_window_scaling()
        w, h = round(W * s), round(H * s)
        x = top.winfo_rootx() + top.winfo_width() + 8
        if x + w > self.winfo_screenwidth():
            x = top.winfo_rootx() + top.winfo_width() - w - 24
        y = top.winfo_rooty() + 40
        self.geometry(f"{W}x{H}+{max(0, x)}+{max(0, y)}")

    def _fit(self):
        """Hauteur ajustée au contenu (adresses ajoutées à la fin)."""
        self.update_idletasks()
        s = self._get_window_scaling()
        h = max(H, round(self.winfo_reqheight() / s) + 8)
        self.geometry(f"{W}x{min(h, 760)}")

    def _close(self):
        self._cancel.set()
        PlayitPanel._open.pop(self._key, None)
        self.destroy()

    def _tick(self):
        """Animation des étapes en cours (thread Tk)."""
        self._spin_i = (self._spin_i + 1) % len(_SPIN)
        for st in self._steps.values():
            if st["state"] == "active":
                st["icon"].configure(text=_SPIN[self._spin_i])
        if self._busy:
            self.after(150, self._tick)

    def _step(self, key, state, detail=None):
        st = self._steps.get(key)
        if not st:
            return
        st["state"] = state
        icon, color = {"wait": ("○", theme.MUTED),
                       "active": (_SPIN[0], theme.ACCENT),
                       "done": ("✔", theme.GREEN),
                       "error": ("✖", theme.RED)}[state]
        st["icon"].configure(text=icon, text_color=color)
        if detail is not None:
            st["detail"].configure(text=detail)

    # ------------------------------------------------------------- liaison
    def _reopen(self):
        if self._url:
            webbrowser.open(self._url)

    def _copy_link(self):
        if self._url:
            self.clipboard_clear()
            self.clipboard_append(self._url)

    def _show_link_bar(self):
        self.link_bar.pack(fill="x", padx=12, pady=(0, 4), after=self._box)

    def _claim_status(self, state):
        if state == "WaitingForUserVisit":
            self._step("link", "active", t("pl_st_visit"))
        elif state == "WaitingForUser":
            self._step("link", "active", t("pl_st_approve"))
        elif state == "UserAccepted":
            self._step("link", "active", t("pl_st_accepted"))
            self.link_bar.pack_forget()

    # ------------------------------------------------------------- travail
    def _work(self):
        """Thread : aucun appel Tk direct, tout passe par ui_call."""
        opened = []

        def on_status(state):
            if not opened:
                opened.append(True)
                webbrowser.open(self._url)
            ui_call(self, self._claim_status, state)

        try:
            if playit.linked():
                ui_call(self, self._step, "link", "done", t("pl_linked"))
            else:
                code, self._url = playit.new_claim()
                ui_call(self, self._step, "link", "active",
                        t("pl_st_opening"))
                ui_call(self, self._show_link_bar)
                playit.link(code, on_status=on_status, cancel=self._cancel)
                ui_call(self, self.link_bar.pack_forget)
                ui_call(self, self._step, "link", "done", t("pl_linked"))
            if not self.proc:
                ui_call(self, self._finish, [])
                return
            for key in self._steps:
                if key not in ("link", "agent"):
                    ui_call(self, self._step, key, "active",
                            t("pl_st_waiting"))
            ui_call(self, self._step, "agent", "active", t("pl_agent_dl"))
            playit.ensure_agent_exe()
            ui_call(self, self._step, "agent", "wait", "")

            def log(event, label, value):
                if event == "create":
                    ui_call(self, self._step, label, "active",
                            t("pl_st_creating"))
                elif event == "ready":
                    ui_call(self, self._step, label, "done", value)
                elif event == "agent":
                    ui_call(self, self._step, "agent", "active", "")

            found = playit.setup_server(self.proc.name, self.proc.path, log)
            self.proc.reload_meta()
            if self._cancel.wait(3):
                return
            err = playit.agent_error()
            if err:
                raise playit.PlayitError(t("pl_log_agent_err", e=err))
            running = self.proc.is_running()
            if not running:
                playit.release(list(sm.PROCESSES.values()))
            ui_call(self, self._step, "agent", "done",
                    t("pl_agent_ok") if running else t("pl_agent_later"))
            ui_call(self, self._finish, found)
        except Exception as e:  # noqa: BLE001 — réseau, compte, API
            if not self._cancel.is_set():
                ui_call(self, self._fail, playit.explain(e))

    def _finish(self, found):
        self._busy = False
        self.close_btn.configure(text=t("pl_close"), fg_color=theme.ACCENT,
                                 hover_color=theme.ACCENT_HOVER,
                                 text_color=theme.ON_ACCENT)
        if not self.proc:
            self.msg.configure(text=t("pl_link_done"))
        else:
            ctk.CTkLabel(self.result, text=t("pl_done"),
                         font=(theme.FONT, 12, "bold"),
                         text_color=theme.TEXT, anchor="w").pack(
                fill="x", pady=(4, 4))
            for tn in found:
                row = ctk.CTkFrame(self.result, fg_color=theme.PANEL,
                                   corner_radius=8)
                row.pack(fill="x", pady=2)
                ctk.CTkLabel(row, text=f"{tn['name']} ({tn['proto'].upper()})",
                             font=(theme.FONT, 10), text_color=theme.MUTED,
                             width=110, anchor="w").pack(side="left",
                                                         padx=(10, 4))
                ctk.CTkLabel(row, text=tn["address"],
                             font=(theme.FONT_MONO, 11),
                             text_color=theme.TEXT, anchor="w").pack(
                    side="left", fill="x", expand=True)
                btn = ctk.CTkButton(row, text="📋", width=32, height=26,
                                    fg_color=theme.PANEL_2,
                                    hover_color=theme.HOVER,
                                    text_color=theme.TEXT)
                btn.configure(command=lambda a=tn["address"], b=btn:
                              self._copy(a, b))
                btn.pack(side="right", padx=6, pady=4)
            self.msg.configure(text=t("pl_done_hint"))
        self._fit()
        if self.on_done:
            self.on_done()

    def _copy(self, text, btn):
        self.clipboard_clear()
        self.clipboard_append(text)
        btn.configure(text="✔")
        self.after(1200, lambda: btn.winfo_exists()
                   and btn.configure(text="📋"))

    def _fail(self, msg):
        self._busy = False
        for st in self._steps.values():
            if st["state"] == "active":
                st["state"] = "error"
                st["icon"].configure(text="✖", text_color=theme.RED)
        self.link_bar.pack_forget()
        self.msg.configure(text=f"✖ {msg}", text_color=theme.RED)
        self.close_btn.configure(text=t("pl_close"))
        self._fit()
