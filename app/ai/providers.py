"""Providers LLM : Gemini, Anthropic, OpenAI, Ollama, LM Studio, compatible OpenAI."""
import requests

GEMINI_API = "https://generativelanguage.googleapis.com/v1beta/models"
ANTHROPIC_API = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

PROVIDERS = {
    "gemini": "Gemini (Google)",
    "anthropic": "Anthropic (Claude)",
    "openai": "OpenAI",
    "ollama": "Ollama (local)",
    "lmstudio": "LM Studio (local)",
    "custom": "API compatible OpenAI",
}
LOCAL_PROVIDERS = {"ollama", "lmstudio"}


class ProviderError(Exception):
    pass


# ------------------------------------------------------------------ listage

def list_models(provider: str, settings: dict) -> list:
    """Retourne les modèles disponibles pour un provider (peut être vide)."""
    try:
        if provider == "ollama":
            base = settings.get("ollama_url", "http://localhost:11434").rstrip("/")
            r = requests.get(f"{base}/api/tags", timeout=10)
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]
        if provider == "lmstudio":
            base = settings.get("lmstudio_url", "http://localhost:1234/v1").rstrip("/")
            return _list_openai_models(base)
        if provider == "openai":
            base = settings.get("openai_base", "https://api.openai.com/v1").rstrip("/")
            return _list_openai_models(base, settings.get("openai_api_key", ""))
        if provider == "custom":
            base = settings.get("custom_base", "").rstrip("/")
            if base:
                return _list_openai_models(base, settings.get("custom_key", ""))
    except requests.RequestException:
        pass
    return []


def _list_openai_models(base: str, key: str = "") -> list:
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    r = requests.get(f"{base}/models", headers=headers, timeout=10)
    r.raise_for_status()
    return sorted(m["id"] for m in r.json().get("data", []))


# -------------------------------------------------------------------- chat

def chat(provider: str, messages: list, system: str, settings: dict) -> str:
    """messages : [{"role": "user"|"assistant", "content": str}] -> texte de réponse."""
    if provider == "gemini":
        return _gemini_chat(messages, system, settings)
    if provider == "anthropic":
        return _anthropic_chat(messages, system, settings)
    if provider == "ollama":
        return _ollama_chat(messages, system, settings)
    if provider in ("openai", "lmstudio", "custom"):
        base, key, model = _openai_params(provider, settings)
        return _openai_compatible_chat(messages, system, base, key, model)
    raise ProviderError(f"Provider inconnu : {provider}")


def _gemini_chat(messages: list, system: str, settings: dict) -> str:
    key = settings.get("gemini_api_key", "").strip()
    if not key:
        raise ProviderError("Clé API Gemini manquante (onglet Agent IA).")
    model = settings.get("gemini_model", "gemini-2.5-flash").strip()
    contents = [
        {
            "role": "model" if m["role"] == "assistant" else "user",
            "parts": [{"text": m["content"]}],
        }
        for m in messages
    ]
    body = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": contents,
    }
    r = requests.post(
        f"{GEMINI_API}/{model}:generateContent",
        params={"key": key}, json=body, timeout=120,
    )
    if r.status_code != 200:
        raise ProviderError(f"Gemini HTTP {r.status_code} : {r.text[:300]}")
    data = r.json()
    try:
        parts = data["candidates"][0]["content"].get("parts", [])
        return "".join(p.get("text", "") for p in parts)
    except (KeyError, IndexError) as e:
        raise ProviderError(f"Réponse Gemini inattendue : {data}") from e


def _anthropic_chat(messages: list, system: str, settings: dict) -> str:
    key = settings.get("anthropic_api_key", "").strip()
    if not key:
        raise ProviderError("Clé API Anthropic manquante (onglet Agent IA).")
    model = settings.get("anthropic_model", "claude-sonnet-4-5").strip()
    body = {
        "model": model,
        "max_tokens": 8192,
        "system": system,
        "messages": messages,
    }
    r = requests.post(
        ANTHROPIC_API, json=body, timeout=180,
        headers={"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION},
    )
    if r.status_code != 200:
        raise ProviderError(f"Anthropic HTTP {r.status_code} : {r.text[:300]}")
    blocks = r.json().get("content", [])
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")


def _ollama_chat(messages: list, system: str, settings: dict) -> str:
    base = settings.get("ollama_url", "http://localhost:11434").rstrip("/")
    model = settings.get("ollama_model", "llama3.1").strip()
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}] + messages,
        "stream": False,
    }
    try:
        r = requests.post(f"{base}/api/chat", json=payload, timeout=300)
    except requests.ConnectionError as e:
        raise ProviderError(
            f"Ollama injoignable sur {base} — le serveur est-il lancé ?"
        ) from e
    if r.status_code != 200:
        raise ProviderError(f"Ollama HTTP {r.status_code} : {r.text[:300]}")
    return r.json()["message"]["content"]


def _openai_params(provider: str, settings: dict):
    if provider == "openai":
        return (
            settings.get("openai_base", "https://api.openai.com/v1").rstrip("/"),
            settings.get("openai_api_key", "").strip(),
            settings.get("openai_model", "gpt-4o-mini").strip(),
        )
    if provider == "lmstudio":
        return (
            settings.get("lmstudio_url", "http://localhost:1234/v1").rstrip("/"),
            "",
            settings.get("lmstudio_model", "").strip(),
        )
    return (
        settings.get("custom_base", "").rstrip("/"),
        settings.get("custom_key", "").strip(),
        settings.get("custom_model", "").strip(),
    )


def _openai_compatible_chat(messages: list, system: str, base: str,
                            key: str, model: str) -> str:
    if not base:
        raise ProviderError("URL de l'API manquante (onglet Agent IA).")
    if not model:
        raise ProviderError("Nom du modèle manquant (onglet Agent IA).")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}] + messages,
    }
    try:
        r = requests.post(
            f"{base}/chat/completions", json=body, headers=headers, timeout=300)
    except requests.ConnectionError as e:
        raise ProviderError(f"API injoignable sur {base}") from e
    if r.status_code != 200:
        raise ProviderError(f"API HTTP {r.status_code} : {r.text[:300]}")
    return r.json()["choices"][0]["message"]["content"]
