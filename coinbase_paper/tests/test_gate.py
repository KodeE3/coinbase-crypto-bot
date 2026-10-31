import unittest, tempfile
from datetime import datetime,timezone,timedelta
from gate import PaperGate,GateError

class TestGate(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.g=PaperGate(self.tmp.name+'/db.sqlite')
  self.now=datetime(2026,10,26,16,tzinfo=timezone.utc)
  self.exp=(self.now+timedelta(hours=3)).isoformat()
 def prop(self,pid='p1'):
  return self.g.propose(pid,'BTC-USD',100,95,120,'0.1',self.exp,self.now)
 def test_pending_cannot_fill(self):
  self.prop()
  with self.assertRaises(GateError):self.g.simulate_entry('p1',100,self.now.isoformat(),self.now,quote_utc=self.now.isoformat())
 def test_approval_and_idempotency(self):
  self.prop();self.assertEqual(self.g.decide('p1',True,self.now),'Approved')
  self.assertEqual(self.g.simulate_entry('p1',100,self.now.isoformat(),self.now,quote_utc=self.now.isoformat())['status'],'Open')
  with self.assertRaises(GateError):self.g.simulate_entry('p1',100,self.now.isoformat(),self.now,quote_utc=self.now.isoformat())
 def test_rejected(self):
  self.prop();self.g.decide('p1',False,self.now)
  with self.assertRaises(GateError):self.g.simulate_entry('p1',100,self.now.isoformat(),self.now,quote_utc=self.now.isoformat())
 def test_expired(self):
  self.prop();self.assertEqual(self.g.decide('p1',True,self.now+timedelta(hours=4)),'Expired')
 def test_risk(self):
  with self.assertRaises(GateError):self.g.propose('bad','BTC-USD',100,80,150,'0.1',self.exp,self.now)
 def test_trigger(self):
  self.prop();self.g.decide('p1',True,self.now)
  with self.assertRaises(GateError):self.g.simulate_entry('p1',101,self.now.isoformat(),self.now,quote_utc=self.now.isoformat())
 def test_stale(self):
  self.prop();self.g.decide('p1',True,self.now)
  with self.assertRaises(GateError):self.g.simulate_entry('p1',100,(self.now-timedelta(days=3)).isoformat(),self.now,quote_utc=self.now.isoformat())
if __name__=='__main__':unittest.main()

class TestSafetyEdges(unittest.TestCase):
 def test_below_stop_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   g=PaperGate(d+'/db');now=datetime(2026,10,26,16,tzinfo=timezone.utc)
   g.propose('p','BTC-USD',100,95,120,'0.1',(now+timedelta(hours=3)).isoformat(),now)
   g.decide('p',True,now)
   with self.assertRaises(GateError):g.simulate_entry('p',94,now.isoformat(),now,quote_utc=now.isoformat())
 def test_reopen_same_proposal_forbidden(self):
  with tempfile.TemporaryDirectory() as d:
   g=PaperGate(d+'/db');now=datetime(2026,10,26,16,tzinfo=timezone.utc)
   g.propose('p','BTC-USD',100,95,120,'0.1',(now+timedelta(hours=3)).isoformat(),now)
   g.decide('p',True,now);g.simulate_entry('p',100,now.isoformat(),now,quote_utc=now.isoformat())
   with self.assertRaises(GateError):g.simulate_entry('p',100,now.isoformat(),now,quote_utc=now.isoformat())
