"""ServerCraft Agent - lanceur et gestionnaire de serveurs Minecraft.

Lancement :  python main.py
"""
import customtkinter as ctk

from app.config import ensure_dirs, load_settings
from app.ui import theme


def main() -> None:
    ensure_dirs()
    settings = load_settings()
    theme.apply(settings.get("theme", "dark"))
    # avant d'importer l'interface : ses modules lisent les couleurs
    theme.set_accent(settings.get("accent", "blue"))
    ctk.set_default_color_theme("blue")
    from app.ui.app_window import App
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
