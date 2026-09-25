# Versions — ServerCraft Agent

## v0.4.0 — Release (2026-09-25)

**Agent IA**
- Nouveaux outils : `search_mods`, `install_mod`, `list_mods`, `remove_mod` —
  l'IA peut chercher, installer et supprimer des mods/plugins Modrinth
  elle-même (« installe JEI et Create » fonctionne directement dans le chat)
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
