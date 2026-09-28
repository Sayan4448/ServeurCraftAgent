# ServerCraft Agent

Application de bureau locale pour **créer, lancer et administrer des serveurs
Minecraft en 1 clic** — sans compte Minecraft requis (mode offline), avec
**gestionnaire de mods/plugins** façon ATLauncher/Prism (Modrinth + CurseForge),
**interface d'administration serveur** (console + joueurs avec têtes et grades),
intégration **Voice Chat** / **Playit.gg**. Interface traduite en
**français, anglais, russe, japonais, espagnol et allemand**, thème
**clair ou sombre**.

## Installation

### Option 1 — Installateur Windows (.msi)

Télécharge `ServerCraftAgent-x.x.x-win64.msi` depuis la page
[Releases](../../releases), double-clique — **aucun droit administrateur requis**
(installation par utilisateur). Un raccourci est créé sur le **Bureau** et dans
le **menu Démarrer**, avec l'icône de l'application.

### Option 2 — Depuis les sources

Prérequis : **Python 3.10+** (testé sous Python 3.11 / Windows).

```bash
pip install -r requirements.txt
python main.py
```

Java est détecté automatiquement ; s'il est absent ou trop ancien, un JRE
Temurin 21 est téléchargé dans `%LOCALAPPDATA%\ServerCraftAgent\runtimes`.

## Fonctionnalités

### Onglet « Créateur Rapide »
- Choix du type : **Paper / Purpur** (plugins), **Fabric / Forge / NeoForge**
  (mods), **Mohist** (mods Forge + plugins Bukkit ensemble).
- Versions récupérées en direct depuis les API officielles
  (papermc.io, purpurmc.org, Fabric Meta, Forge promotions, Maven NeoForge).
- Téléchargement du `server.jar`, exécution automatique des installeurs
  Forge/NeoForge (`--installServer`), `eula.txt` accepté, `server.properties`
  préconfiguré (port, RAM, online-mode, MOTD…).
- **Voice Chat** : installation automatique de *Simple Voice Chat* ou
  *Plasmo Voice* depuis Modrinth (dans `plugins/` ou `mods/` selon le loader).
- **Playit.gg** : renseignez l'adresse du tunnel + ports publics TCP/UDP —
  l'app renseigne `voice_host` dans `voicechat-server.properties` et génère un
  récapitulatif copiable (`PLAYIT-README.txt`).

### Cross-play Java + Bedrock
Case « Cross-play » (créateur ou ⚙ Config) : l'app installe et configure
seule **Geyser Standalone** (proxy Bedrock sur UDP 19132, lancé et arrêté avec
le serveur), **Floodgate** (joueurs Bedrock sans compte Java), **ViaVersion +
ViaBackwards**. Compatible avec les comptes Crack, Premium et Les deux. Pour
jouer depuis Internet, ouvrez/tunnelisez aussi le port **UDP 19132**.

### Onglet « Mes Serveurs »
- **Tableau de bord** : RAM utilisée / limite, CPU, joueurs, durée en ligne.
- **Statut en direct** : « ● Lancé » (vert) / « ○ Arrêté » ; le bouton rouge
  « Arrêter » n'est actif que quand le serveur tourne.
- **IP** affichée au-dessus de la console : IP locale (+ port) et IP publique
  ou adresse du tunnel Playit.
- Lancer / Arrêter (`stop` propre) / Redémarrer / Supprimer / Ouvrir le dossier.
- **Console en direct** avec coloration des erreurs et envoi de commandes.
- **Panneau joueurs** : liste en temps réel ; clic sur ⋯ → message privé,
  kick/ban **avec raison**, unban, op/deop, gamemode, kill.
- Bouton **Mods/Plugins** : gestionnaire intégré.
- Bouton **⚙ Config** : fenêtre de configuration du serveur.

### Interface serveur (fenêtre d'administration)
Quand l'option « Interface serveur » est activée (⚙ Paramètres), le lancement
d'un serveur ouvre une fenêtre dédiée :
- **Console de commandes** complète (envoi direct, logs colorés).
- **Joueurs en ligne** : tête du skin (Minotar), pseudo et grade.
- **Grades et catégories** : définir un grade (Admin, Modo, VIP…) et trier les
  joueurs entre « Admins / OP » et « Joueurs ». Op/deop en un clic, stocké dans
  `ranks.json` du serveur.
- **IP locale/publique** dans l'en-tête ; boutons « Lancer » (arrêté) /
  « Arrêter » (rouge, lancé) synchronisés.

### Configuration du serveur (fenêtre ⚙ Config)
- Édition de `server.properties` : port, **nombre de joueurs**, MOTD,
  difficulté, gamemode, PvP, **command blocks**, whitelist, nether, monstres,
  vol, distances de vue/simulation, protection du spawn, hardcore…
- **Comptes** : « Premium uniquement » (`online-mode=true`) ou
  « Premium + crack » (`online-mode=false`).
- RAM allouée et champ libre `clé=valeur` pour toute autre propriété.
- **Simple Voice Chat** : port UDP et `voice_host` quand le mod est installé.

### Agent IA — bêta (early access)
Option expérimentale dans ⚙ Paramètres (**désactivée par défaut**, un
avertissement s'affiche à l'activation). Ajoute l'onglet « Agent IA (Bêta) » :
- installe des **mods/plugins** depuis Modrinth, fait des recherches,
  modifie les fichiers de config ;
- **construit en jeu** (prison, maison, tour, arène…) quand le serveur tourne ;
- providers : Gemini, Anthropic (Claude), OpenAI, Ollama, LM Studio,
  compatible OpenAI — modèles détectés automatiquement.

### Gestionnaire de Mods & Plugins (façon ATLauncher/Prism)
- Recherche sur **Modrinth** (sans clé) et **CurseForge** (clé API gratuite —
  console.curseforge.com, configurable dans ⚙ Paramètres).
- Cartes avec **icône**, auteur, téléchargements, description.
- **Fiche détaillée** au clic : description complète, **galerie d'images**,
  catégories, bouton **« Ouvrir la page »** (navigateur) et liste des
  **versions compatibles** (release/beta/alpha) avec installation individuelle.
- Pagination « Charger plus » : tout le catalogue est parcourable.
- Installation **automatique** dans `mods/` ou `plugins/` selon le loader —
  aucun chemin à saisir. Sur **Mohist**, les deux types cohabitent.

### Paramètres (⚙ en haut à droite)
- **Langue** : Français / English / Русский / 日本語 / Español / Deutsch.
- **Thème** : sombre ou clair.
- **Interface serveur** au lancement (on/off).
- **Agent IA (bêta)** : activation avec avertissement.
- **Clé API CurseForge**.

## Playit.gg — mode d'emploi

1. Sur [playit.gg](https://playit.gg), créez un tunnel **TCP** vers
   `localhost:25565` (Minecraft) et, si Voice Chat, un tunnel **UDP** vers
   `localhost:24454`.
2. Notez l'adresse publique (`xxx.gl.joinmc.link`) et les ports publics.
3. Dans le créateur, cochez « Configurer un tunnel playit.gg » et renseignez
   les champs — le récapitulatif généré indique l'adresse à donner aux joueurs.
4. Lancez l'agent playit sur votre machine (téléchargeable sur playit.gg).

## Construire l'installateur .msi

```bash
pip install cx_Freeze
python setup.py bdist_msi
# -> dist/ServerCraftAgent-0.20.0-win64.msi
```

## Structure

```
main.py                 # point d'entrée
app/
  config.py             # chemins + settings.json
  i18n.py               # traductions FR/EN/RU/JA/ES/DE
  ai/                   # Agent IA (bêta, optionnel) : providers, agent, autonomie
  core/
    java.py             # détection Java + JRE Temurin auto
    downloader.py       # versions + jars (Paper/Purpur/Fabric/Forge/NeoForge/Mohist)
    properties.py       # fichiers .properties
    mods.py             # Modrinth + CurseForge + Voice Chat + Playit
    players.py          # tracking join/leave + actions admin
    ranks.py            # grades/catégories joueurs (ranks.json)
    server_net.py       # IP locale/publique, adresse Playit
    server_manager.py   # création, process, console
    structures.py       # blueprints de constructions (bêta IA)
  ui/
    app_window.py       # fenêtre + tabview + paramètres
    tab_servers.py      # liste + console live + IP + statut
    tab_creator.py      # formulaire de création
    mods_manager.py     # navigateur de mods + fiches détaillées
    server_window.py    # interface serveur (console + joueurs + grades)
    server_settings.py  # configuration du serveur (properties + voice chat)
servers/                # vos serveurs (servercraft.json = métadonnées)
%LOCALAPPDATA%\ServerCraftAgent\   # données de l'app installée
```

## Notes

- **online-mode=false** par défaut : les joueurs peuvent rejoindre sans compte
  premium (utile avec Playit/LAN). Les têtes de skin s'affichent quand même via
  Minotar (skin par défaut pour les pseudos hors-ligne).
- Pour Forge/NeoForge, le lancement réplique `run.bat`
  (`java @user_jvm_args.txt @libraries/.../win_args.txt nogui`) ; la RAM se
  règle via `user_jvm_args.txt` généré automatiquement.
- Aucune télémétrie, aucun compte : tout reste en local.
