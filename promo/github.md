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

## Release v1.0.0

**Titre** : `ServerCraft Agent 1.0.0 Beta`

**Tag** : `v1.0.0` (sur le commit de `main` après fusion). Les anciennes
releases 1.0.0 et 1.30.0 ont été renommées v0.8.0 et v0.9.0.

**Texte**

> ## ServerCraft Agent 1.0.0 Beta
>
> Première version stable : les gros bugs signalés sont corrigés, et
> l'inventaire devient un vrai mode créatif.
>
> ### Corrigé
> - **Bedrock « version incompatible »** sur Forge, NeoForge et les
>   anciennes versions : ViaProxy traduit maintenant la version entre
>   Geyser et le serveur. Geyser se met à jour à chaque démarrage.
> - **Crash avec les comptes crack sur les dernières versions** (Fabric) :
>   les dépendances obligatoires des mods (ViaFabric, Fabric API…) sont
>   installées avec eux, et plus aucun jar d'un autre loader n'est posé.
> - **Playit.gg** : les tunnels se créent enfin.
> - **Anciennes versions** : le bon Java pour chaque version de Minecraft,
>   et pas de plugin trop récent pour lui.
> - **Mods client** écartés de la recherche et de l'installation.
>
> ### Nouveau
> - **Donner un objet comme en créatif** : catalogue de tous les objets du
>   jeu et des mods installés, avec textures et noms traduits.
> - **Vérifier les mods** : repère et désactive (sans supprimer) les
>   fichiers qui empêchent le serveur de démarrer.
> - **Interface refaite** : navigation dans l'en-tête, types de serveur en
>   cartes, couleur de l'interface au choix.
>
> Détail complet dans le [CHANGELOG](CHANGELOG.md).
>
> ### Installation
> Télécharge `ServerCraftAgent-1.0.0-win64.msi` ci-dessous et
> double-clique : aucun droit administrateur requis. Il remplace une
> version déjà installée (même numérotée 1.30.0) ; tes serveurs et
> réglages sont conservés.
>
> Windows 10 et 11.

**Fichier à joindre** : `dist/ServerCraftAgent-1.0.0-win64.msi`
(`python setup.py bdist_msi`).
