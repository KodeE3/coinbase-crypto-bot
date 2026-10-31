import io,tempfile,unittest,json
from contextlib import redirect_stdout
from cli import main
class TestCLI(unittest.TestCase):
 def test_status_empty(self):
  with tempfile.TemporaryDirectory() as d:
   b=io.StringIO()
   with redirect_stdout(b):self.assertEqual(main(['--db',d+'/db.sqlite','status']),0)
   self.assertEqual(json.loads(b.getvalue())['proposals'],[])
 def test_fixture_roundtrip(self):
  with tempfile.TemporaryDirectory() as d:
   f=d+'/fixture.json'
   with open(f,'w') as out:json.dump([{'product_id':'ETH-USD','trade_id':'1','side':'BUY','trade_time':'2026-10-26T12:00:00Z','price':'2000','size':'0.01','size_in_quote':False,'commission':'0.1','commission_currency':'USD'}],out)
   with redirect_stdout(io.StringIO()) as out:self.assertEqual(main(['--db',d+'/db.sqlite','import-fixture',f]),0)
   self.assertEqual(json.loads(out.getvalue())['inserted'],1)
