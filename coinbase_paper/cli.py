"""Local-only operator CLI. Never executes trades or makes network requests."""
import argparse,json,sys
from gate import PaperGate,GateError
from importer import FillStager

def main(argv=None):
 p=argparse.ArgumentParser(description='Offline paper-only Coinbase journal prototype')
 p.add_argument('--db',default='paper_gate.sqlite',help='local paper gate SQLite path')
 sub=p.add_subparsers(dest='cmd',required=True)
 a=sub.add_parser('propose');a.add_argument('id');a.add_argument('pair');a.add_argument('entry');a.add_argument('stop');a.add_argument('target');a.add_argument('quantity');a.add_argument('expires')
 a=sub.add_parser('decide');a.add_argument('id');a.add_argument('decision',choices=['approve','reject'])
 a=sub.add_parser('inspect');a.add_argument('id',help='review proposal and recorded signal evidence without approving')
 a=sub.add_parser('paper-entry');a.add_argument('id');a.add_argument('market_price');a.add_argument('candle_utc');a.add_argument('--quote-at',required=True)
 a=sub.add_parser('paper-exit');a.add_argument('id');a.add_argument('market_price');a.add_argument('--quote-at',required=True)
 a=sub.add_parser('import-fixture');a.add_argument('json_file');a.add_argument('--portfolio',default='default');a.add_argument('--complete',action='store_true')
 sub.add_parser('status')
 args=p.parse_args(argv)
 g=None
 try:
  if args.cmd=='import-fixture':
   with open(args.json_file,encoding='utf-8') as f: payload=json.load(f)
   if not isinstance(payload,list):raise ValueError('JSON must contain a list of fills')
   result=FillStager(args.db).import_batch(payload,args.portfolio,args.complete,'Local fixture; not a live Coinbase fetch')
  else:
   g=PaperGate(args.db)
   if args.cmd=='propose':result=g.propose(args.id,args.pair,args.entry,args.stop,args.target,args.quantity,args.expires)
   elif args.cmd=='inspect':
    row=g.db.execute('SELECT * FROM proposals WHERE id=?',(args.id,)).fetchone()
    if row is None:raise GateError('Unknown proposal')
    events=[{**dict(x),'detail':json.loads(x['detail'])} for x in g.db.execute('SELECT * FROM events WHERE proposal_id=? ORDER BY id',(args.id,))]
    result={'mode':'PAPER_ONLY','proposal':dict(row),'events':events}
   elif args.cmd=='decide':result={'status':g.decide(args.id,args.decision=='approve')}
   elif args.cmd=='paper-entry':result=g.simulate_entry(args.id,args.market_price,args.candle_utc,quote_utc=args.quote_at)
   elif args.cmd=='paper-exit':result=g.evaluate_exit(args.id,args.market_price,args.quote_at)
   else:
    result={**g.status(),'proposals':[dict(x) for x in g.db.execute('SELECT * FROM proposals ORDER BY created DESC LIMIT 100')],
            'paper_fills':[dict(x) for x in g.db.execute('SELECT * FROM fills ORDER BY at DESC LIMIT 100')]}
  print(json.dumps(result,indent=2,sort_keys=True))
 except (GateError,ValueError,OSError) as exc:
  print(json.dumps({'error':str(exc)}),file=sys.stderr);return 1
 finally:
  if g is not None:g.close()
 return 0
if __name__=='__main__':sys.exit(main())
