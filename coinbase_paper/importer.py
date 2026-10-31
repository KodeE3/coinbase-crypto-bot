"""Read-only Coinbase fill normalization and idempotent local staging. No API credentials."""
import json
import sqlite3
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone

SCHEMA = '''
CREATE TABLE IF NOT EXISTS imported_fills (
 fill_key TEXT PRIMARY KEY, portfolio TEXT NOT NULL, product TEXT NOT NULL,
 trade_id TEXT NOT NULL, order_id TEXT, side TEXT NOT NULL,
 traded_at TEXT NOT NULL, base_quantity TEXT NOT NULL,
 source_size TEXT NOT NULL, size_in_quote INTEGER NOT NULL,
 price TEXT NOT NULL, fee TEXT NOT NULL, fee_currency TEXT NOT NULL,
 source_json TEXT NOT NULL, imported_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS import_conflicts (
 id INTEGER PRIMARY KEY AUTOINCREMENT, fill_key TEXT, observed_at TEXT NOT NULL,
 existing_json TEXT, incoming_json TEXT, reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS import_runs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, source TEXT NOT NULL,
 scanned INTEGER NOT NULL, inserted INTEGER NOT NULL, duplicates INTEGER NOT NULL,
 conflicts INTEGER NOT NULL, quarantined INTEGER NOT NULL, complete INTEGER NOT NULL,
 note TEXT NOT NULL
);
'''
class ImportErrorValue(ValueError): pass

def positive(value, name, allow_zero=False):
    try: x=Decimal(str(value))
    except (InvalidOperation, TypeError): raise ImportErrorValue(f'invalid {name}')
    if not x.is_finite() or (x < 0 if allow_zero else x <= 0): raise ImportErrorValue(f'invalid {name}')
    return x

def normalize(fill, portfolio='default'):
    if not isinstance(fill,dict): raise ImportErrorValue('fill must be an object')
    product=fill.get('product_id'); trade_id=fill.get('trade_id')
    if not isinstance(product,str) or not product or not isinstance(trade_id,str) or not trade_id:
        raise ImportErrorValue('product_id and trade_id required')
    if fill.get('side') not in ('BUY','SELL'): raise ImportErrorValue('invalid side')
    if not isinstance(fill.get('trade_time'),str): raise ImportErrorValue('trade_time required')
    try: dt=datetime.fromisoformat(fill['trade_time'].replace('Z','+00:00'))
    except ValueError: raise ImportErrorValue('invalid trade_time')
    if dt.tzinfo is None: raise ImportErrorValue('timezone required')
    price=positive(fill.get('price'),'price'); size=positive(fill.get('size'),'size')
    quote=fill.get('size_in_quote')
    if type(quote) is not bool: raise ImportErrorValue('size_in_quote must be boolean')
    fee=positive(fill.get('commission','0'),'commission',True)
    currency=fill.get('commission_currency')
    if not isinstance(currency,str) or not currency: raise ImportErrorValue('commission_currency required')
    qty=size/price if quote else size
    key=f'Coinbase|{portfolio}|{product}|{trade_id}'
    return dict(fill_key=key,portfolio=portfolio,product=product,trade_id=trade_id,
                order_id=fill.get('order_id'),side=fill['side'],traded_at=dt.astimezone(timezone.utc).isoformat(),
                base_quantity=str(qty),source_size=str(size),size_in_quote=int(quote),
                price=str(price),fee=str(fee),fee_currency=currency)

class FillStager:
    def __init__(self, path):
        self.db=sqlite3.connect(str(path),isolation_level=None,timeout=20)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA busy_timeout=20000')
        self.db.executescript(SCHEMA)
    def import_batch(self, fills, portfolio='default', complete=False, note=''):
        """Only complete=True when upstream pagination was fully exhausted."""
        counts=dict(scanned=0,inserted=0,duplicates=0,conflicts=0,quarantined=0)
        now=datetime.now(timezone.utc).isoformat()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            for fill in fills:
                counts['scanned']+=1
                try: norm=normalize(fill,portfolio)
                except (ImportErrorValue, ValueError) as ex:
                    counts['quarantined']+=1
                    self.db.execute('INSERT INTO import_conflicts(fill_key,observed_at,incoming_json,reason) VALUES (?,?,?,?)',
                                    (None,now,json.dumps(fill,sort_keys=True,default=str),str(ex)))
                    continue
                row=self.db.execute('SELECT * FROM imported_fills WHERE fill_key=?',(norm['fill_key'],)).fetchone()
                # Compare semantic normalized fields, not raw JSON formatting or optional metadata.
                fields=('portfolio','product','trade_id','order_id','side','traded_at','base_quantity','source_size','size_in_quote','price','fee','fee_currency')
                if row:
                    if all(str(row[k])==str(norm[k]) for k in fields): counts['duplicates']+=1
                    else:
                        counts['conflicts']+=1
                        self.db.execute('INSERT INTO import_conflicts(fill_key,observed_at,existing_json,incoming_json,reason) VALUES (?,?,?,?,?)',
                                        (norm['fill_key'],now,row['source_json'],json.dumps(fill,sort_keys=True,default=str),'source data changed'))
                    continue
                columns=list(norm)+['source_json','imported_at']
                vals=list(norm.values())+[json.dumps(fill,sort_keys=True,default=str),now]
                self.db.execute(f"INSERT INTO imported_fills ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",vals)
                counts['inserted']+=1
            self.db.execute('INSERT INTO import_runs(started_at,source,scanned,inserted,duplicates,conflicts,quarantined,complete,note) VALUES (?,?,?,?,?,?,?,?,?)',
                            (now,'Coinbase SPOT',*(counts[k] for k in ('scanned','inserted','duplicates','conflicts','quarantined')),int(complete),note))
            self.db.commit()
        except Exception:
            self.db.rollback(); raise
        return {**counts,'complete':bool(complete),'note':note}
    def export_pending(self):
        """Return normalized records for an external authenticated Notion writer; no network calls."""
        return [dict(r) for r in self.db.execute('SELECT * FROM imported_fills ORDER BY traded_at,fill_key')]
