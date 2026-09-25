# ServerCraft Agent — Beta 0.1

Application de bureau locale pour **créer, lancer et administrer des serveurs
Minecraft en 1 clic** — sans compte Minecraft requis (mode offline), avec
intégration **Voice Chat**, **Playit.gg** et un **agent IA multi-providers**
(Gemini, Anthropic, OpenAI, Ollama, LM Studio…).

## Installation

### Option 1 — Installateur Windows (.msi)

Télécharge `ServerCraftAgent-x.x.x-win64.msi` depuis la page
[Releases](../../releases), double-clique, puis lance **ServerCraftAgent**
depuis le menu Démarrer. Aucun prérequis : Python est embarqué.

### Option 2 — Depuis les sources

Prérequis : **Python 3.10+** (testé sous Python 3.11 / Windows).

```bash
pip install -r requirements.txt
python main.py
```

Java est détecté automatiquement ; s'il est absent ou trop ancien, un JRE
Temurin 21 est téléchargé dans `runtimes/` (via l'API Adoptium).

## Fonctionnalités

### Onglet « Créateur Rapide »
- Choix du type : **Paper / Purpur** (plugins), **Fabric / Forge / NeoForge** (mods).
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

### Onglet « Mes Serveurs »
- Lancer / Arrêter (`stop` propre) / Redémarrer / Supprimer / Ouvrir le dossier.
- **Console en direct** avec coloration des erreurs et envoi de commandes.

### Onglet « Agent IA & Outils »
- Providers supportés (sélecteur en haut de l'onglet) :
  - **Gemini (Google)** : clé API AI Studio + modèle (`gemini-2.5-flash`).
  - **Anthropic (Claude)** : clé `sk-ant-…` + modèle (`claude-sonnet-4-5`).
  - **OpenAI** : clé `sk-…`, base configurable (`api.openai.com/v1`),
    modèle (`gpt-4o-mini`).
  - **Ollama (local)** : `http://localhost:11434`, modèles auto-détectés.
  - **LM Studio (local)** : `http://localhost:1234/v1`, modèles auto-détectés.
  - **API compatible OpenAI** : n'importe quel endpoint `/v1/chat/completions`
    (Groq, OpenRouter, Together, vLLM…).
- L'agent dispose d'outils sandboxés au dossier du serveur :
  `list_files`, `read_file`, `read_errors`, `server_info`, `write_file`,
  `edit_properties`, `send_command`.
- Bouton **« Analyser les logs »** : extrait les erreurs de `latest.log`,
  diagnostique et applique le correctif directement dans la config.
- Prompts rapides (ex : *« Configure ce serveur pour du RP avec Voice Chat et
  4 Go de RAM »*).

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
# -> dist/ServerCraftAgent-0.1.0-win64.msi
```

## Structure

```
main.py                 # point d'entrée
app/
  config.py             # chemins + settings.json
  core/
    java.py             # détection Java + JRE Temurin auto
    downloader.py       # versions + jars (Paper/Purpur/Fabric/Forge/NeoForge)
    properties.py       # fichiers .properties
    mods.py             # Modrinth (Voice Chat) + Playit
    server_manager.py   # création, process, console
  ai/
    providers.py        # Gemini REST + Ollama /api/chat
    agent.py            # boucle d'outils sandboxée
  ui/
    app_window.py       # fenêtre + tabview
    tab_servers.py      # liste + console live
    tab_creator.py      # formulaire de création
    tab_ai.py           # chat agent + analyseur
servers/                # vos serveurs (servercraft.json = métadonnées)
data/settings.json      # réglages (clé API, provider, modèle)
runtimes/               # JRE téléchargés si besoin
```

## Notes

- **online-mode=false** est la valeur par défaut : les joueurs peuvent rejoindre
  sans compte premium (utile avec Playit/LAN).
- Pour Forge/NeoForge, le lancement réplique `run.bat`
  (`java @user_jvm_args.txt @libraries/.../win_args.txt nogui`) ; la RAM se
  règle via `user_jvm_args.txt` généré automatiquement.
- Aucune télémétrie, aucun compte : tout reste en local.
