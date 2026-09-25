"""Agent IA : boucle de conversation avec outils fichiers sandboxés au serveur.

Le modèle émet des blocs ```action {"tool": ..., ...} ``` ; l'agent les exécute
dans le dossier du serveur puis renvoie les résultats, jusqu'à réponse finale.
"""
import json
import re
from pathlib import Path

from ..core import server_manager as sm
from ..core import mods as mods_mod
from ..core.properties import load_properties, save_properties
from . import providers

MAX_TOOL_LOOPS = 6
WRITABLE_EXT = {".properties", ".yml", ".yaml", ".json", ".txt", ".cfg", ".toml", ".md"}
ERROR_PATTERN = re.compile(
    r"ERROR|WARN|Exception|Caused by|FAILED|crash|missing|incompatible", re.IGNORECASE
)

ACTION_RE = re.compile(r"```action\s*(\{.*?\})\s*```", re.DOTALL)

SYSTEM_PROMPT = """Tu es l'agent intégré de ServerCraft Agent, un gestionnaire de serveurs Minecraft local.
Tu aides l'utilisateur à administrer son serveur : config, plugins/mods, performances, bugs, crashes.
Réponds en français, de façon concise et actionnable.

Tu peux agir sur les fichiers du serveur en émettant un bloc :
```action
{"tool": "<outil>", "arg1": ..., "arg2": ...}
```
Tu peux émettre plusieurs blocs d'un coup. Après exécution, tu reçois les résultats
et tu peux continuer. Ne mets un bloc action QUE si tu veux réellement l'exécuter.

Outils disponibles :
- list_files(subdir)                : liste les fichiers d'un sous-dossier ("" = racine)
- read_file(path, tail)             : lit un fichier (tail = N dernières lignes, optionnel)
- read_errors(tail)                 : extrait les erreurs/warnings de logs/latest.log
- server_info()                     : métadonnées (loader, version MC, RAM, port, mode)
- write_file(path, content)         : réécrit un fichier de config (.properties/.yml/.json/...)
- edit_properties(path, changes)    : modifie des clés d'un fichier .properties/.yml {clé: valeur}
- send_command(cmd)                 : envoie une commande à la console du serveur (si lancé)
- search_mods(query, kind)          : cherche sur Modrinth ("mod"|"plugin", optionnel) → slug|titre|téléch.
- install_mod(name, kind)           : installe un mod/plugin Modrinth par slug ou nom (recherche auto)
- list_mods()                       : liste les mods/plugins installés sur le serveur
- remove_mod(filename)              : supprime un fichier installé dans mods/ ou plugins/

Règles :
- Les chemins sont relatifs à la racine du serveur (ex: "server.properties", "logs/latest.log",
  "plugins/voicechat/voicechat-server.properties", "config/voicechat/voicechat-server.properties").
- Vérifie l'état réel avec les outils avant de proposer un correctif.
- Quand tu modifies une config, dis exactement ce que tu as changé et pourquoi.
- Pour la RAM, rappelle qu'elle se règle dans les métadonnées du serveur (servercraft.json, clé ram_mb)
  ou via l'onglet "Mes Serveurs", pas dans server.properties.
- Pour installer un mod ou un plugin demandé par l'utilisateur, utilise install_mod directement
  (Modrinth, sans clé) — précise kind="plugin" sur les loaders Bukkit/Paper/Mohist quand pertinent.
  Vérifie avec list_mods() ce qui est déjà installé avant d'installer.
"""


class Agent:
    def __init__(self, server_name: str, settings: dict):
        self.server_name = server_name
        self.dir = sm.server_dir(server_name)
        self.settings = settings
        self.history: list = []

    # ------------------------------------------------------------ conversation

    def run(self, user_msg: str, on_step=None) -> str:
        self.history.append({"role": "user", "content": user_msg})
        for _ in range(MAX_TOOL_LOOPS):
            reply = providers.chat(
                self.settings.get("ai_provider", "gemini"),
                self.history, SYSTEM_PROMPT, self.settings,
            )
            self.history.append({"role": "assistant", "content": reply})
            actions = self._parse_actions(reply)
            if not actions:
                return reply
            results = []
            for act in actions:
                if on_step:
                    on_step(f"⚙ {act.get('tool')} {json.dumps(act, ensure_ascii=False)[:120]}")
                results.append(self._execute(act))
            self.history.append({
                "role": "user",
                "content": "Résultats des actions :\n" + "\n".join(results),
            })
        return "Limite d'actions atteinte. Reformule ou continue la conversation."

    def analyze_logs(self, on_step=None) -> str:
        errors = self._tool_read_errors(500)
        if not errors.strip():
            return "Aucune erreur détectée dans latest.log."
        prompt = (
            "Voici les erreurs récentes de logs/latest.log du serveur. "
            "Analyse-les, identifie la cause racine, puis corrige directement "
            "les fichiers de config si un correctif applicable existe. "
            "Explique ensuite ce que tu as fait.\n\n```\n" + errors + "\n```"
        )
        return self.run(prompt, on_step=on_step)

    def reset(self) -> None:
        self.history.clear()

    # ---------------------------------------------------------------- actions

    @staticmethod
    def _parse_actions(reply: str) -> list:
        out = []
        for m in ACTION_RE.finditer(reply):
            try:
                act = json.loads(m.group(1))
                if isinstance(act, dict) and act.get("tool"):
                    out.append(act)
            except json.JSONDecodeError:
                continue
        return out

    def _safe_path(self, rel: str) -> Path:
        p = (self.dir / rel).resolve()
        if not str(p).startswith(str(self.dir.resolve())):
            raise PermissionError(f"Chemin hors du serveur : {rel}")
        return p

    def _execute(self, act: dict) -> str:
        tool = act.get("tool")
        try:
            handler = getattr(self, f"_tool_{tool}", None)
            if not handler:
                return f"[{tool}] Outil inconnu."
            return handler(**{k: v for k, v in act.items() if k != "tool"})
        except TypeError as e:
            return f"[{tool}] Arguments invalides : {e}"
        except Exception as e:
            return f"[{tool}] Erreur : {e}"

    # ----------------------------------------------------------------- outils

    def _tool_list_files(self, subdir: str = "") -> str:
        base = self._safe_path(subdir or ".")
        if not base.exists():
            return f"Dossier inexistant : {subdir}"
        entries, count = [], 0
        for p in sorted(base.rglob("*")):
            if count >= 300:
                entries.append("... (tronqué)")
                break
            if p.is_file():
                entries.append(str(p.relative_to(self.dir)))
                count += 1
        return "\n".join(entries) or "(vide)"

    def _tool_read_file(self, path: str, tail: int = 0) -> str:
        p = self._safe_path(path)
        if not p.exists():
            return f"Fichier inexistant : {path}"
        text = p.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        if tail:
            lines = lines[-int(tail):]
        return "\n".join(lines[:2000]) or "(vide)"

    def _tool_read_errors(self, tail: int = 400) -> str:
        log = sm.latest_log_path(self.dir)
        if not log.exists():
            return "logs/latest.log introuvable (serveur jamais lancé ?)."
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        hits = [l for l in lines[-int(tail):] if ERROR_PATTERN.search(l)]
        return "\n".join(hits[-120:])

    def _tool_server_info(self) -> str:
        try:
            meta = sm.load_meta(self.dir)
        except OSError:
            return "Métadonnées introuvables."
        meta["running"] = self.server_name in sm.PROCESSES and sm.PROCESSES[
            self.server_name
        ].is_running()
        meta.pop("dir", None)
        return json.dumps(meta, ensure_ascii=False, indent=2)

    def _tool_write_file(self, path: str, content: str) -> str:
        p = self._safe_path(path)
        if p.suffix.lower() not in WRITABLE_EXT:
            return f"Extension non autorisée : {p.suffix}"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"{path} écrit ({len(content)} caractères)."

    def _tool_edit_properties(self, path: str, changes: dict) -> str:
        p = self._safe_path(path)
        props = load_properties(p)
        props.update({k: str(v) for k, v in dict(changes).items()})
        p.parent.mkdir(parents=True, exist_ok=True)
        save_properties(p, props)
        return f"{path} mis à jour : {json.dumps(changes, ensure_ascii=False)}"

    def _tool_send_command(self, cmd: str) -> str:
        proc = sm.PROCESSES.get(self.server_name)
        if not proc or not proc.is_running():
            return "Serveur non lancé — commande non envoyée."
        return "Commande envoyée." if proc.send(cmd) else "Échec d'envoi."

    # ------------------------------------------------------------- mods

    def _meta(self) -> dict:
        return sm.load_meta(self.dir)

    def _tool_search_mods(self, query: str, kind: str = "") -> str:
        meta = self._meta()
        kind = kind or mods_mod.default_kind(meta["loader"])
        hits = mods_mod.search_modrinth(
            query, meta["loader"], meta["mc_version"], kind, limit=6)
        if not hits:
            return f"Aucun résultat Modrinth ({kind}) pour « {query} »."
        return "\n".join(
            f"{h['slug']} | {h['title']} | ⬇{h['downloads']} | {h['description'][:80]}"
            for h in hits)

    def _tool_install_mod(self, name: str, kind: str = "") -> str:
        meta = self._meta()
        loader, mc = meta["loader"], meta["mc_version"]
        if not kind:
            kind = "mod" if mods_mod.supports_mods(loader) else "plugin"
        if kind == "mod" and not mods_mod.supports_mods(loader):
            return f"Le loader {loader} ne supporte pas les mods — utilise kind=\"plugin\"."
        if kind == "plugin" and not mods_mod.supports_plugins(loader):
            return f"Le loader {loader} ne supporte pas les plugins — utilise kind=\"mod\"."
        try:
            path = mods_mod.install_modrinth(name, self.dir, loader, mc, kind)
            return f"{path.name} installé dans {path.parent.name}/."
        except Exception:
            hits = mods_mod.search_modrinth(name, loader, mc, kind, limit=5)
            if not hits:
                return f"« {name} » introuvable sur Modrinth."
            path = mods_mod.install_modrinth(
                hits[0]["slug"], self.dir, loader, mc, kind)
            return (f"{path.name} installé ({hits[0]['title']}) "
                    f"dans {path.parent.name}/.")

    def _tool_list_mods(self) -> str:
        meta = self._meta()
        items = mods_mod.list_installed(self.dir, meta["loader"])
        if not items:
            return "(aucun mod/plugin installé)"
        return "\n".join(f"{i['kind']} | {i['name']}" for i in items)

    def _tool_remove_mod(self, filename: str) -> str:
        for d in ("mods", "plugins"):
            p = self._safe_path(f"{d}/{filename}")
            if p.exists() and p.is_file():
                p.unlink()
                return f"{d}/{filename} supprimé."
        return f"{filename} introuvable dans mods/ ni plugins/."
