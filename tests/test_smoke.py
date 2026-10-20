import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "starter"))
from assistant import CoverageAssistant

class Smoke(unittest.TestCase):
    def test_returns_text(self):
        bot = CoverageAssistant()
        response = bot.answer("Tell me about the plan", {"eligible_ids":["P-BASE"], "visible_ids":["P-BASE"], "selected_id":"P-BASE", "selected_options": []})
        self.assertIsInstance(response, str)
        self.assertTrue(response)

if __name__ == '__main__':
    unittest.main()
