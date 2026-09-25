import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def test_full_workflow_across_processes(self):
        with tempfile.TemporaryDirectory() as folder:
            account = str(Path(folder)/'demo.sqlite3')
            def run(*args, text=''):
                result = subprocess.run([sys.executable, '-m', 'options_paper.cli', '--demo', '--account', account, *args],
                                        input=text, text=True, capture_output=True, cwd=ROOT)
                self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                return result.stdout
            contract = 'DEMO-SPY-20261023-C-110'
            self.assertIn('$9,849.35', run(text=contract+'\n'))
            self.assertIn('$9,849.35', run('--status'))
            self.assertIn('$10,028.70', run('--close', contract, '--bid', '1.80', text=contract+'\n'))
            self.assertIn('$28.70', run('--status'))

    def test_bad_file_has_friendly_error(self):
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run([sys.executable, '-m', 'options_paper.cli', '--snapshot', str(Path(folder)/'missing.json'),
                                     '--account', str(Path(folder)/'account.sqlite3')], capture_output=True, text=True, cwd=ROOT)
            self.assertEqual(result.returncode, 1)
            self.assertIn('Unable to complete', result.stdout)
            self.assertNotIn('Traceback', result.stderr)
