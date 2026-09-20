import argparse, csv, json, sys
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import asdict, replace
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from bot.engine import Config, Engine, make_config, PRESETS
from bot.market import Candle, validate
parser=argparse.ArgumentParser(description='Fixed research comparison; excludes data on/after 2026-02-20')
parser.add_argument('--csv',required=True)
parser.add_argument('--out',default='research-results')
args=parser.parse_args()
OUT=Path(args.out)
OUT.mkdir(exist_ok=True)
with Path(args.csv).open(encoding='utf-8',newline='') as f:
    candles=[Candle(int(r['time']),*(float(r[k]) for k in ['low','high','open','close','volume'])) for r in csv.DictReader(f)]
def ts(s):return int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp())
def iso(t):return datetime.fromtimestamp(t,timezone.utc).isoformat()
# Fixed, small hypothesis set. Never consult the previously observed holdout.
configs={name:make_config(name) for name in PRESETS}
periods=[('development','2024-08-27','2025-08-20'),
 ('validation_before_gap','2025-08-20','2025-10-25T16:00:00'),
 ('validation_after_gap','2025-11-04','2026-02-20')]
def run(cfg,a,b):
 start,end=ts(a),ts(b)
 warmup=[c for c in candles if start-cfg.history_size*3600<=c.time<start]
 bars=[c for c in candles if start<=c.time<end]
 assert len(warmup)==cfg.history_size
 validate(warmup+bars)
 assert bars[-1].time==end-3600
 e=Engine(cfg);e.s.closes=[c.close for c in warmup];e.s.last=start-3600
 events=[];halt=None
 for c in bars:
  events+=e.step(c)
  if e.s.halted and halt is None:halt=c.time
 s=e.report(events)
 s['net_liquidation_return_pct']=( (e.s.cash+e.s.qty*bars[-1].close*(1-cfg.slippage)*(1-cfg.fee))/cfg.initial_cash-1)*100
 s['halted_at']=iso(halt) if halt else None
 return dict(summary=s,trades=events,config=asdict(cfg),start=a,end=b)
runs={}
for name,cfg in configs.items():
 for period,a,b in periods:
  r=run(cfg,a,b);runs[name+'/'+period]=r
  print(name,period,json.dumps(r['summary']),flush=True)
(OUT/'experiments.json').write_text(json.dumps(runs,indent=2),encoding='utf-8')
cost_runs={}
for name,cfg in configs.items():
 for cost,fee,slip in [('lower',.002,.0005),('stress',.01,.002)]:
  for period,a,b in periods:
   cost_runs[name+'/'+cost+'/'+period]=run(replace(cfg,fee=fee,slippage=slip),a,b)
(OUT/'cost-sensitivity.json').write_text(json.dumps(cost_runs,indent=2),encoding='utf-8')

