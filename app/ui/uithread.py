"""Pont thread → UI.

Tkinter n'est pas thread-safe : les threads de travail (téléchargements,
recherches, création de serveur) ne doivent jamais toucher un widget ni
appeler `after()`. Ils passent par `ui_call()`, qui met l'appel en file ; la
fenêtre principale vide la file toutes les 50 ms dans le thread Tk et ignore
les appels destinés à une fenêtre déjà fermée.
"""
import queue
import tkinter as tk
import traceback

_q: "queue.Queue" = queue.Queue()


def ui_call(widget, fn, *args) -> None:
    """Exécute fn(*args) dans le thread Tk si `widget` existe encore."""
    _q.put((widget, fn, args))


def install(root, interval: int = 50) -> None:
    def drain():
        try:
            while True:
                widget, fn, args = _q.get_nowait()
                try:
                    if widget is None or widget.winfo_exists():
                        fn(*args)
                except tk.TclError:
                    pass              # widget enfant détruit entre-temps
                except Exception:  # noqa: BLE001
                    traceback.print_exc()
        except queue.Empty:
            pass
        try:
            root.after(interval, drain)
        except (RuntimeError, tk.TclError):
            pass
    drain()
