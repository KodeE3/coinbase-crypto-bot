import pathlib
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]

class DeploymentSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql=(ROOT/'supabase_schema.sql').read_text()
        cls.docs=(ROOT/'DEPLOYMENT.md').read_text()
    def test_tables_private_schema(self):
        self.assertIn('CREATE SCHEMA IF NOT EXISTS paper_gate',self.sql)
        self.assertNotIn('CREATE TABLE public.',self.sql)
    def test_rls_all_tables(self):
        for table in ('proposals','paper_fills','coinbase_fills','events'):
            self.assertIn(f'ALTER TABLE paper_gate.{table} ENABLE ROW LEVEL SECURITY',self.sql)
    def test_no_client_grants(self):
        self.assertIn('REVOKE ALL ON ALL TABLES',self.sql)
        self.assertNotIn('GRANT ALL TO anon',self.sql)
    def test_unique_fill_identity(self):
        self.assertIn('PRIMARY KEY(source_portfolio,product_id,trade_id)',self.sql)
    def test_one_open_position(self):
        self.assertIn('WHERE status=\'Open\'',self.sql)
    def test_no_sqlite_vercel_deploy_claim(self):
        self.assertIn('Do not deploy `server.py` on Vercel with local SQLite',self.docs)
