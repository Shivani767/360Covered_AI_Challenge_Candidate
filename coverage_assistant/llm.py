"""Model adapters.

Three provider families are supported, all reached over plain HTTP with the
standard library so the project has **no third-party runtime dependency**:

* ``OpenAIProvider``      - chat completions, api.openai.com
* ``AnthropicProvider``   - messages API, api.anthropic.com
* ``OpenAICompatibleProvider`` - any OpenAI-compatible endpoint (Ollama,
  vLLM, LM Studio, Together, ...). Selected with ``LLM_BASE_URL``.

Plus one non-LLM adapter:

* ``OfflineDeterministicProvider`` - renders a safe answer from the fact
  pack. It is **not** a language model and every answer it produces is
  prefixed with an explicit non-LLM label so it can never be mistaken for
  one.

Two operational controls are enforced for every live provider:
  * a per-call token cap,
  * a per-session call cap (a hard spend ceiling).

API keys are read from the environment only. Nothing here ever writes a key
to disk or logs one.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MAX_TOKENS = 700
DEFAULT_MAX_CALLS = 40
DEFAULT_RETRIES = 2


class ProviderError(RuntimeError):
    """Raised when a model call cannot be completed.

    Carries a human-readable message so the UI can surface something useful
    instead of a stack trace.
    """


class MissingCredentialError(ProviderError):
    """Raised when live mode is requested but no API key is configured."""


class SpendCapError(ProviderError):
    """Raised when the session call budget is exhausted."""


@dataclass
class ProviderConfig:
    """Configuration for a live provider."""

    provider: str = "openai"
    model: str = "gpt-4o-mini"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    timeout: int = DEFAULT_TIMEOUT_SECONDS
    max_tokens: int = DEFAULT_MAX_TOKENS
    max_calls: int = DEFAULT_MAX_CALLS
    retries: int = DEFAULT_RETRIES
    extra_headers: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls, provider: Optional[str] = None) -> "ProviderConfig":
        """Build a config from environment variables.

        Recognised variables:
          OPENAI_API_KEY, ANTHROPIC_API_KEY, LLM_API_KEY, LLM_BASE_URL,
          LLM_MODEL, LLM_PROVIDER, LLM_TIMEOUT, LLM_MAX_TOKENS,
          LLM_MAX_CALLS.
        """
        chosen = (provider or os.environ.get("LLM_PROVIDER") or "").strip().lower()
        if not chosen:
            if os.environ.get("OPENAI_API_KEY"):
                chosen = "openai"
            elif os.environ.get("ANTHROPIC_API_KEY"):
                chosen = "anthropic"
            else:
                chosen = "openai"

        if chosen == "openai":
            model = os.environ.get("LLM_MODEL") or "gpt-4o-mini"
            api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY")
        elif chosen == "anthropic":
            model = os.environ.get("LLM_MODEL") or "claude-3-5-haiku-latest"
            api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("LLM_API_KEY")
        else:
            model = os.environ.get("LLM_MODEL") or "llama3.1"
            api_key = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")

        return cls(
            provider=chosen,
            model=model,
            api_key=api_key,
            base_url=os.environ.get("LLM_BASE_URL"),
            timeout=int(os.environ.get("LLM_TIMEOUT", DEFAULT_TIMEOUT_SECONDS)),
            max_tokens=int(os.environ.get("LLM_MAX_TOKENS", DEFAULT_MAX_TOKENS)),
            max_calls=int(os.environ.get("LLM_MAX_CALLS", DEFAULT_MAX_CALLS)),
        )


class BaseProvider:
    """Common interface: turn a chat message list into a string."""

    name = "base"
    is_llm = True

    def __init__(self, config: Optional[ProviderConfig] = None) -> None:
        self.config = config or ProviderConfig()
        self.calls = 0

    # -- spend control ------------------------------------------------
    def _check_budget(self) -> None:
        if self.calls >= self.config.max_calls:
            raise SpendCapError(
                f"Session call limit reached ({self.config.max_calls} calls). "
                "Reset the conversation or raise LLM_MAX_CALLS to continue."
            )

    def complete(self, messages: Sequence[Dict[str, str]]) -> str:
        raise NotImplementedError

    # -- helpers ------------------------------------------------------
    @staticmethod
    def _post_json(
        url: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
        timeout: int,
        retries: int = DEFAULT_RETRIES,
    ) -> Dict[str, Any]:
        """POST JSON with bounded retries and a clear error message."""
        body = json.dumps(payload).encode("utf-8")
        last_error: Optional[str] = None
        for attempt in range(retries + 1):
            request = urllib.request.Request(url, data=body, method="POST")
            request.add_header("Content-Type", "application/json")
            for key, value in headers.items():
                request.add_header(key, value)
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    raw = response.read().decode("utf-8")
                return json.loads(raw)
            except urllib.error.HTTPError as exc:
                detail = ""
                try:
                    detail = exc.read().decode("utf-8")[:500]
                except Exception:  # pragma: no cover - best-effort diagnostics
                    detail = ""
                last_error = f"HTTP {exc.code} from {url}: {detail}"
                # 4xx (except 429) will not succeed on retry.
                if exc.code < 500 and exc.code != 429:
                    break
            except urllib.error.URLError as exc:
                last_error = f"Network error calling {url}: {exc.reason}"
            except TimeoutError:
                last_error = f"Request to {url} timed out after {timeout}s"
            except json.JSONDecodeError as exc:
                last_error = f"Malformed JSON response from {url}: {exc}"
                break
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
        raise ProviderError(last_error or f"Request to {url} failed.")


class OpenAIProvider(BaseProvider):
    """OpenAI chat completions (also used for OpenAI-compatible endpoints)."""

    name = "openai"

    def __init__(self, config: Optional[ProviderConfig] = None) -> None:
        super().__init__(config)
        if not self.config.api_key:
            raise MissingCredentialError(
                "No API key found. Set OPENAI_API_KEY (or LLM_API_KEY) in your "
                "environment, or run the assistant in offline mode."
            )

    @property
    def base_url(self) -> str:
        return (self.config.base_url or "https://api.openai.com/v1").rstrip("/")

    def complete(self, messages: Sequence[Dict[str, str]]) -> str:
        self._check_budget()
        payload = {
            "model": self.config.model,
            "messages": list(messages),
            "max_tokens": self.config.max_tokens,
            "temperature": 0.2,
        }
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        headers.update(self.config.extra_headers)
        data = self._post_json(
            f"{self.base_url}/chat/completions",
            payload,
            headers,
            self.config.timeout,
            self.config.retries,
        )
        self.calls += 1
        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"Unexpected response shape from provider: {data}") from exc


class AnthropicProvider(BaseProvider):
    """Anthropic Messages API."""

    name = "anthropic"

    def __init__(self, config: Optional[ProviderConfig] = None) -> None:
        super().__init__(config)
        if not self.config.api_key:
            raise MissingCredentialError(
                "No API key found. Set ANTHROPIC_API_KEY (or LLM_API_KEY) in your "
                "environment, or run the assistant in offline mode."
            )

    @property
    def base_url(self) -> str:
        return (self.config.base_url or "https://api.anthropic.com/v1").rstrip("/")

    def complete(self, messages: Sequence[Dict[str, str]]) -> str:
        self._check_budget()
        system = "\n\n".join(m["content"] for m in messages if m.get("role") == "system")
        turns = [m for m in messages if m.get("role") != "system"]
        payload: Dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "temperature": 0.2,
            "messages": turns,
        }
        if system:
            payload["system"] = system
        headers = {
            "x-api-key": self.config.api_key,
            "anthropic-version": "2023-06-01",
        }
        headers.update(self.config.extra_headers)
        data = self._post_json(
            f"{self.base_url}/messages",
            payload,
            headers,
            self.config.timeout,
            self.config.retries,
        )
        self.calls += 1
        try:
            blocks = data["content"]
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            return text.strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"Unexpected response shape from provider: {data}") from exc


class OpenAICompatibleProvider(OpenAIProvider):
    """Any OpenAI-compatible endpoint: Ollama, vLLM, LM Studio, gateways.

    Enabled by setting ``LLM_BASE_URL``. The default local example is
    ``http://127.0.0.1:11434/v1``.
    """

    name = "openai-compatible"


class OfflineDeterministicProvider(BaseProvider):
    """Deterministic, rule-based answer builder. **Not a language model.**

    It renders a safe answer directly from the fact pack so that reviewers
    can run the safety suite with no credentials and no network. Every
    answer carries the ``OFFLINE_DETERMINISTIC`` label so it can never be
    mistaken for model output.
    """

    name = "offline"
    is_llm = False

    def complete(self, messages: Sequence[Dict[str, str]]) -> str:
        self._check_budget()
        self.calls += 1
        fact_pack = _extract_fact_pack(messages)
        return render_offline_answer(fact_pack)


def _extract_fact_pack(messages: Sequence[Dict[str, str]]) -> Dict[str, Any]:
    """Recover the fact pack from the system message.

    The offline adapter receives the same prompt as a live model, so it
    parses the machine-readable block back out. If the block is missing or
    malformed it falls back to a minimal, always-safe message.
    """
    for message in messages:
        content = message.get("content", "")
        marker = "FACT_PACK_JSON_START"
        if marker in content:
            start = content.index(marker) + len(marker)
            end = content.find("FACT_PACK_JSON_END", start)
            if end != -1:
                try:
                    return json.loads(content[start:end].strip())
                except json.JSONDecodeError:
                    return {}
    return {}


def render_offline_answer(fact_pack: Dict[str, Any]) -> str:
    """Build a safe, catalog-grounded answer without a language model."""
    if not fact_pack:
        return (
            "OFFLINE_DETERMINISTIC - NOT AN LLM. I could not build a grounded "
            "answer for that request."
        )

    from .offline_render import render_answer  # local import to avoid a cycle

    return render_answer(fact_pack)


def build_provider(mode: str = "offline", config: Optional[ProviderConfig] = None) -> BaseProvider:
    """Factory used by the assistant and the CLI.

    mode:
      "offline"  - deterministic, credential-free (not an LLM)
      "live"     - a real LLM call; requires an API key
    """
    chosen = (mode or "offline").strip().lower()
    if chosen in ("offline", "deterministic", "test"):
        return OfflineDeterministicProvider(config or ProviderConfig(provider="offline"))
    if chosen in ("live", "llm", "openai"):
        cfg = config or ProviderConfig.from_env("openai")
        if cfg.provider == "anthropic":
            return AnthropicProvider(cfg)
        if cfg.base_url:
            return OpenAICompatibleProvider(cfg)
        return OpenAIProvider(cfg)
    if chosen == "anthropic":
        return AnthropicProvider(config or ProviderConfig.from_env("anthropic"))
    raise ValueError(f"Unknown mode '{mode}'. Use 'offline' or 'live'.")
