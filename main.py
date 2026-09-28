"""ServerCraft Agent - lanceur et gestionnaire de serveurs Minecraft.

Lancement :  python main.py
"""
import customtkinter as ctk

from app.config import ensure_dirs, load_settings
from app.ui import theme
from app.ui.app_window import App


def main() -> None:
    ensure_dirs()
    theme.apply(load_settings().get("theme", "dark"))
    ctk.set_default_color_theme("blue")
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
