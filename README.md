# ServerCraft Agent — édition Rust (préversion)

Réécriture en Rust de ServerCraft Agent, faite **en parallèle** de la
version Python (branche `main`), qui reste la version officielle.

Les deux versions partagent les mêmes données
(`%LOCALAPPDATA%\ServerCraftAgent` : `servers/`, `data/`, `runtimes/`) :
un serveur créé avec l'une s'ouvre dans l'autre, avec le même compte
Playit.

## Étape 1 (cette branche)
- Liste des serveurs, création (Paper, Purpur, Fabric, Forge, NeoForge,
  Mohist), Java trouvé ou téléchargé tout seul ; comptes crack protégés
  par mot de passe (AuthMe sur les plugins, EasyAuth sur Fabric)
- Lancer / arrêter (arrêt propre, puis forcé après 30 s), console avec
  commandes, joueurs connectés
- Playit.gg : liaison du compte, tunnels Java / Bedrock / Voice Chat
  (Simple Voice Chat et Plasmo Voice, adresse écrite dans le mod)
- Sauvegardes du monde (même format et même dossier `backups/` que la
  version Python) : bouton « 💾 Sauvegarder » (même serveur lancé :
  save-off / save-all / save-on), avant chaque arrêt, automatiques toutes
  les N minutes, rotation des automatiques, restauration (le monde actuel
  est sauvegardé avant), suppression

Pas encore : cross-play Bedrock, mods/plugins, modpacks,
tâches planifiées, inventaire des joueurs, Discord, agent IA, OpenCode,
autres langues que le français.

## Développement
- `cargo run` — l'app (données dans `SERVERCRAFT_HOME` si défini)
- `cargo test`
- Windows : le `.exe` est compilé par GitHub Actions à chaque push
  (onglet Actions → Artifacts)
