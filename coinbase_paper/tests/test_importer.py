import tempfile,unittest
from importer import FillStager,normalize,ImportErrorValue

BASE={'product_id':'BTC-USD','trade_id':'123','order_id':'o1','side':'BUY','trade_time':'2026-10-26T12:00:00Z','price':'100','size':'20','size_in_quote':True,'commission':'0.18','commission_currency':'USD'}
class TestImport(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.s=FillStager(self.tmp.name+'/fills.db')
 def test_quote_size(self):self.assertEqual(normalize(BASE)['base_quantity'],'0.2')
 def test_base_size(self):
  self.assertEqual(normalize({**BASE,'size_in_quote':False})['base_quantity'],'20')
 def test_idempotency(self):
  self.assertEqual(self.s.import_batch([BASE],complete=True)['inserted'],1)
  r=self.s.import_batch([BASE],complete=True)
  self.assertEqual((r['inserted'],r['duplicates'],len(self.s.export_pending())),(0,1,1))
 def test_conflict(self):
  self.s.import_batch([BASE]);r=self.s.import_batch([{**BASE,'price':'101'}]);self.assertEqual(r['conflicts'],1)
  self.assertEqual(self.s.export_pending()[0]['price'],'100')
 def test_missing_id_quarantine(self):
  r=self.s.import_batch([{**BASE,'trade_id':None}]);self.assertEqual(r['quarantined'],1)
 def test_fee_currency(self):
  self.s.import_batch([{**BASE,'commission_currency':'BTC'}]);self.assertEqual(self.s.export_pending()[0]['fee_currency'],'BTC')
 def test_empty_not_complete_by_default(self):
  self.assertFalse(self.s.import_batch([])['complete'])
 def test_same_trade_different_portfolio(self):
  self.s.import_batch([BASE],portfolio='a');self.s.import_batch([BASE],portfolio='b')
  self.assertEqual(len(self.s.export_pending()),2)
 def test_invalid_time(self):
  with self.assertRaises(ImportErrorValue):normalize({**BASE,'trade_time':'2026-10-26T12:00:00'})
if __name__=='__main__':unittest.main()
