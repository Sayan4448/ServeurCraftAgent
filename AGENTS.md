# Notes projet — ServerCraft Agent

## Commandes
- Lancer depuis les sources : `python main.py`
- Vérif syntaxe : `python -m compileall -q app`
- Tests : `pip install -r requirements-dev.txt` puis `python -m pytest`
  (données isolées dans un dossier temporaire, aucun accès réseau ni Java)
- Build MSI : `python setup.py bdist_msi` (fermer `ServerCraftAgent.exe` avant)
- Install test (per-user, sans admin) : `msiexec /i dist\ServerCraftAgent-<ver>-win64.msi /qn`
- Données de l'app installée : `%LOCALAPPDATA%\ServerCraftAgent` (servers/, data/, runtimes/, backups/)
  — pour tester depuis les sources sur ces données : `sys.frozen = True` avant les imports `app`.

## Règles
- **Jamais d'appel Tkinter (widget, `after`) depuis un thread.** Console/joueurs/statut
  sont stockés dans `ServerProcess` (`log()`, `lines_since()`, `tracker`) et lus par
  `_pump()` dans le thread Tk. Les autres threads utilisent `ui.uithread.ui_call()`.
- Tester l'UI dans une vraie `mainloop()` (pilotage par `app.after`), pas avec
  `update()` en boucle : ça masque les bugs de threads.
- Ne jamais committer `data/settings.json` (clés API). Aucune clé API n'est
  livrée avec l'app (CurseForge : clé de l'utilisateur ou `CURSEFORGE_API_KEY`).
- Ne pas supprimer de fonctionnalités/boutons sans demande explicite.
- Version : uniquement dans `app/__init__.py` (`__version__`), lue par `setup.py`
  et par l'interface.
- Changer de page : `App.show_tab()` (met aussi à jour la navigation de
  l'en-tête). `App.tabview` est un `Pages` maison, plus un CTkTabview.
- Couleurs : `theme.ACCENT`… sont lues à la création des widgets ; la couleur
  d'accent choisie est appliquée par `main.py` (`theme.set_accent`) avant
  d'importer l'interface — ne pas importer `app.ui.app_window` avant.
- Textes : toute nouvelle clé va dans `_V130` de `app/i18n.py`, dans les 6 langues
  (un test vérifie que rien ne manque).
- Commandes d'inventaire : passer par `playerdata.slot_name()` — le numéro de case
  NBT n'est pas celui de `/item replace` (`hotbar.0–8`, `inventory.0–26`).
- Tests : ne jamais écouter sur `0.0.0.0` (fenêtre du pare-feu Windows) ; boucle
  locale `127.0.0.1` seulement.
