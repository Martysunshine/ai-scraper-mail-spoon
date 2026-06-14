"""Thin wrapper around a local Ollama server via the OpenAI-compatible API.

Hermes / OpenClaw run a local model (e.g. ``hermes3``). We talk to it through
the OpenAI Python client pointed at ``http://127.0.0.1:11434/v1`` so no cloud
API and no paid keys are involved.
"""

from __future__ import annotations

from dataclasses import dataclass

from openai import OpenAI

from .config import get_settings


class OllamaUnavailable(RuntimeError):
    """Raised when the local model cannot be reached or errors out."""


@dataclass
class LLMResult:
    text: str
    model: str


def _client() -> OpenAI:
    s = get_settings()
    return OpenAI(base_url=s.ollama_base_url, api_key=s.ollama_api_key, timeout=60.0)


def check_connection() -> str:
    """Ping the local model. Returns the model name on success.

    Raises ``OllamaUnavailable`` with a clear message if it cannot connect.
    """
    s = get_settings()
    try:
        client = _client()
        resp = client.chat.completions.create(
            model=s.ollama_model,
            messages=[{"role": "user", "content": "Reply with the single word: ok"}],
            max_tokens=5,
            temperature=0.0,
        )
        _ = resp.choices[0].message.content
        return s.ollama_model
    except Exception as exc:  # noqa: BLE001 — surface any transport/model error
        raise OllamaUnavailable(
            f"Could not reach the local Ollama model '{s.ollama_model}' at "
            f"{s.ollama_base_url}. Is Ollama running and the model pulled? "
            f"Original error: {exc}"
        ) from exc


def chat(
    system: str,
    user: str,
    *,
    temperature: float = 0.4,
    max_tokens: int = 700,
) -> LLMResult:
    """Single-turn chat completion against the local model."""
    s = get_settings()
    try:
        client = _client()
        resp = client.chat.completions.create(
            model=s.ollama_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        text = (resp.choices[0].message.content or "").strip()
        return LLMResult(text=text, model=s.ollama_model)
    except Exception as exc:  # noqa: BLE001
        raise OllamaUnavailable(str(exc)) from exc
