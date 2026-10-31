import unittest
from notion_adapter import to_notion_properties,parse_notion_fill,plan_staged_to_notion,from_staged_fill
from notion_sync import SyncConflict

F=dict(fill_key='Coinbase|default|BTC-USD|x1',product='BTC-USD',side='BUY',base_quantity='0.05',price='70000',fee='0.02',fee_currency='USD',traded_at='2026-10-26T12:00:00+00:00',order_id='o1')
class AdapterTests(unittest.TestCase):
 def test_properties(self):
  p=to_notion_properties(from_staged_fill(F));self.assertEqual(p['Mode']['select']['name'],'Live observed');self.assertFalse(p['Reconciled']['checkbox'])
 def test_roundtrip(self):
  r=from_staged_fill(F);p=to_notion_properties(r)
  page={'properties':{k:dict(v,type=next(iter(v))) for k,v in p.items()}}
  # Notion returns plain_text in rich_text, while input uses text objects.
  for v in page['properties'].values():
   for key in ('title','rich_text'):
    if key in v:
     for item in v[key]:item['plain_text']=item['text']['content']
  self.assertEqual(plan_staged_to_notion([F],[page])['unchanged'],1)
 def test_new(self):self.assertEqual(len(plan_staged_to_notion([F],[])['creates']),1)
 def test_bad_pair(self):
  with self.assertRaises(SyncConflict):to_notion_properties(dict(from_staged_fill(F),pair='DOGE-USD'))
 def test_bad_timestamp(self):
  with self.assertRaises(SyncConflict):to_notion_properties(dict(from_staged_fill(F),trade_time='2026-10-26'))
 def test_bad_fee(self):
  with self.assertRaises(SyncConflict):to_notion_properties(dict(from_staged_fill(F),fee='NaN'))
