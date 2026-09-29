# Versions — ServerCraft Agent

## v0.8.0 — (2026-09-29)

**Sauvegardes automatiques**
- Zip du monde (`world`, `world_nether`, `world_the_end`) dans
  `backups/<serveur>/`, hors du dossier serveur
- Serveur lancé : `save-off` → `save-all flush` → zip → `save-on`
  (réponses masquées de la console)
- Avant chaque arrêt et redémarrage (fermeture de l'app comprise) et à
  intervalle configurable ; rotation des N dernières sauvegardes auto —
  les manuelles ne sont jamais supprimées
- Bouton **« Restaurer »** dans « Mes Serveurs » : liste des sauvegardes,
  restauration avec confirmation (copie de sécurité du monde actuel juste
  avant), sauvegarde manuelle, suppression
- Réglages dans ⚙ Config → « Sauvegardes »

**Tâches planifiées** (⚙ Config → « Tâches planifiées »)
- Redémarrage quotidien à heure fixe (HH:MM), annoncé en jeu
  « redémarrage dans 5 min », 1 min et 10 s — sauvegarde avant
  redémarrage si activée
- Commandes planifiées personnalisées : « toutes les N min » ou « à
  HH:MM » (say, save-all, weather…), tracées dans la console

**Créer un serveur depuis un modpack** (Créateur → « 📦 Depuis un modpack… »)
- `.mrpack` (Modrinth) et zip CurseForge (`manifest.json`) : loader,
  version de Minecraft et **version exacte du loader** (Fabric, Forge,
  NeoForge) reprises du pack — repli sur la dernière si introuvable
- Mods serveur téléchargés, mods client ignorés, configs du pack
  (`overrides/`, `server-overrides/`) copiées
- Java adapté aux anciens loaders : Java borné (ex. 21 pour MC 1.21)
  cherché parmi tous les Java installés, sinon JRE téléchargé — Java 25
  faisait planter Fabric Loader 0.16

**Notifications Discord** (⚙ Paramètres → « Notifications Discord »)
- Webhook configurable + bouton « Tester » ; événements au choix :
  serveur lancé / arrêté / crashé (avec les dernières lignes de la
  console), joueur qui rejoint / quitte
- Envoi en file d'attente (jamais bloquant), limite de débit Discord
  respectée, mentions désactivées — rien n'est envoyé si le champ est vide

**Détection de crash** (⚙ Config → « Détection de crash »)
- Un arrêt sans commande « stop » (ni depuis l'app, ni `/stop` en jeu)
  est signalé comme crash dans la console
- Au choix : rien, proposer de relancer (par défaut), ou redémarrage
  automatique après 10 s
- Anti-boucle : nombre de tentatives limité sur 10 min (3 par défaut),
  puis retour à la proposition ; pas de relance auto si le serveur plante
  pendant son démarrage

**Monitoring** (⚙ Paramètres → « Graphique de monitoring »)
- Graphique temps réel RAM / CPU des 2 dernières minutes dans le tableau
  de bord (1 mesure par seconde, thème clair/sombre)
- TPS pour Paper/Purpur via `/tps` toutes les 5 s — réponse masquée de la
  console, interrogé seulement quand le graphique est affiché
- Une seule source de mesure CPU (le tableau de bord et la fenêtre serveur
  ne se volent plus la mesure `cpu_percent`)

## v0.7.0 — Release (2026-09-28)

Version consolidée avant la 1.0. Reprend tout le contenu de la 0.5.5 :
- **Fiche joueur** « Carte & inventaire » : mini-carte du monde (.mca,
  sans plugin), coordonnées exactes, inventaire + Ender chest gérables
  en ligne ou hors ligne
- **Tunnels Playit.gg** multiples (Java/Bedrock/Voice Chat + ajouts
  illimités), adresse du tunnel = puce « Internet »
- **Bannis & Opérateurs** administrables hors ligne (OP avant déban)
- **Import de modpack** .mrpack / CurseForge / dossier avec tri
  client/serveur automatique
- Console : réponses des commandes internes masquées (plus de spam
  « There are X of a max… »), mémoire allégée

## v0.5.5 — Release (2026-09-28)

**Fiche joueur « Carte & inventaire »** (menu ⋯ d'un joueur → 🗺)
- **Mini-carte** : rendu top-down des vrais chunks du monde autour du joueur
  (lecture directe des régions .mca, aucun plugin), marqueur rouge +
  flèche du regard, zoom 1/2/4 chunks
- **Coordonnées exactes** : X/Y/Z + monde (Surface/Nether/End), vie, faim,
  XP, mode de jeu — en direct via `data get` si le joueur est en ligne,
  sinon dernière position enregistrée
- **Inventaire** : les 41 cases (armure, main gauche, inventaire, barre)
  + **Ender chest** ; donner un objet (catalogue filtrable), retirer une
  case, tout vider. En ligne → commandes `item replace`/`give`/`clear` ;
  hors ligne → écriture directe du `playerdata` NBT

**Tunnels Playit.gg multiples**
- 3 lignes par défaut (Java, Bedrock, Voice Chat) + « ＋ Ajouter » illimité,
  dans le créateur **et** dans ⚙ Config
- L'adresse du tunnel Java devient la puce **« Internet »** du tableau de
  bord (celle à donner aux amis) ; l'IP de la box n'apparaît plus qu'avec
  l'explication qu'elle nécessite d'ouvrir le port — Playit reste la
  solution simple
- `PLAYIT-README.txt` régénéré avec tous les tunnels ; `voice_host` de
  Simple Voice Chat renseigné automatiquement si un tunnel UDP pointe
  vers le port vocal

**Bannis & Opérateurs (hors ligne)**
- Vues « Bannis » et « Opérateurs » dans l'onglet joueurs et la fenêtre
  serveur : liste des bannis (raison, date, source, IP), **OP avant
  déban**, déban/OP/deop **même serveur arrêté** (édition directe de
  `banned-players.json`, `banned-ips.json`, `ops.json`)

**Import de modpack** : `.mrpack` (Modrinth), `.zip` CurseForge et dossiers
d'instances Prism/ATLauncher en plus des zip de jars — tri client/serveur
par hash SHA1 → Modrinth, métadonnées internes et liste de mods client
connus ; installation depuis la fenêtre de résultat

**Correctifs**
- Console : les réponses des commandes internes (`list`, `data get`,
  `give`…) ne polluent plus la console — masquées mais conservées dans
  le backlog pour les modules qui en ont besoin
- Mémoire : backlog serveur ramené à 4000 lignes ; la carte RAM affiche
  le processus Java réel (Java monte jusqu'à sa limite -Xmx, c'est
  normal — baisser la RAM dans ⚙ Config pour un serveur léger)

## v0.5.0 — Release (2026-09-29)

**Nouvelle interface**
- Tableau de bord par serveur : pastille d'état, IP cliquables (copie),
  cartes **Mémoire** (utilisée / limite + RAM du PC), **Processeur**,
  **Joueurs** (x / max) et **En ligne depuis**
- Boutons grisés quand indisponibles (plus de faux boutons « actifs »)
- Thème clair / sombre **instantané** (bouton ☀/☾ en haut, sans redémarrer)
- Boutons segmentés lisibles en mode clair, en-tête et onglets redessinés

**Cross-play Java + Bedrock (automatique)**
- Case « Cross-play » dans le créateur et la Config : installe
  **Geyser Standalone** (proxy Bedrock UDP 19132, démarré/arrêté avec le
  serveur), **Floodgate** (Bedrock sans compte Java), **ViaVersion +
  ViaBackwards** ; clé Floodgate et port configurés tout seuls
- Fonctionne avec les comptes **Crack**, **Premium** et **Les deux**
- « Les deux » installe automatiquement **AuthMe** (plugins) / **EasyAuth**
  (Fabric) : les joueurs crack font /register, personne ne vole un pseudo

**Par défaut** : comptes « Les deux », PvP et monstres activés

**Correctifs**
- Java resté ouvert après fermeture brutale de l'app → détecté et arrêté au
  lancement (c'était la cause du « le serveur ne se lance plus »)
- Fermer l'app arrête proprement les serveurs (avec confirmation)
- Accents corrects dans la console (Java forcé en UTF-8), codes couleur
  ANSI retirés, `list` envoyé seulement une fois le serveur prêt

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
