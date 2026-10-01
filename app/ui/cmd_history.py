"""Historique des commandes d'une console (flèches ↑ / ↓), comme dans un
terminal. Sans Tk : la console branche ses touches dessus."""


class CommandHistory:
    def __init__(self, limit: int = 100):
        self.limit = limit
        self._items: list = []
        self._index = None            # None = pas en train de naviguer
        self._draft = ""              # texte en cours de saisie, à rendre

    def add(self, command: str) -> None:
        command = command.strip()
        self._index = None
        if not command:
            return
        if command in self._items:    # une commande répétée remonte
            self._items.remove(command)
        self._items.append(command)
        del self._items[:-self.limit]

    def previous(self, current: str = "") -> str:
        """↑ : commande plus ancienne (reste sur la première)."""
        if not self._items:
            return current
        if self._index is None:
            self._draft = current
            self._index = len(self._items) - 1
        elif self._index > 0:
            self._index -= 1
        return self._items[self._index]

    def next(self, current: str = "") -> str:
        """↓ : commande plus récente, puis retour au texte en cours."""
        if self._index is None:
            return current
        if self._index < len(self._items) - 1:
            self._index += 1
            return self._items[self._index]
        self._index = None
        return self._draft

    def bind(self, entry) -> None:
        """Branche ↑ / ↓ sur un champ de saisie (CTkEntry)."""
        def show(text):
            entry.delete(0, "end")
            entry.insert(0, text)
            return "break"
        entry.bind("<Up>", lambda _e: show(self.previous(entry.get())))
        entry.bind("<Down>", lambda _e: show(self.next(entry.get())))
