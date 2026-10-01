# Page GitHub

## Description (champ « About », 350 caractères max)

**Français**

> Application Windows pour créer, lancer et administrer des serveurs
> Minecraft sans ligne de commande : Paper, Purpur, Fabric, Forge,
> NeoForge, Mohist. Mods, sauvegardes, inventaires, cross-play Bedrock,
> tunnel Playit.gg.

**English**

> Windows desktop app to create, run and manage Minecraft servers without
> the command line: Paper, Purpur, Fabric, Forge, NeoForge, Mohist. Mods,
> backups, player inventories, Bedrock cross-play, Playit.gg tunnels.

Le dépôt et le README étant en français, garde la description française
si ton public l'est ; l'anglaise touche plus de monde. Tu peux aussi mettre
l'anglaise dans « About » et laisser le README en français.

## Site web (champ « Website »)

Le lien vers la dernière release :
`https://github.com/Sayan4448/ServeurCraftAgent/releases/latest`

## Topics

```
minecraft
minecraft-server
minecraft-server-manager
server-management
paper
fabric
forge
neoforge
modrinth
curseforge
geyser
playit
python
customtkinter
desktop-app
windows
```

GitHub accepte 20 topics au plus. N'ajoute `open-source` qu'une fois un
fichier `LICENSE` présent dans le dépôt.

## Release v1.30.0

**Titre** : `ServerCraft Agent 1.30.0`

**Tag** : `v1.30.0` (sur le commit de la branche fusionnée dans `main`)

**Texte**

> ## ServerCraft Agent 1.30.0
>
> Version centrée sur la fiabilité : une vingtaine de corrections, une
> interface plus nette et quelques outils pour les administrateurs.
>
> ### À retenir
> - **Inventaire des joueurs** : « Retirer » vise enfin la bonne case, et
>   on peut déplacer les objets par glisser-déposer, joueur connecté ou
>   non. Chaque modification est vérifiée auprès du serveur.
> - **Console** : historique des commandes (↑ ↓), filtre, copie.
> - **Whitelist** dans le panneau joueurs, serveur lancé ou arrêté.
> - **Dupliquer un serveur** sur un port libre, pour tester sans risque.
> - **Port déjà utilisé** : signalé avant le lancement.
> - **Interface** : vraies icônes, notifications, raccourcis clavier, aide
>   (F1).
> - **Mods et plugins** : une nouvelle version remplace l'ancienne au lieu
>   de créer un doublon ; erreurs CurseForge expliquées clairement.
>
> Détail complet dans le [CHANGELOG](CHANGELOG.md).
>
> ### Installation
> Télécharge `ServerCraftAgent-1.30.0-win64.msi` ci-dessous et
> double-clique : aucun droit administrateur requis. Tes serveurs et
> réglages existants sont conservés.
>
> Windows 10 et 11.

**Fichier à joindre** : `dist/ServerCraftAgent-1.30.0-win64.msi`
(`python setup.py bdist_msi`).
