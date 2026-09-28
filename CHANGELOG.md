# Versions — ServerCraft Agent

## v0.20.0 — Release (2026-09-29)

**Correctifs de stabilité (boutons / lancement)**
- La console, le statut et les joueurs ne passent plus par des appels Tkinter
  depuis les threads (source des boutons « morts » et de la console vide) :
  `ServerProcess` stocke la console et les joueurs, l'UI les lit toutes les
  150 ms ; les autres threads (mods, créateur, IA) passent par une file
  `ui_call` sûre
- Serveur sélectionné automatiquement et surligné ; nouveau serveur
  sélectionné après création ; plus de reconstruction de la liste pendant un clic
- Statut « ◌ Démarrage… » pendant la préparation de Java
- Java : la version requise est vérifiée à chaque lancement (Java 25 pour
  Minecraft 26.x) avec téléchargement auto d'un JRE compatible
- Plus de fenêtre console noire java.exe ; erreurs de redémarrage affichées
- Tous les boutons : Lancer, Arrêter, Redémarrer, Mods, Config, Dossier
- Comptes Premium / Crack / Les deux ; RAM libre en Go

**Correctif** : les boutons de l'onglet « Mes Serveurs » débordaient de leur
colonne et étaient recouverts par le panneau joueurs — « Lancer » ne répondait
plus. Barre simplifiée à 3 boutons (« ▶ Lancer », « ■ Arrêter »,
« 🧩 Ouvrir les mods ») sur leur propre ligne, démarrage en tâche de fond.

**Import de modpack** (bouton « 📦 Importer un modpack » dans le gestionnaire
de mods) : analyse automatique des .jar — identification via Modrinth
(SHA1 → projet, `client_side`/`server_side`), métadonnées internes
(fabric.mod.json, mods.toml) et liste de mods client connus. Les mods client
sont ignorés par défaut, les serveurs copiés dans `mods/`.

**Statut et adresses**
- Indicateur « ● Lancé / ○ Arrêté » synchronisé en temps réel ; bouton rouge
  « Arrêter » actif uniquement quand le serveur tourne
- **IP locale** (avec port) et **IP publique** affichées au-dessus de la
  console — adresse du tunnel Playit détectée automatiquement

**Configuration du serveur (nouvelle fenêtre ⚙ Config)**
- RAM, port, nombre de joueurs max, MOTD, difficulté, gamemode, PvP,
  command blocks, whitelist, nether, monstres, vol, distances de
  vue/simulation, protection du spawn, hardcore
- Choix du mode de comptes : « Premium uniquement » (`online-mode=true`) ou
  « Premium + crack » (`online-mode=false`)
- Propriété libre `clé=valeur` pour toute autre option de `server.properties`
- Section **Simple Voice Chat** : port UDP et `voice_host` quand le mod est
  installé
- Fenêtre de config aussi accessible depuis l'interface serveur

**Joueurs en ligne**
- Kick et ban avec **saisie de la raison**, op/deop, MP, gamemode, kill,
  unban — dans l'onglet comme dans la fenêtre serveur

**Interface**
- **Thème clair / sombre** (⚙ Paramètres, appliqué au redémarrage)
- 6 langues : Français, English, Русский, 日本語, Español, Deutsch
- Corrections visuelles : couleurs de console dynamiques, callbacks
  thread→UI protégés, boutons synchronisés

**Agent IA — bêta (early access)**
- Option dans ⚙ Paramètres, **désactivée par défaut**, avec avertissement à
  l'activation. Ajoute l'onglet « Agent IA (Bêta) » : installation de
  mods/plugins, recherche Modrinth, construction de structures en jeu
  (prison, maison, tour…), gestion de fichiers — providers : Gemini,
  Anthropic, OpenAI, Ollama, LM Studio, compatible OpenAI.

## v0.10.0 — Release (2026-09-28)

**Suppression de toutes les fonctionnalités IA** (agent, providers, modération
autonome) — l'application se concentre sur la gestion de serveurs.

**Nouveau**
- **Interface serveur** : fenêtre d'administration qui s'ouvre au lancement
  (activable dans ⚙ Paramètres) — console complète + joueurs en ligne avec
  **tête de skin** (Minotar), pseudo et **grade** ; catégories « Admins / OP »
  et « Joueurs », op/deop en un clic, grades persistés dans `ranks.json`
- **Gestionnaire de mods façon ATLauncher/Prism** : fiche détaillée au clic
  (description complète, galerie d'images, catégories), bouton **« Ouvrir la
  page »**, versions compatibles avec installation individuelle
- **Traduction Français / English** (⚙ Paramètres, appliquée au redémarrage)
- Dialog **Paramètres** : langue, interface serveur, clé API CurseForge

## v0.4.0 — Release (2026-09-25)

**Agent IA**
- **Timeline d'activité en direct** : chronomètre + chaque action affichée en
  temps réel (fichier modifié, mod/plugin installé, commande en jeu,
  recherche Modrinth, erreur) avec icônes colorées, puis **résumé final**
  « 📋 2 fichiers modifiés · 1 mod installé · 14 s »
- Nouveaux outils : `search_mods`, `install_mod`, `list_mods`, `remove_mod` —
  l'IA peut chercher, installer et supprimer des mods/plugins Modrinth
  elle-même (« installe JEI et Create » fonctionne directement dans le chat)
- L'IA peut aussi agir **dans le jeu** quand le serveur tourne : nouvel outil
  `build_structure` avec blueprints complets (**prison** avec cellules à
  barreaux et portes en fer, cage, maison, mur, arène, fontaine, tour) —
  plus fill/setblock/summon/give/tp en sur-mesure via send_command
- **Liste des modèles automatique pour tous les providers** : Gemini et
  Anthropic rejoignent OpenAI/Ollama/LM Studio — le champ modèle devient
  une liste déroulante remplie depuis la clé API (⟳ pour rafraîchir),
  toujours éditable à la main

**Icône**
- Nouveau logo « rack serveur » (aucun visuel Minecraft protégé) appliqué
  à l'exe, la fenêtre, les raccourcis et l'installateur

## v0.3.0 — Release (2026-09-25)

**Correctifs majeurs**
- L'app ne démarrait pas depuis Program Files → données déplacées dans
  `%LOCALAPPDATA%\ServerCraftAgent` (serveurs, réglages, JRE)
- Installation **sans droits admin** dans `LocalAppData\Programs` + icône
  d'application, raccourcis Bureau et menu Démarrer fonctionnels

**Gestionnaire de Mods & Plugins (refonte)**
- Cartes avec **icônes**, auteur, téléchargements, description
- Bouton **« Versions »** : liste toutes les versions compatibles
  (release/beta/alpha, date, versions MC) avec installation individuelle
- Pagination « Charger plus » pour parcourir tout le catalogue

## v0.2.0 — Release (2026-09-25)

**Gestionnaire de Mods & Plugins**
- Recherche Modrinth (sans clé) et CurseForge (clé API)
- Installation automatique dans `mods/` ou `plugins/` selon le loader
- Nouveau loader **Mohist** : mods Forge + plugins Bukkit ensemble

**Panneau Joueurs**
- Liste des joueurs connectés en temps réel
- Actions : message privé, kick, ban, unban, op/deop, gamemode, kill

**Mode IA autonome**
- Modération automatique du chat selon des règles personnalisables
- Warn → kick → ban progressif, compteur d'avertissements par joueur

**Installateur**
- MSI allégé (~21 Mo), raccourcis Bureau + menu Démarrer

## v0.1-beta — Beta initiale (2025-09-25)

- Création de serveur 1-clic : Paper, Purpur, Fabric, Forge, NeoForge
- EULA auto, `server.properties` préconfiguré (port, RAM, online-mode)
- Console en direct, lancer/arrêter/redémarrer/supprimer
- Voice Chat : Simple Voice Chat / Plasmo Voice (Modrinth)
- Intégration Playit.gg (voice_host + récapitulatif copiable)
- Agent IA : Gemini, Anthropic, OpenAI, Ollama, LM Studio, compatible OpenAI
- Outils IA : lecture logs, édition configs, commandes console, analyse de logs
- Premier installateur MSI Windows
