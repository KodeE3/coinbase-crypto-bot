import argparse,csv,json
from pathlib import Path
from datetime import datetime,timezone
parser=argparse.ArgumentParser(description='Attribute saved breakout trade P/L to prices and costs')
parser.add_argument('--runs',required=True)
parser.add_argument('--csv',required=True)
parser.add_argument('--out',default='trade-diagnosis')
args=parser.parse_args()
OUT=Path(args.out)
OUT.mkdir(parents=True,exist_ok=True)
runs=json.loads(Path(args.runs).read_text(encoding='utf-8'))
with Path(args.csv).open(encoding='utf-8',newline='') as f:
 bars=list(csv.DictReader(f))
closes={int(r['time']):float(r['close']) for r in bars}
def iso(t):return datetime.fromtimestamp(t,timezone.utc).isoformat()
records=[]
for period in ['development','validation_before_gap','validation_after_gap']:
 r=runs['weekly_breakout/'+period];cfg=r['config'];entry=None
 for fill in r['trades']:
  if fill['side']=='buy':entry=fill;continue
  assert entry is not None
  t=entry['time'];q=entry['qty'];slip=cfg['slippage']
  history=[closes[x] for x in range(t-224*3600,t,3600)]
  sma=sum(history[-200:])/200
  older=sum(history[-224:-24])/200
  raw_entry=entry['price']/(1+slip);raw_exit=fill['price']/(1-slip)
  gross=q*(raw_exit-raw_entry)
  slip_cost=q*((entry['price']-raw_entry)+(raw_exit-fill['price']))
  fees=entry['fee']+fill['fee']
  assert abs(gross-slip_cost-fees-fill['pnl'])<1e-7
  records.append(dict(period=period,entry=iso(t),exit=iso(fill['time']),hours=(fill['time']-t)/3600,
   gross_price_pnl=gross,slippage_cost=slip_cost,fees=fees,net_pnl=fill['pnl'],reason=fill['reason'],
   sma200_slope_24h_pct=(sma/older-1)*100,fast_slow_spread_pct=(sum(history[-50:])/50/sma-1)*100,
   breakout_margin_pct=(history[-1]/max(history[-169:-1])-1)*100))
  entry=None
for period in ['development','validation_before_gap','validation_after_gap']:
 rows=[r for r in records if r['period']==period]
 print(period,json.dumps(dict(trades=len(rows),gross=sum(r['gross_price_pnl'] for r in rows),fees=sum(r['fees'] for r in rows),slippage=sum(r['slippage_cost'] for r in rows),net=sum(r['net_pnl'] for r in rows),cost_flipped=sum(r['gross_price_pnl']>0 and r['net_pnl']<0 for r in rows))),flush=True)
 for r in rows:print(json.dumps(r),flush=True)
(OUT/'trade-attribution.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
with (OUT/'trade-attribution.csv').open('w',newline='',encoding='utf-8') as f:
 w=csv.DictWriter(f,fieldnames=list(records[0]));w.writeheader();w.writerows(records)
