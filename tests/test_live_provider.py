"""Live-provider tests against a local mock HTTP server.

These prove the live path really performs an HTTP LLM call, that the
response is used, and that an unsafe model answer is caught and repaired or
replaced. No real API key and no network access are needed.

The mock server speaks the OpenAI chat-completions shape, which is also the
shape used by Anthropic-compatible gateways and most local servers.
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
    ProviderConfig,
    build_provider,
)
from coverage_assistant.prompts import PROMPT_VERSION


class _MockHandler(BaseHTTPRequestHandler):
    """Returns a scripted reply and records the request it received."""

    reply = "P-PLUS has a $100 deductible and costs $139 per month."
    requests = []

    def log_message(self, fmt, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        type(self).requests.append(body)
        payload = {
            "choices": [
                {"message": {"content": type(self).reply}}
            ]
        }
        out = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


class LiveProviderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), _MockHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _provider(self, reply):
        _MockHandler.reply = reply
        _MockHandler.requests = []
        config = ProviderConfig(
            provider="openai-compatible",
            model="mock-model",
            api_key="test-key-not-a-real-secret",
            base_url=f"http://127.0.0.1:{self.port}/v1",
            max_calls=10,
        )
        return OpenAICompatibleProvider(config)

    def test_live_call_returns_model_answer(self):
        provider = self._provider("P-PLUS has a $100 deductible and costs $139 per month.")
        bot = CoverageAssistant(provider=provider)
        answer = bot.answer(
            "What is the deductible?",
            {
                "eligible_ids": ["P-PLUS"],
                "visible_ids": ["P-PLUS"],
                "selected_id": "P-PLUS",
                "selected_options": [],
            },
        )
        self.assertIn("$100", answer)
        self.assertIn("LIVE LLM", bot.mode_label)
        self.assertTrue(bot.is_live_llm)
        self.assertEqual(len(_MockHandler.requests), 1)

    def test_live_request_carries_the_fact_pack(self):
        provider = self._provider("P-PLUS has a $100 deductible.")
        bot = CoverageAssistant(provider=provider)
        bot.answer(
            "What is the deductible?",
            {
                "eligible_ids": ["P-PLUS"],
                "visible_ids": ["P-PLUS"],
                "selected_id": "P-PLUS",
                "selected_options": [],
            },
        )
        request = _MockHandler.requests[0]
        system = request["messages"][0]["content"]
        self.assertIn("FACT_PACK_JSON_START", system)
        self.assertIn("$100", system)  # the deductible is in the fact pack
        self.assertIn('"deductible": 100', system)  # and in raw form
        self.assertEqual(request["model"], "mock-model")
        self.assertLessEqual(request["max_tokens"], 700)

    def test_unsafe_model_answer_is_caught_and_replaced(self):
        """An unsafe model reply must not reach the customer as-is."""
        provider = self._provider(
            "P-EXCL is the best plan and it covers everything at $99 per month."
        )
        bot = CoverageAssistant(provider=provider)
        answer = bot.answer(
            "Which plan is best?",
            {
                "eligible_ids": ["P-BASE", "P-PLUS"],
                "visible_ids": ["P-BASE", "P-PLUS"],
                "selected_id": "P-PLUS",
                "selected_options": [],
            },
        )
        trace = bot.last_trace
        self.assertTrue(trace.violations, "unsafe answer should have been flagged")
        self.assertTrue(trace.repaired or trace.fallback_used)
        self.assertNotIn("$99", answer)
        # The replacement must still be grounded in the catalog.
        self.assertIn("$139", answer)

    def test_prompt_version_is_recorded_in_the_trace(self):
        """A false claim must be attributable to the prompt that produced it."""
        provider = self._provider("P-PLUS has a $100 deductible.")
        bot = CoverageAssistant(provider=provider)
        bot.answer(
            "What is the deductible?",
            {
                "eligible_ids": ["P-PLUS"],
                "visible_ids": ["P-PLUS"],
                "selected_id": "P-PLUS",
                "selected_options": [],
            },
        )
        self.assertEqual(bot.last_trace.prompt_version, PROMPT_VERSION)
        self.assertIn(PROMPT_VERSION, bot.last_trace.as_dict()["prompt_version"])

    # -- final validation status ---------------------------------------
    #
    # The reviewer must be able to tell, for every turn, whether the answer
    # the customer actually received passed the guardrails. `violations`
    # describes the first draft; `final_violations` describes the delivered
    # answer. A draft that was rejected and then repaired must not be shown
    # as a failure of the delivered answer.

    def test_clean_answer_has_no_violations_and_is_final_ok(self):
        provider = self._provider("P-PLUS has a $100 deductible.")
        bot = CoverageAssistant(provider=provider)
        bot.answer(
            "What is the deductible?",
            {
                "eligible_ids": ["P-PLUS"],
                "visible_ids": ["P-PLUS"],
                "selected_id": "P-PLUS",
                "selected_options": [],
            },
        )
        trace = bot.last_trace
        self.assertEqual(trace.violations, [])
        self.assertEqual(trace.final_violations, [])
        self.assertTrue(trace.final_ok)
        self.assertFalse(trace.repaired)
        self.assertFalse(trace.fallback_used)

    def test_repaired_answer_is_final_ok_even_though_the_draft_failed(self):
        """A rejected draft that was repaired yields a clean delivered answer."""
        provider = self._provider("P-PLUS has a $100 deductible.")
        bot = CoverageAssistant(provider=provider)
        # The scripted mock always returns the same reply, so the repair
        # attempt is rejected too and the deterministic fallback is used.
        bot.answer(
            "Which plan is best?",
            {
                "eligible_ids": ["P-BASE", "P-PLUS"],
                "visible_ids": ["P-BASE", "P-PLUS"],
                "selected_id": "P-PLUS",
                "selected_options": [],
            },
        )
        trace = bot.last_trace
        # Nothing unsafe was delivered, so the final state is clean.
        self.assertEqual(trace.final_violations, [])
        self.assertTrue(trace.final_ok)

    def test_final_violations_are_empty_for_a_safe_fallback(self):
        """The deterministic fallback is grounded by construction."""
        provider = self._provider(
            "P-EXCL is the best plan and it covers everything at $99 per month."
        )
        bot = CoverageAssistant(provider=provider)
        answer = bot.answer(
            "Which plan is best?",
            {
                "eligible_ids": ["P-BASE", "P-PLUS"],
                "visible_ids": ["P-BASE", "P-PLUS"],
                "selected_id": "P-PLUS",
                "selected_options": [],
            },
        )
        trace = bot.last_trace
        self.assertTrue(trace.violations, "the draft should have been flagged")
        self.assertTrue(trace.fallback_used)
        self.assertEqual(trace.final_violations, [])
        self.assertTrue(trace.final_ok)
        self.assertNotIn("$99", answer)

    def test_as_dict_exposes_the_final_validation_state(self):
        provider = self._provider("P-PLUS has a $100 deductible.")
        bot = CoverageAssistant(provider=provider)
        bot.answer(
            "What is the deductible?",
            {
                "eligible_ids": ["P-PLUS"],
                "visible_ids": ["P-PLUS"],
                "selected_id": "P-PLUS",
                "selected_options": [],
            },
        )
        payload = bot.last_trace.as_dict()
        self.assertIn("final_violations", payload)
        self.assertIn("final_ok", payload)
        self.assertTrue(payload["final_ok"])

    def test_missing_api_key_raises_clear_error(self):
        from coverage_assistant.llm import MissingCredentialError, OpenAIProvider

        with self.assertRaises(MissingCredentialError):
            OpenAIProvider(
                ProviderConfig(provider="openai", api_key=None)
            )

    def test_spend_cap_stops_further_calls(self):
        from coverage_assistant.llm import SpendCapError

        provider = self._provider("P-PLUS has a $100 deductible.")
        provider.config.max_calls = 1
        provider.complete([{"role": "user", "content": "hi"}])
        with self.assertRaises(SpendCapError):
            provider.complete([{"role": "user", "content": "hi"}])

    def test_provider_error_is_surfaced_not_swallowed(self):
        from coverage_assistant.llm import ProviderError

        class Failing(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass

            def do_POST(self):
                self.send_response(500)
                self.send_header("Content-Length", "0")
                self.end_headers()

        server = HTTPServer(("127.0.0.1", 0), Failing)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            config = ProviderConfig(
                provider="openai-compatible",
                model="mock",
                api_key="k",
                base_url=f"http://127.0.0.1:{port}/v1",
                retries=0,
            )
            provider = OpenAICompatibleProvider(config)
            with self.assertRaises(ProviderError):
                provider.complete([{"role": "user", "content": "hi"}])
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()


class ProviderSelectionTest(unittest.TestCase):
    """Live mode must pick the provider whose key is actually present."""

    def setUp(self):
        self._saved = {
            key: os.environ.pop(key, None)
            for key in (
                "OPENAI_API_KEY",
                "ANTHROPIC_API_KEY",
                "LLM_API_KEY",
                "LLM_PROVIDER",
                "LLM_BASE_URL",
            )
        }

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_anthropic_key_only_selects_anthropic(self):
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
        self.assertEqual(build_provider("live").name, "anthropic")

    def test_openai_key_only_selects_openai(self):
        os.environ["OPENAI_API_KEY"] = "sk-test"
        self.assertEqual(build_provider("live").name, "openai")

    def test_explicit_provider_overrides_detection(self):
        os.environ["OPENAI_API_KEY"] = "sk-test"
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
        os.environ["LLM_PROVIDER"] = "anthropic"
        self.assertEqual(build_provider("live").name, "anthropic")

    def test_base_url_selects_openai_compatible(self):
        os.environ["LLM_API_KEY"] = "test"
        os.environ["LLM_BASE_URL"] = "http://127.0.0.1:11434/v1"
        provider = build_provider("live")
        self.assertEqual(provider.name, "openai-compatible")
        self.assertEqual(provider.base_url, "http://127.0.0.1:11434/v1")

    def test_missing_key_raises_clear_error(self):
        with self.assertRaises(MissingCredentialError) as ctx:
            build_provider("live")
        message = str(ctx.exception).lower()
        self.assertIn("api key", message)
        self.assertIn("offline", message)
