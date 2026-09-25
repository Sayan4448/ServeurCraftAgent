"""Mode autonome : l'IA surveille le chat et modère selon les règles définies."""
import json
import re
import threading
import time

from ..core import players as pl
from ..core import server_manager as sm
from . import providers

MIN_EVAL_INTERVAL = 1.5  # secondes entre deux évaluations (anti-spam LLM)

MOD_SYSTEM = """Tu es le modérateur automatique d'un serveur Minecraft.
On te donne un message de chat (pseudo + texte) et les règles du serveur.
Réponds UNIQUEMENT avec un JSON sur une seule ligne :
{"action": "ignore|warn|kick|ban", "reason": "courte raison", "reply": "message public optionnel"}
- ignore : rien à signaler (la grande majorité des cas)
- warn   : avertissement au joueur
- kick   : expulsion immédiate
- ban    : bannissement (réservé aux cas graves)
Sois mesuré, pas de sanction pour des messages normaux ou de l'humour légère.
Si le joueur a déjà des warns, durcis progressivement (warn -> kick -> ban)."""

_REGISTRY: dict = {}


class AutonomousModerator:
    """Écoute le flux console, envoie les messages de chat au LLM, applique
    les actions (warn/kick/ban) via la console du serveur."""

    def __init__(self, server_name: str, settings: dict,
                 rules: str, on_event=None):
        self.server_name = server_name
        self.settings = settings
        self.rules = rules or "Aucune insulte, aucun spam, respect entre joueurs."
        self.on_event = on_event        # callback(texte) pour l'UI
        self.enabled = True
        self.warnings = {}              # pseudo -> nb de warns
        self._proc = None
        self._last_eval = 0.0
        self._queue = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------ cycle de vie

    def attach(self) -> bool:
        proc = sm.get_process(self.server_name)
        if proc is self._proc:
            return True
        if self._proc:
            self.detach()
        proc.add_listener(on_line=self._on_line, on_exit=self._on_exit)
        self._proc = proc
        return True

    def detach(self) -> None:
        if self._proc:
            for lst, cb in ((self._proc.listeners, self._on_line),
                            (self._proc.exit_listeners, self._on_exit)):
                if cb in lst:
                    lst.remove(cb)
        self._proc = None
        self.enabled = False

    def _on_exit(self, _name, _code):
        self.warnings.clear()
        if self.on_event:
            self.on_event("Serveur arrêté — modération en pause.")

    # ------------------------------------------------------------ surveillance

    def _on_line(self, name: str, line: str) -> None:
        if not self.enabled or name != self.server_name:
            return
        chat = pl.parse_chat(line)
        if not chat:
            return
        player, msg = chat
        if not self._proc or not self._proc.is_running():
            return
        threading.Thread(target=self._evaluate,
                         args=(player, msg), daemon=True).start()

    def _evaluate(self, player: str, msg: str) -> None:
        with self._lock:
            if time.time() - self._last_eval < MIN_EVAL_INTERVAL:
                return
            self._last_eval = time.time()
        warns = self.warnings.get(player, 0)
        system = (
            MOD_SYSTEM + f"\n\nRègles du serveur : {self.rules}\n"
            f"Le joueur {player} a déjà {warns} avertissement(s)."
        )
        user_msg = f"{player}: {msg}"
        try:
            raw = providers.chat(
                self.settings.get("ai_provider", "gemini"),
                [{"role": "user", "content": user_msg}],
                system, self.settings,
            )
        except providers.ProviderError as e:
            if self.on_event:
                self.on_event(f"Modération : erreur provider — {e}")
            return
        self._apply(player, self._parse_decision(raw), msg)

    @staticmethod
    def _parse_decision(raw: str) -> dict:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return {"action": "ignore"}
        try:
            data = json.loads(m.group(0))
            if data.get("action") in ("ignore", "warn", "kick", "ban"):
                return data
        except json.JSONDecodeError:
            pass
        return {"action": "ignore"}

    def _apply(self, player: str, decision: dict, original: str) -> None:
        action = decision.get("action", "ignore")
        reason = decision.get("reason", "")
        reply = decision.get("reply", "")
        if action == "ignore":
            return
        proc = self._proc
        if not proc or not proc.is_running():
            return

        if action == "warn":
            self.warnings[player] = self.warnings.get(player, 0) + 1
            n = self.warnings[player]
            text = reply or f"Avertissement ({n}) : {reason}"
            proc.send(f"say [Modération] {player} — {text}")
            proc.send(f"msg {player} ⚠ {reason} (warn {n})")
            self._log(f"⚠ warn {player} ({n}) — {reason}")
        elif action == "kick":
            proc.send(f"kick {player} {reason or 'Règles non respectées'}")
            self._log(f"👢 kick {player} — {reason}")
        elif action == "ban":
            proc.send(f"ban {player} {reason or 'Règles non respectées'}")
            self._log(f"🔨 ban {player} — {reason}")
        if reply and action != "warn":
            proc.send(f"say [Modération] {reply}")

    def _log(self, text: str) -> None:
        if self.on_event:
            self.on_event(text)


def get_moderator(server_name: str):
    return _REGISTRY.get(server_name)


def set_moderator(server_name: str, moderator) -> None:
    if moderator is None:
        old = _REGISTRY.pop(server_name, None)
        if old:
            old.detach()
    else:
        _REGISTRY[server_name] = moderator
        moderator.attach()
