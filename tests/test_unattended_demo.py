import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from options_paper.demo import run_demo

ROOT = Path(__file__).resolve().parents[1]


class UnattendedDemoTests(unittest.TestCase):
    def test_repeatable_offline_cycle_without_input(self):
        with patch('builtins.input', side_effect=AssertionError('No prompts allowed')), \
                patch('socket.socket', side_effect=AssertionError('No network allowed')):
            first, second = run_demo(), run_demo()
        self.assertEqual(first, second)
        self.assertEqual(first['initial_cash_cents'], 1000000)
        self.assertEqual(first['cash_after_entry_cents'], 984935)
        self.assertEqual(first['final_cash_cents'], 1007870)
        self.assertEqual(first['realized_pnl_cents'], 7870)
        self.assertEqual(first['open_positions'], 0)
        self.assertFalse(first['real_orders'])
        self.assertEqual([event['kind'] for event in first['events']], ['buy', 'sell'])

    def test_command_leaves_existing_account_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            existing = Path(directory) / 'paper_data' / 'demo.sqlite3'
            existing.parent.mkdir()
            existing.write_bytes(b'existing account sentinel')
            result = subprocess.run([sys.executable, '-m', 'options_paper.demo'],
                                    cwd=directory, env=dict(os.environ, PYTHONPATH=str(ROOT)),
                                    stdin=subprocess.DEVNULL, capture_output=True,
                                    text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(json.loads(result.stdout)['final_cash_cents'], 1007870)
            self.assertEqual(existing.read_bytes(), b'existing account sentinel')
