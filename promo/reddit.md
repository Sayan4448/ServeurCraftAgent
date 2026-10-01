# Reddit

> **Rappel : lis les règles de chaque subreddit avant de poster.** Les
> indications ci-dessous sont des points à vérifier, pas un résumé fiable
> de leurs règles actuelles.

## Où poster

| Subreddit | Pourquoi | À vérifier dans les règles |
|---|---|---|
| **r/admincraft** | Communauté des administrateurs de serveurs Minecraft : le public le plus concerné. | Conditions de l'autopromotion (jour ou fil dédié, flair), outils encore jeunes. |
| **r/feedthebeast** | Minecraft moddé : l'import de modpack avec tri client/serveur les concerne directement. | Flair pour les outils, autopromotion. |
| **r/Python** | L'app est écrite en Python (CustomTkinter) : angle technique. | Posts de projets souvent réservés à un format ou un flair « Showcase », avec des rubriques imposées. |
| **r/Minecraft** | Très grande audience, mais règles strictes. | L'autopromotion et les outils tiers y sont très encadrés : à ne tenter que si les règles l'autorisent clairement. |
| **r/selfhosted** | Hébergement chez soi. | Une app de bureau Windows est à la limite du sujet ; règles sur les projets récents et sur le code écrit avec une IA. À tenter en dernier, ou pas du tout. |
| **r/opensource** | Seulement après avoir ajouté un fichier `LICENSE` au dépôt. | Licence exigée. |

Ordre conseillé : r/admincraft d'abord (le retour le plus utile), puis une
semaine plus tard r/feedthebeast ou r/Python selon l'accueil.

---

## r/admincraft

Ton : entre administrateurs, concret, sans superlatif. Demander un retour.

**Titre**

> I made a free Windows app to create and manage Minecraft servers without the command line — looking for feedback from admins

**Texte**

> Hi all. I run small servers for friends and got tired of doing the same
> setup by hand every time, so I built a desktop app for it. It's called
> ServerCraft Agent, it's free, and the source is on GitHub. I'd like
> feedback from people who actually run servers.
>
> **What it does**
>
> - Creates a Paper, Purpur, Fabric, Forge, NeoForge or Mohist server:
>   downloads the jar, picks a suitable Java (and downloads a Temurin JRE
>   if needed), accepts the EULA, writes server.properties.
> - Dashboard per server: console with command history and a filter,
>   RAM/CPU/TPS graph, players, bans, ops, whitelist.
> - Backups before every stop and on a schedule, with one-click restore.
> - Scheduled restarts and commands, crash detection with optional
>   auto-restart, Discord webhook notifications.
> - Mods/plugins from Modrinth and CurseForge (CurseForge needs your own
>   free API key), and modpack import that leaves client-only mods out.
> - Optional helpers that install third-party tools for you: Geyser +
>   Floodgate for Bedrock cross-play, a Playit.gg tunnel if you can't open
>   ports, AuthMe when you accept offline-mode accounts.
> - A player card with the inventory drawn like in-game; you can give,
>   remove or drag items around, online (via commands) or offline (edits
>   the .dat).
>
> **What it is not**
>
> - Windows only (10/11). No Linux, no web panel — if you run a VPS,
>   Pterodactyl or Crafty are the right tools, not this.
> - A hobby project by one person. It has a test suite now, but it hasn't
>   been battle-tested on big servers.
> - There is an "AI agent" tab; it is a beta, off by default, and not the
>   point of the app.
>
> No telemetry, no account, everything stays on your machine.
>
> GitHub (installer in Releases): [lien]
>
> [capture]
>
> What would you want from a tool like this that's missing? And if you try
> it and something breaks, I'd really like to know.

---

## r/feedthebeast

Ton : joueurs de modpacks. Aller droit à l'import de modpack.

**Titre**

> Free Windows tool that turns a .mrpack or CurseForge zip into a ready-to-run server (and skips the client-only mods)

**Texte**

> I made a small desktop app for running modded servers for friends, and
> the part this sub might care about is the modpack import.
>
> You point it at a `.mrpack` or a CurseForge pack zip. It reads the
> Minecraft version, the loader and the exact loader version from the
> pack, installs that server, downloads the mods and copies the configs.
> Client-only mods (Sodium, Iris, minimaps…) are left out: it checks each
> file against Modrinth's client/server data, then the mod's own metadata,
> then a list of known client mods. Anything it can't classify is listed
> so you can decide.
>
> It also picks a Java version the old loaders can live with, instead of
> whatever is newest on your PC.
>
> Limits, so nobody wastes their time: Windows only; CurseForge packs need
> your own (free) CurseForge API key; packs with unusual server setups
> will still need manual fixes. It's a one-person hobby project.
>
> Loaders: Fabric, Forge, NeoForge (plus Paper/Purpur/Mohist). Free, source
> on GitHub: [lien]
>
> If you try it on a pack and the client/server sorting gets a mod wrong,
> tell me which one — that list is exactly what I want to improve.

---

## r/Python

Ton : technique. Vérifier le format imposé (souvent : ce que fait le
projet, public visé, comparaison).

**Titre**

> ServerCraft Agent – a CustomTkinter desktop app that creates and manages Minecraft servers

**Texte**

> **What My Project Does**
>
> A Windows desktop app that creates Minecraft servers (downloads the
> server jar and a matching JRE), runs them as subprocesses, and gives you
> a dashboard: live console, RAM/CPU graph, players, backups, scheduled
> tasks, mod management through the Modrinth and CurseForge APIs. It also
> reads and edits player inventories, either by parsing the NBT `.dat`
> files (nbtlib) or by sending commands to the running server and reading
> the answer back.
>
> **Target Audience**
>
> People who run a Minecraft server for friends on their own Windows PC
> and don't want to touch a terminal. It is a hobby project, not a
> production hosting panel.
>
> **Comparison**
>
> Web panels such as Pterodactyl or Crafty Controller are built for
> servers and VPSes. This is a local desktop app with no web server and no
> account, closer to a launcher for servers.
>
> **Things that might interest this sub**
>
> - GUI in CustomTkinter. The hard rule that made it stable: worker
>   threads never touch a widget. The server process stores console lines
>   and player state; the Tk thread polls them. Everything else goes
>   through one queue drained by `after()`.
> - Icons are glyphs from a font that ships with Windows, rendered to
>   images with Pillow, so there is no icon pack to bundle.
> - Tests run with pytest, without network or Java: paths are redirected
>   to a temp folder and the server process is faked.
> - Packaged as an MSI with cx_Freeze.
>
> Source: [lien]
>
> Feedback on the structure is welcome — it grew fast and I know some
> modules are too big.

---

## r/Minecraft (seulement si les règles l'autorisent)

Ton : grand public, très court, une image.

**Titre**

> I made a free app that sets up a Minecraft server for you and your friends in one click (Windows)

**Texte**

> You pick a version, click Create, and it downloads everything — server,
> Java, even a free address your friends can join without you opening a
> port on your router (through Playit.gg). There's a dashboard to start
> and stop it, see who's online, and back up the world.
>
> Free, no account, Windows only. It's a personal project, so expect rough
> edges. Link in the comments if that's allowed here.
>
> [capture]
