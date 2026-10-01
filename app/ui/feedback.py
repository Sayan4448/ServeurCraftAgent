"""Retours visuels légers : notifications « toast » et infobulles.

Tout se passe dans le thread Tk (les threads passent par `ui_call`)."""
import tkinter as tk

import customtkinter as ctk

from . import theme

_KINDS = {
    "success": ("check", theme.GREEN, theme.TINT_GREEN),
    "error": ("error", theme.RED, theme.TINT_RED),
    "warning": ("warning", theme.ORANGE, theme.TINT_ORANGE),
    "info": ("info", theme.ACCENT, theme.TINT_BLUE),
}
_MARGIN = 18
_GAP = 8
_SLIDE = 6             # étapes de l'animation d'entrée


def toast(widget, text: str, kind: str = "info", ms: int = 3200) -> None:
    """Petit message en bas à droite de la fenêtre de `widget`, qui glisse
    en place puis disparaît seul (clic pour le fermer). Non bloquant : ne
    remplace pas une boîte de dialogue quand une décision est attendue."""
    try:
        top = widget.winfo_toplevel()
        if not top.winfo_exists():
            return
    except tk.TclError:
        return
    icon_name, color, tint = _KINDS.get(kind, _KINDS["info"])
    stack = getattr(top, "_sc_toasts", None)
    if stack is None:
        stack = top._sc_toasts = []

    frame = ctk.CTkFrame(top, fg_color=tint, corner_radius=theme.RADIUS_SM,
                         border_width=1, border_color=color)
    img = theme.icon(icon_name, 16, color)
    ctk.CTkLabel(frame, text="" if img else "●", image=img, width=18,
                 text_color=color).pack(side="left", padx=(12, 8), pady=10)
    ctk.CTkLabel(frame, text=text, font=(theme.FONT, 12),
                 text_color=theme.TEXT, justify="left", anchor="w",
                 wraplength=340).pack(side="left", padx=(0, 14), pady=10)

    job = None

    def close(_e=None):
        if frame in stack:
            stack.remove(frame)
        try:
            if job is not None:
                frame.after_cancel(job)
            frame.destroy()
        except tk.TclError:
            return
        _restack(stack)

    for w in (frame, *frame.winfo_children()):
        w.bind("<Button-1>", close)
    stack.append(frame)
    _restack(stack, entering=frame)
    job = frame.after(ms, close)


def _restack(stack: list, entering=None) -> None:
    """Empile les toasts du bas vers le haut ; `entering` glisse depuis le
    bas."""
    offset = _MARGIN
    for frame in reversed(stack):
        try:
            if not frame.winfo_exists():
                continue
            frame.update_idletasks()
            height = frame.winfo_reqheight()
            if frame is entering:
                _slide(frame, offset, _SLIDE)
            else:
                frame.place(relx=1.0, rely=1.0, anchor="se", x=-_MARGIN,
                            y=-offset)
            offset += height + _GAP
        except tk.TclError:
            continue


def _slide(frame, offset: int, step: int) -> None:
    try:
        if not frame.winfo_exists():
            return
        frame.place(relx=1.0, rely=1.0, anchor="se", x=-_MARGIN,
                    y=-offset + step * 5)
        frame.lift()
        if step > 0:
            frame.after(16, _slide, frame, offset, step - 1)
    except tk.TclError:
        pass


class Tooltip:
    """Infobulle au survol (boutons sans texte : thème, +, copier…)."""

    def __init__(self, widget, text: str, delay: int = 450):
        self.widget, self.text, self.delay = widget, text, delay
        self._job = None
        self._tip = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _e=None):
        self._cancel()
        self._job = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self._job is not None:
            try:
                self.widget.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None

    def _show(self):
        self._job = None
        if self._tip is not None or not self.text:
            return
        try:
            if not self.widget.winfo_exists():
                return
            x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
            tip = self._tip = tk.Toplevel(self.widget)
            tip.wm_overrideredirect(True)
            tip.attributes("-topmost", True)
            tk.Label(tip, text=self.text, font=(theme.FONT, 9), padx=8,
                     pady=4, bg=theme.c(theme.PANEL_2),
                     fg=theme.c(theme.TEXT), relief="solid", bd=1).pack()
            tip.update_idletasks()
            tip.wm_geometry(f"+{max(0, x - tip.winfo_width() // 2)}+{y}")
        except tk.TclError:
            self._tip = None

    def _hide(self, _e=None):
        self._cancel()
        tip, self._tip = self._tip, None
        if tip is not None:
            try:
                tip.destroy()
            except tk.TclError:
                pass
