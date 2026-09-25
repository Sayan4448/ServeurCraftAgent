"""Agent IA : boucle de conversation avec outils fichiers sandboxés au serveur.

Le modèle émet des blocs ```action {"tool": ..., ...} ``` ; l'agent les exécute
dans le dossier du serveur puis renvoie les résultats, jusqu'à réponse finale.
"""
import json
import re
import time
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
- Si le serveur est lancé, tu peux aussi agir DANS LE JEU via send_command : construire une
  structure (fill, setblock, clone), invoquer des entités (summon), donner des items (give),
  téléporter (tp), etc. Décris ensuite ce que tu as construit/fait.
"""


class Agent:
    def __init__(self, server_name: str, settings: dict):
        self.server_name = server_name
        self.dir = sm.server_dir(server_name)
        self.settings = settings
        self.history: list = []

    # ------------------------------------------------------------ conversation

    def run(self, user_msg: str, on_step=None) -> str:
        self.stats = {"files": set(), "mods": [], "removed": [],
                      "commands": [], "searches": [], "errors": 0}
        self._start_ts = time.time()
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
                res, ev = self._execute(act)
                self._track(ev, act, res)
                if on_step:
                    on_step(ev)
                results.append(res)
            self.history.append({
                "role": "user",
                "content": "Résultats des actions :\n" + "\n".join(results),
            })
        return "Limite d'actions atteinte. Reformule ou continue la conversation."

    def summary(self) -> str:
        """Résumé lisible des actions effectuées pendant le dernier run."""
        if not hasattr(self, "stats"):
            return ""
        s = self.stats
        parts = []
        if s["files"]:
            parts.append(f"{len(s['files'])} fichier(s) modifié(s) : "
                         + ", ".join(sorted(s["files"])[:5]))
        if s["mods"]:
            parts.append(f"{len(s['mods'])} mod/plugin installé(s) : "
                         + ", ".join(s["mods"][:5]))
        if s["removed"]:
            parts.append(f"{len(s['removed'])} supprimé(s) : "
                         + ", ".join(s["removed"][:5]))
        if s["commands"]:
            parts.append(f"{len(s['commands'])} commande(s) en jeu")
        if s["searches"]:
            parts.append(f"{len(s['searches'])} recherche(s) Modrinth")
        if s["errors"]:
            parts.append(f"{s['errors']} erreur(s)")
        if not parts:
            return ""
        elapsed = time.time() - self._start_ts
        return "📋 Résumé : " + " · ".join(parts) + f" — {elapsed:.0f} s"

    def _track(self, ev: dict, act: dict, res: str) -> None:
        k = ev["kind"]
        if k == "error":
            self.stats["errors"] += 1
        elif k == "file":
            self.stats["files"].add(act.get("path", ""))
        elif k == "mod":
            self.stats["mods"].append(res.split(" install")[0])
        elif k == "del":
            self.stats["removed"].append(act.get("filename", ""))
        elif k == "cmd":
            self.stats["commands"].append(act.get("cmd", ""))
        elif k == "search":
            self.stats["searches"].append(act.get("query", ""))

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

    def _execute(self, act: dict):
        """Exécute un outil -> (résultat pour le modèle, événement pour l'UI)."""
        tool = act.get("tool")
        try:
            handler = getattr(self, f"_tool_{tool}", None)
            if not handler:
                res = f"[{tool}] Outil inconnu."
            else:
                res = handler(**{k: v for k, v in act.items() if k != "tool"})
        except TypeError as e:
            res = f"[{tool}] Arguments invalides : {e}"
        except Exception as e:
            res = f"[{tool}] Erreur : {e}"
        return res, self._event(tool, act, res)

    @staticmethod
    def _event(tool: str, act: dict, res: str) -> dict:
        """Traduit une exécution d'outil en événement lisible pour l'UI."""
        low = res.lower()
        error = any(m in low for m in (
            "erreur", "inconnu", "invalide", "inexistant", "introuvable",
            "échec", "non autorisée", "non lancé"))
        icon, text, kind = "⚙", tool, "info"
        if tool == "list_files":
            icon, text = "📁", f"Liste des fichiers ({act.get('subdir') or 'racine'})"
        elif tool == "read_file":
            icon, text = "📖", f"Lecture de {act.get('path')}"
        elif tool == "read_errors":
            icon, text = "🔍", "Analyse des erreurs de latest.log"
        elif tool == "server_info":
            icon, text = "ℹ️", "Lecture des informations serveur"
        elif tool == "write_file":
            icon, text, kind = "📝", f"Fichier réécrit : {act.get('path')}", "file"
        elif tool == "edit_properties":
            keys = ", ".join(act.get("changes", {}).keys())
            icon, text, kind = "🔧", f"Config modifiée : {act.get('path')} ({keys})", "file"
        elif tool == "send_command":
            icon, text, kind = "⚡", f"Commande en jeu : {act.get('cmd')}", "cmd"
        elif tool == "search_mods":
            icon, text, kind = "🔍", f"Recherche Modrinth : « {act.get('query')} »", "search"
        elif tool == "install_mod":
            icon, text, kind = "🧩", f"Installation de « {act.get('name')} »", "mod"
            if not error:
                text += f" → {res.split(' install')[0]}"
        elif tool == "list_mods":
            icon, text = "🧩", "Liste des mods/plugins installés"
        elif tool == "remove_mod":
            icon, text, kind = "🗑️", f"Suppression de {act.get('filename')}", "del"
        if error:
            icon, kind = "❌", "error"
            text += f" — {res[:100]}"
        return {"icon": icon, "text": text, "kind": kind}

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
