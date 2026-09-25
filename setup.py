"""Build de l'installateur Windows (.msi) avec cx_Freeze.

Usage :
    pip install cx_Freeze
    python setup.py bdist_msi

Produit dist/ServerCraftAgent-<version>-win64.msi
"""
from cx_Freeze import Executable, setup

APP_VERSION = "0.2.0"
APP_NAME = "ServerCraftAgent"

# Raccourcis créés par l'installateur : Bureau + menu Démarrer.
# Table MSI Shortcut : 12 colonnes (Shortcut, Directory_, Name, Component_,
# Target, Arguments, Description, Hotkey, Icon_, IconIndex, ShowCmd, WkDir).
shortcut_table = [
    ("DesktopShortcut", "DesktopFolder", "ServerCraft Agent",
     "TARGETDIR", f"[TARGETDIR]{APP_NAME}.exe",
     None, None, None, None, None, None, "TARGETDIR"),
    ("StartMenuShortcut", "ProgramMenuFolder", "ServerCraft Agent",
     "TARGETDIR", f"[TARGETDIR]{APP_NAME}.exe",
     None, None, None, None, None, None, "TARGETDIR"),
]

build_exe_options = {
    # zip_exclude "*": les packages restent en vrais fichiers dans lib/ —
    # indispensable pour les assets de customtkinter (thèmes .json, polices)
    # et le bundle de certificats de certifi (SSL).
    "zip_exclude_packages": ["*"],
    "packages": ["tkinter", "requests", "darkdetect", "customtkinter", "PIL"],
    "excludes": [
        "pytest", "unittest", "test", "setuptools", "pip", "wheel",
        "IPython", "matplotlib", "numpy", "pandas", "scipy", "torch",
        "cv2", "jupyter_client", "jupyter_core", "notebook", "pygments",
        "prompt_toolkit", "traitlets", "PyQt5", "PyQt6", "PySide2",
        "PySide6", "sphinx", "docutils",
    ],
    "include_msvcr": True,
}

bdist_msi_options = {
    # GUID fixe : permet les mises à jour de version en version
    "upgrade_code": "{8F3D7C1E-2A4B-4E5D-9C6A-1B2E3F4A5B6C}",
    "add_to_path": False,
    "all_users": True,
    "initial_target_dir": rf"[ProgramFilesFolder]\{APP_NAME}",
    "data": {"Shortcut": shortcut_table},
}

setup(
    name=APP_NAME,
    version=APP_VERSION,
    description="Gestionnaire et créateur de serveurs Minecraft automatisé",
    options={
        "build_exe": build_exe_options,
        "bdist_msi": bdist_msi_options,
    },
    executables=[
        Executable(
            "main.py",
            base="Win32GUI",          # pas de console noire au lancement
            target_name=f"{APP_NAME}.exe",
        )
    ],
)
