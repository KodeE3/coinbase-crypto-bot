"""Pure Notion payload adapter. Never executes HTTP requests or approves orders."""
from datetime import datetime
from decimal import Decimal
from notion_sync import plan_fill_sync, SyncConflict
from importer import normalize

DATABASE_PROPERTIES = ('Name','Unique Fill Key','Mode','Pair','Side','Time UTC','Quantity','Price','Fee','Fee Currency','Order ID','Trade Key','Source','Reconciled')

def _plain(prop):
    if not isinstance(prop,dict): return None
    kind=prop.get('type')
    if kind in ('title','rich_text'):
        return ''.join(item.get('plain_text',item.get('text',{}).get('content','')) for item in prop.get(kind,[]))
    if kind=='select': return (prop.get('select') or {}).get('name')
    if kind=='date': return (prop.get('date') or {}).get('start')
    if kind=='number': return prop.get('number')
    if kind=='checkbox': return prop.get('checkbox')
    return None

def parse_notion_fill(page):
    props=page.get('properties',{})
    def get(key): return _plain(props.get(key))
    return dict(unique_fill_key=get('Unique Fill Key'),pair=get('Pair'),side=get('Side'),quantity=get('Quantity'),price=get('Price'),fee=get('Fee'),fee_currency=get('Fee Currency'),trade_time=get('Time UTC'))

def from_staged_fill(record):
    return dict(unique_fill_key=record['fill_key'],pair=record['product'],side=record['side'],quantity=record['base_quantity'],price=record['price'],fee=record['fee'],fee_currency=record['fee_currency'],trade_time=record['traded_at'],order_id=record.get('order_id'))

def _rich(value):
    return {'rich_text':[{'text':{'content':str(value)[:2000]}}]}

def to_notion_properties(record):
    """Write a fill as an observed Coinbase execution, NEVER a simulated trade."""
    from notion_sync import ALLOWED, _numeric
    if record['pair'] not in ALLOWED or record['side'] not in ('BUY','SELL'): raise SyncConflict('Unsupported fill')
    for field in ('quantity','price','fee'):
        val=_numeric(record[field])
        if val < 0 or (field!='fee' and val==0): raise SyncConflict('Invalid fill value')
        if abs(val)>Decimal('1e14'): raise SyncConflict('Notion numeric precision unsafe')
    if not record.get('unique_fill_key') or not record.get('fee_currency'): raise SyncConflict('Missing identifier or currency')
    stamp=datetime.fromisoformat(record['trade_time'].replace('Z','+00:00'))
    if stamp.tzinfo is None: raise SyncConflict('Timezone required')
    key=record['unique_fill_key']
    return {'Name':{'title':[{'text':{'content':key[:2000]}}]},'Unique Fill Key':_rich(key),
      'Mode':{'select':{'name':'Live observed'}},'Pair':{'select':{'name':record['pair']}},
      'Side':{'select':{'name':record['side']}},'Time UTC':{'date':{'start':stamp.isoformat()}},
      'Quantity':{'number':float(record['quantity'])},'Price':{'number':float(record['price'])},
      'Fee':{'number':float(record['fee'])},'Fee Currency':_rich(record['fee_currency']),
      'Order ID':_rich(record.get('order_id') or ''),'Source':{'select':{'name':'Coinbase SPOT'}},
      'Reconciled':{'checkbox':False}}

def plan_staged_to_notion(staged, notion_pages):
    records=[from_staged_fill(r) for r in staged]
    return plan_fill_sync(records,[parse_notion_fill(p) for p in notion_pages])
