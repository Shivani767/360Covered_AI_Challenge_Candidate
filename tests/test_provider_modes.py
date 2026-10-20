"""Provider-mode tests with mocks: OpenAI, Ollama (openai-compatible), offline.

No real API keys, no network, no paid calls. Every test exercises actual
application code (provider construction, request shape, response parsing,
malformed-output handling, repair-once, safe fallback, guardrails).
"""
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from conftest_helper import ROOT  # noqa: F401
from coverage_assistant import CoverageAssistant
from coverage_assistant.llm import (
    MissingCredentialError,
    OpenAICompatibleProvider,
    OpenAIProvider,
    ProviderConfig,
    ProviderError,
    build_provider,
)
from coverage_assistant.guardrails import validate_answer


class _MockHandler(BaseHTTPRequestHandler):
    """Scripted mock HTTP server recording requests."""

    reply_queue = None
    status = 200
    requests = []

    def log_message(self, fmt, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) or b"{}"
        try:
            type(self).requests.append(json.loads(body))
        except json.JSONDecodeError:
            type(self).requests.append({})
        if type(self).reply_queue is None:
            self.send_response(500)
            self.end_headers()
            return
        if type(self).reply_queue:
            reply = type(self).reply_queue.pop(0)
        else:
            reply = {"choices": [{"message": {"content": ""}}]}
        payload = json.dumps(reply).encode()
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def start_mock(replies=None, status=200):
    _MockHandler.reply_queue = list(replies) if replies else None
    _MockHandler.status = status
    _MockHandler.requests = []
    server = HTTPServer(("127.0.0.1", 0), _MockHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


class _Env:
    """Context manager that sets env vars and restores them."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.saved = {}

    def __enter__(self):
        for key, value in self.kwargs.items():
            self.saved[key] = os.environ.pop(key, None)
            if value is not None:
                os.environ[key] = value
        return self

    def __exit__(self, *exc):
        for key, saved in self.saved.items():
            if saved is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = saved


class ProviderSelectionTest(unittest.TestCase):
    def test_offline_mode_uses_deterministic_provider(self):
        p = build_provider("offline")
        self.assertEqual(p.name, "offline")
        self.assertFalse(p.is_llm)

    def test_openai_provider_from_key(self):
        with _Env(OPENAI_API_KEY="sk-test", LLM_PROVIDER=None, LLM_BASE_URL=None):
            p = build_provider("live")
            self.assertEqual(p.name, "openai")
            self.assertTrue(p.is_llm)

    def test_ollama_via_openai_compatible(self):
        with _Env(LLM_PROVIDER="openai-compatible", LLM_API_KEY="x",
                  LLM_BASE_URL="http://localhost:11434/v1",
                  LLM_MODEL="qwen2.5:3b"):
            p = build_provider("live")
            self.assertEqual(p.name, "openai-compatible")
            self.assertEqual(p.base_url, "http://localhost:11434/v1")
            self.assertEqual(p.config.model, "qwen2.5:3b")

    def test_ollama_without_api_key(self):
        with _Env(LLM_PROVIDER="openai-compatible", LLM_API_KEY=None,
                  LLM_BASE_URL="http://localhost:11434/v1",
                  LLM_MODEL="qwen2.5:3b",
                  OPENAI_API_KEY=None):
            p = OpenAICompatibleProvider(
                ProviderConfig(
                    provider="openai-compatible",
                    model="qwen2.5:3b",
                    api_key=None,
                    base_url="http://localhost:11434/v1",
                )
            )
            self.assertEqual(p.name, "openai-compatible")

    def test_openai_requires_api_key(self):
        with self.assertRaises(MissingCredentialError):
            OpenAIProvider(ProviderConfig(provider="openai", api_key=None))

    def test_explicit_llm_provider_overrides_auto(self):
        with _Env(OPENAI_API_KEY="sk-openai", ANTHROPIC_API_KEY="sk-ant",
                  LLM_PROVIDER="anthropic"):
            p = build_provider("live")
            self.assertEqual(p.name, "anthropic")


class ProviderRequestConstructionTest(unittest.TestCase):
    def setUp(self):
        self.server, self.port = start_mock(
            [{"choices": [{"message": {"content": "$100 deductible."}}]}]
        )

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_openai_request_shape(self):
        config = ProviderConfig(
            provider="openai",
            model="gpt-4o-mini",
            api_key="sk-test",
            base_url=f"http://127.0.0.1:{self.port}/v1",
        )
        provider = OpenAIProvider(config)
        provider.complete([{"role": "user", "content": "hello"}])
        req = _MockHandler.requests[0]
        self.assertEqual(req["model"], "gpt-4o-mini")
        self.assertEqual(req["messages"], [{"role": "user", "content": "hello"}])
        self.assertEqual(req["temperature"], 0.2)
        self.assertLessEqual(req["max_tokens"], 700)

    def test_ollama_request_shape(self):
        config = ProviderConfig(
            provider="openai-compatible",
            model="qwen2.5:3b",
            api_key="x",
            base_url=f"http://127.0.0.1:{self.port}/v1",
        )
        provider = OpenAICompatibleProvider(config)
        provider.complete([{"role": "user", "content": "hello"}])
        req = _MockHandler.requests[0]
        self.assertEqual(req["model"], "qwen2.5:3b")
        self.assertIn("messages", req)


class ResponseParsingTest(unittest.TestCase):
    def test_openai_response_parsing(self):
        server, port = start_mock(
            [{"choices": [{"message": {"content": "CoreDrive is $89/month."}}]}]
        )
        try:
            config = ProviderConfig(
                provider="openai", model="gpt-4o-mini", api_key="sk-test",
                base_url=f"http://127.0.0.1:{port}/v1",
            )
            provider = OpenAIProvider(config)
            text = provider.complete([{"role": "user", "content": "hi"}])
            self.assertEqual(text, "CoreDrive is $89/month.")
        finally:
            server.shutdown()
            server.server_close()

    def test_ollama_response_parsing(self):
        server, port = start_mock(
            [{"choices": [{"message": {"content": "CoreDrive Plus is $139/month."}}]}]
        )
        try:
            config = ProviderConfig(
                provider="openai-compatible", model="qwen2.5:3b",
                api_key="x", base_url=f"http://127.0.0.1:{port}/v1",
            )
            provider = OpenAICompatibleProvider(config)
            text = provider.complete([{"role": "user", "content": "hi"}])
            self.assertEqual(text, "CoreDrive Plus is $139/month.")
        finally:
            server.shutdown()
            server.server_close()

    def test_content_none_is_malformed(self):
        server, port = start_mock(
            [{"choices": [{"message": {"content": None}}]}]
        )
        try:
            config = ProviderConfig(
                provider="openai-compatible", model="qwen2.5:3b",
                api_key="x", base_url=f"http://127.0.0.1:{port}/v1",
            )
            provider = OpenAICompatibleProvider(config)
            with self.assertRaises(ProviderError):
                provider.complete([{"role": "user", "content": "hi"}])
        finally:
            server.shutdown()
            server.server_close()

    def test_empty_content_is_malformed(self):
        server, port = start_mock(
            [{"choices": [{"message": {"content": ""}}]}]
        )
        try:
            config = ProviderConfig(
                provider="openai-compatible", model="qwen2.5:3b",
                api_key="x", base_url=f"http://127.0.0.1:{port}/v1",
            )
            provider = OpenAICompatibleProvider(config)
            text = provider.complete([{"role": "user", "content": "hi"}])
            self.assertEqual(text, "")
        finally:
            server.shutdown()
            server.server_close()

    def test_unexpected_shape_raises(self):
        server, port = start_mock([{"foo": "bar"}])
        try:
            config = ProviderConfig(
                provider="openai-compatible", model="qwen2.5:3b",
                api_key="x", base_url=f"http://127.0.0.1:{port}/v1",
            )
            provider = OpenAICompatibleProvider(config)
            with self.assertRaises(ProviderError):
                provider.complete([{"role": "user", "content": "hi"}])
        finally:
            server.shutdown()
            server.server_close()




class MalformedOutputAndRepairTest(unittest.TestCase):
    """Repair attempted exactly once, then safe fallback."""

    def _assistant_with_server(self, replies):
        _MockHandler.reply_queue = list(replies)
        _MockHandler.requests = []
        server, port = start_mock(replies)
        config = ProviderConfig(
            provider="openai-compatible", model="mock", api_key="x",
            base_url=f"http://127.0.0.1:{port}/v1", retries=0,
        )
        provider = OpenAICompatibleProvider(config)
        bot = CoverageAssistant(provider=provider)
        return bot, server, port

    def test_repair_then_fallback_metadata(self):
        bot, server, port = self._assistant_with_server([
            {"choices": [{"message": {"content": "CoreDrive is $999/month."}}]},
            {"choices": [{"message": {"content": "CoreDrive is $999/month."}}]},
        ])
        try:
            answer = bot.answer(
                "What does CoreDrive cost?",
                {
                    "eligible_ids": ["P-BASE", "P-PLUS"],
                    "visible_ids": ["P-BASE", "P-PLUS"],
                    "selected_id": "P-BASE",
                    "selected_options": [],
                },
            )
            trace = bot.last_trace
            self.assertTrue(trace.fallback_used)
            self.assertIn("SAFE_FALLBACK", answer)
            self.assertNotIn("$999", answer)
            self.assertEqual(trace.provider_calls, 2)
        finally:
            server.shutdown()
            server.server_close()

    def test_repair_succeeds(self):
        bot, server, port = self._assistant_with_server([
            {"choices": [{"message": {"content": "CoreDrive is $999/month."}}]},
            {"choices": [{"message": {"content": "CoreDrive is $89 per month."}}]},
        ])
        try:
            answer = bot.answer(
                "What does CoreDrive cost?",
                {
                    "eligible_ids": ["P-BASE", "P-PLUS"],
                    "visible_ids": ["P-BASE", "P-PLUS"],
                    "selected_id": "P-BASE",
                    "selected_options": [],
                },
            )
            trace = bot.last_trace
            self.assertTrue(trace.repaired)
            self.assertFalse(trace.fallback_used)
            self.assertIn("$89", answer)
        finally:
            server.shutdown()
            server.server_close()

class ProviderFailureTest(unittest.TestCase):
    def test_timeout_surfaces_clear_error(self):
        config = ProviderConfig(
            provider="openai-compatible", model="mock", api_key="x",
            base_url="http://127.0.0.1:1/v1", timeout=1, retries=0,
        )
        provider = OpenAICompatibleProvider(config)
        with self.assertRaises(ProviderError):
            provider.complete([{"role": "user", "content": "hi"}])

    def test_auth_failure_surfaces_clear_error(self):
        server, port = start_mock(
            [{"error": {"message": "invalid api key"}}], status=401
        )
        try:
            config = ProviderConfig(
                provider="openai-compatible", model="mock", api_key="bad",
                base_url=f"http://127.0.0.1:{port}/v1", retries=0,
            )
            provider = OpenAICompatibleProvider(config)
            with self.assertRaises(ProviderError) as ctx:
                provider.complete([{"role": "user", "content": "hi"}])
            self.assertIn("401", str(ctx.exception))
        finally:
            server.shutdown()
            server.server_close()

    def test_unavailable_endpoint_raises(self):
        config = ProviderConfig(
            provider="openai-compatible", model="mock", api_key="x",
            base_url="http://127.0.0.1:9999/v1", timeout=2, retries=0,
        )
        provider = OpenAICompatibleProvider(config)
        with self.assertRaises(ProviderError):
            provider.complete([{"role": "user", "content": "hi"}])


class GuardrailsAppliedToProvidersTest(unittest.TestCase):
    """Same guardrails regardless of provider."""

    def _validate(self, answer, **state_overrides):
        from coverage_assistant.catalog import Catalog
        from coverage_assistant.facts import build_fact_pack, detect_intent
        from coverage_assistant.state import normalize_state, resolve_referent
        state = {
            "eligible_ids": ["P-BASE", "P-PLUS"],
            "visible_ids": ["P-BASE", "P-PLUS"],
            "selected_id": "P-BASE",
            "selected_options": [],
        }
        state.update(state_overrides)
        catalog = Catalog.load()
        norm = normalize_state(state, catalog)
        intent = detect_intent("What does this cover?")
        referent = resolve_referent("What does this cover?", norm, catalog)
        fact_pack = build_fact_pack(
            "What does this cover?", norm, referent, catalog, intent
        )
        return validate_answer(answer, norm, catalog, fact_pack)

    def test_unsupported_component_rejected(self):
        result = self._validate("CoreDrive covers the alternator.")
        self.assertFalse(result.ok)

    def test_exclusion_not_confused_with_coverage(self):
        from coverage_assistant.catalog import Catalog
        from coverage_assistant.facts import build_fact_pack, detect_intent
        from coverage_assistant.state import normalize_state, resolve_referent
        catalog = Catalog.load()
        state = {
            "eligible_ids": ["P-WRAP"],
            "visible_ids": ["P-WRAP"],
            "selected_id": "P-WRAP",
            "selected_options": [],
        }
        norm = normalize_state(state, catalog)
        intent = detect_intent("Is engine covered by DriveWrap?")
        referent = resolve_referent("Is engine covered by DriveWrap?", norm, catalog)
        fact_pack = build_fact_pack(
            "Is engine covered by DriveWrap?", norm, referent, catalog, intent
        )
        result = validate_answer(
            "Yes, the engine is covered by DriveWrap.", norm, catalog, fact_pack
        )
        self.assertFalse(result.ok)

    def test_monetary_misattribution_rejected(self):
        result = self._validate("CoreDrive is $139 per month.")
        self.assertFalse(result.ok)

    def test_unpurchased_option_rejected(self):
        result = self._validate(
            "Your navigation screen is covered.",
            selected_id="P-PLUS",
            selected_options=[],
        )
        self.assertFalse(result.ok)


