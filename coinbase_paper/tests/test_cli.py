import io,tempfile,unittest,json
from contextlib import redirect_stdout,redirect_stderr
from datetime import datetime,timedelta,timezone
from cli import main
from gate import PaperGate
class TestCLI(unittest.TestCase):
 def test_inspect_returns_signal_evidence_without_approval_or_fill(self):
  with tempfile.TemporaryDirectory() as d:
   path=d+'/db.sqlite';g=PaperGate(path);now=datetime.now(timezone.utc)
   try:
    g.propose('review','BTC-USD',100,95,120,'.1',(now+timedelta(hours=1)).isoformat(),now,
              evidence={'entry_floor':'96','strategy':'fixture'})
    with redirect_stdout(io.StringIO()) as out:
     self.assertEqual(main(['--db',path,'inspect','review']),0)
    result=json.loads(out.getvalue())
    self.assertEqual(result['proposal']['status'],'Pending')
    self.assertEqual(result['events'][0]['detail']['evidence']['entry_floor'],'96')
    self.assertEqual(g.status()['cash_usd'],'100')
   finally:g.close()
 def test_inspect_unknown_proposal_reports_error(self):
  with tempfile.TemporaryDirectory() as d,redirect_stderr(io.StringIO()) as out:
   self.assertEqual(main(['--db',d+'/db.sqlite','inspect','missing']),1)
   self.assertIn('Unknown proposal',out.getvalue())
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
