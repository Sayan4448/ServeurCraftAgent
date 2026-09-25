"""Providers LLM : Google Gemini (API REST) et Ollama (local, localhost:11434)."""
import requests

GEMINI_API = "https://generativelanguage.googleapis.com/v1beta/models"


class ProviderError(Exception):
    pass


def list_ollama_models(base_url: str = "http://localhost:11434") -> list:
    try:
        r = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=10)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]
    except requests.RequestException:
        return []


def chat(provider: str, messages: list, system: str, settings: dict) -> str:
    """messages : [{"role": "user"|"assistant", "content": str}] -> texte de réponse."""
    if provider == "gemini":
        return _gemini_chat(messages, system, settings)
    if provider == "ollama":
        return _ollama_chat(messages, system, settings)
    raise ProviderError(f"Provider inconnu : {provider}")


def _gemini_chat(messages: list, system: str, settings: dict) -> str:
    key = settings.get("gemini_api_key", "").strip()
    if not key:
        raise ProviderError("Clé API Gemini manquante (onglet Agent IA).")
    model = settings.get("gemini_model", "gemini-2.5-flash").strip()
    url = f"{GEMINI_API}/{model}:generateContent"
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
    r = requests.post(url, params={"key": key}, json=body, timeout=120)
    if r.status_code != 200:
        raise ProviderError(f"Gemini HTTP {r.status_code} : {r.text[:300]}")
    data = r.json()
    try:
        parts = data["candidates"][0]["content"].get("parts", [])
        return "".join(p.get("text", "") for p in parts)
    except (KeyError, IndexError) as e:
        raise ProviderError(f"Réponse Gemini inattendue : {data}") from e


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
