"""Tests for the local reviewer UI (``review_ui.py``).

The UI is the reviewer's only contact with the system, so the contract it
exposes is tested here: the page loads, the state controls are rendered, the
guardrail verdict describes the answer the customer actually received, and a
reset clears the conversation.

The UI module is imported with ``ASSISTANT_MODE=offline`` so the test needs
no credentials, no network and no model. The HTTP server is started on a
random free port and driven with the standard library.
"""
import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["ASSISTANT_MODE"] = "offline"

import review_ui  # noqa: E402


class ReviewUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), review_ui.Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _get(self, path="/"):
        with urllib.request.urlopen(self.base + path, timeout=30) as response:
            return response.status, response.read().decode()

    def _post(self, path, payload=None):
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(payload or {}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read())

    # -- page -----------------------------------------------------------

    def test_page_loads_and_lists_every_plan(self):
        status, html = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("AI Coverage Assistant", html)
        for plan_id in ("P-BASE", "P-PLUS", "P-WRAP", "P-EXCL"):
            self.assertIn(plan_id, html)
        # The mode badge and the model name must be rendered, not blank.
        self.assertIn("id='mode'", html)
        self.assertIn("id='model'", html)

    def test_page_exposes_the_state_controls(self):
        _, html = self._get("/")
        self.assertIn("id='plans'", html)
        self.assertIn("id='selected'", html)
        self.assertIn("id='opts'", html)
        self.assertIn("id='askBtn'", html)
        self.assertIn("id='q'", html)
        self.assertIn("resetChat()", html)

    def test_unknown_path_is_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/nope")
        self.assertEqual(ctx.exception.code, 404)

    # -- state endpoint -------------------------------------------------

    def test_state_endpoint_reports_the_mode(self):
        payload = self._post("/state")
        self.assertIn("mode", payload)
        self.assertTrue(payload["mode"])

    # -- ask endpoint ---------------------------------------------------

    def test_ask_returns_an_answer_and_a_guardrail_verdict(self):
        payload = self._post(
            "/ask",
            {
                "question": "What is the deductible for CoreDrive Plus?",
                "state": {
                    "eligible_ids": ["P-BASE", "P-PLUS"],
                    "visible_ids": ["P-BASE", "P-PLUS"],
                    "selected_id": "P-PLUS",
                    "selected_options": [],
                },
            },
        )
        self.assertIn("answer", payload)
        self.assertTrue(payload["answer"].strip())
        guardrail = payload["guardrail"]
        self.assertTrue(guardrail["ok"])
        self.assertEqual(guardrail["violations"], [])
        self.assertIn(guardrail["status"], ("PASS", "REPAIRED", "FALLBACK"))

    def test_ask_never_leaks_a_hidden_plan_price(self):
        """A plan that is eligible but not visible must not be described."""
        payload = self._post(
            "/ask",
            {
                "question": "What does TotalDrive Select cost?",
                "state": {
                    "eligible_ids": ["P-BASE", "P-PLUS", "P-EXCL"],
                    "visible_ids": ["P-BASE", "P-PLUS"],
                    "selected_id": "P-PLUS",
                    "selected_options": [],
                },
            },
        )
        answer = payload["answer"]
        self.assertNotIn("$189", answer)
        self.assertNotIn("189 per month", answer)

    def test_guardrail_reports_the_delivered_answer_state(self):
        """`ok` describes the delivered answer, not the rejected first draft.

        The rejected draft is still reported, but separately, so a reviewer
        can tell a repaired turn from a failed one.
        """
        payload = self._post(
            "/ask",
            {
                "question": "What is the deductible?",
                "state": {
                    "eligible_ids": ["P-BASE", "P-PLUS"],
                    "visible_ids": ["P-BASE", "P-PLUS"],
                    "selected_id": "P-PLUS",
                    "selected_options": [],
                },
            },
        )
        guardrail = payload["guardrail"]
        self.assertIn("rejected_draft_violations", guardrail)
        self.assertIn("status", guardrail)
        self.assertIn("repaired", guardrail)
        self.assertIn("fallback_used", guardrail)
        # A delivered answer that passed must not carry violations.
        if guardrail["ok"]:
            self.assertEqual(guardrail["violations"], [])

    def test_ask_reports_a_malformed_state_without_crashing(self):
        payload = self._post(
            "/ask",
            {"question": "What is covered?", "state": {"eligible_ids": "nonsense"}},
        )
        self.assertIn("answer", payload)
        self.assertTrue(payload["answer"].strip())

    # -- reset ----------------------------------------------------------

    def test_reset_clears_the_conversation(self):
        self._post(
            "/ask",
            {
                "question": "What is the deductible?",
                "state": {
                    "eligible_ids": ["P-PLUS"],
                    "visible_ids": ["P-PLUS"],
                    "selected_id": "P-PLUS",
                    "selected_options": [],
                },
            },
        )
        payload = self._post("/reset")
        self.assertTrue(payload["ok"])
        self.assertIsNone(payload.get("error"))
        # The assistant is a fresh instance, so it has no history.
        self.assertEqual(review_ui.Handler.assistant.history, [])


if __name__ == "__main__":
    unittest.main()
