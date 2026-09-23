import copy
import json
import tempfile
import unittest
from pathlib import Path

from options_paper.engine import propose, record_approval


SAMPLE = json.loads((Path(__file__).resolve().parents[1] / "options_paper" / "sample_snapshot.json").read_text())


class PaperTests(unittest.TestCase):
    def test_demo_and_explicit_confirmation(self):
        result = propose(SAMPLE, demo=True)
        self.assertEqual(result["estimated_entry_cost"], "150.0")
        self.assertEqual(result["estimated_immediate_liquidation_value"], "140.0")
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "trades.jsonl"
            with self.assertRaises(ValueError):
                record_approval(result, journal, "wrong contract")
            self.assertFalse(journal.exists())
            record_approval(result, journal, result["contract"])
            with self.assertRaises(ValueError):
                record_approval(result, journal, result["contract"])
            self.assertEqual(len(journal.read_text().splitlines()), 1)

    def test_reject_illiquid_or_unaffordable(self):
        data = copy.deepcopy(SAMPLE)
        data["options"][0]["ask"] = 3.0
        self.assertIn("rejected", propose(data, demo=True))
        data["options"][0]["ask"] = 1.5
        data["options"][0]["volume"] = 0
        self.assertIn("rejected", propose(data, demo=True))

    def test_reject_stale_live_snapshot(self):
        self.assertIn("rejected", propose(SAMPLE))


if __name__ == "__main__":
    unittest.main()
