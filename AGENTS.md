# Notes projet — ServerCraft Agent

## Commandes
- Lancer depuis les sources : `python main.py`
- Vérif syntaxe : `python -m compileall -q app`
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
- Ne jamais committer `data/settings.json` (clés API).
- Ne pas supprimer de fonctionnalités/boutons sans demande explicite.
