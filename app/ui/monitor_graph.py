"""Graphique temps réel RAM / CPU / TPS du tableau de bord (tk.Canvas).

Les données viennent de `ServerProcess.history` (rempli par le
planificateur) ; ce widget ne fait que dessiner, dans le thread Tk."""
import time
import tkinter as tk

import customtkinter as ctk

from ..core.server_manager import HISTORY
from ..i18n import t
from . import theme


class MonitorGraph(ctk.CTkFrame):
    HEIGHT = 60
    HEADROOM = 0.9    # 100 % dessiné à 90 % de la hauteur

    def __init__(self, master):
        super().__init__(master, fg_color=theme.PANEL, corner_radius=12,
                         border_width=1, border_color=theme.BORDER)
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=12, pady=(6, 0))
        ctk.CTkLabel(head, text=t("mon_title"), font=(theme.FONT, 11),
                     text_color=theme.MUTED).pack(side="left")
        self.legend = {}
        for key, color in (("tps", theme.GREEN), ("cpu", theme.PURPLE),
                           ("ram", theme.ACCENT)):
            lbl = ctk.CTkLabel(head, text="", font=(theme.FONT_MONO, 11),
                               text_color=color)
            lbl.pack(side="right", padx=(12, 0))
            self.legend[key] = lbl
        self.canvas = tk.Canvas(self, height=self.HEIGHT, bd=0,
                                highlightthickness=0,
                                bg=theme.c(theme.PANEL))
        self.canvas.pack(fill="x", padx=12, pady=(2, 8))
        self.canvas.bind("<Configure>", lambda _e: self.draw())
        self._points = []
        self._limit = 1.0
        self._tps = False
        self._running = False

    def set(self, history, limit_mb: float, show_tps: bool,
            running: bool) -> None:
        self._points = list(history)
        self._limit = max(1.0, float(limit_mb))
        self._tps = show_tps
        self._running = running
        last = self._points[-1] if running and self._points else None
        if last:
            self.legend["ram"].configure(
                text=f"RAM {last[1] / 1024:.1f} Go")
            self.legend["cpu"].configure(text=f"CPU {last[2]:.0f} %")
        else:
            self.legend["ram"].configure(text="RAM —")
            self.legend["cpu"].configure(text="CPU —")
        tps = last[3] if last else None
        self.legend["tps"].configure(
            text=(f"TPS {tps:.1f}" if tps is not None else "TPS —")
            if show_tps else "")
        self.draw()

    def draw(self) -> None:
        cv = self.canvas
        cv.delete("all")
        cv.configure(bg=theme.c(theme.PANEL))
        w, h = max(cv.winfo_width(), 50), self.HEIGHT
        top, bottom = 2, h - 2
        scale = (bottom - top) * self.HEADROOM
        grid = theme.c(theme.BORDER)
        muted = theme.c(theme.MUTED)
        cv.create_line(0, bottom, w, bottom, fill=grid)
        pts = self._points
        if not self._running or len(pts) < 2:
            cv.create_text(w / 2, h / 2, fill=muted, font=(theme.FONT, 10),
                           text=t("mon_waiting") if self._running
                           else t("mon_stopped"))
            return
        for frac in (0.5, 1.0):
            y = bottom - frac * scale
            cv.create_line(0, y, w, y, fill=grid, dash=(2, 3))
        now = time.time()
        span = float(HISTORY)
        # la RSS de Java dépasse souvent -Xmx (métaspace, threads…)
        ram_max = max(self._limit, 1.25 * max(p[1] for p in pts))
        series = []
        if self._tps:
            series.append((lambda p: None if p[3] is None else p[3] / 20.0,
                           theme.GREEN))
        series += [(lambda p: p[2] / 100.0, theme.PURPLE),
                   (lambda p: p[1] / ram_max, theme.ACCENT)]
        for value, color in series:
            coords = []
            for p in pts:
                v = value(p)
                if v is None:
                    continue
                x = w - (now - p[0]) / span * w
                y = bottom - max(0.0, min(1.0, v)) * scale
                coords += (x, y)
            if len(coords) >= 4:
                cv.create_line(*coords, fill=theme.c(color), width=2)
