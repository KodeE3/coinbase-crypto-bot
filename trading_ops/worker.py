"""One supervisor for paper spot lifecycle and options/prediction research."""
import argparse
import json
import time
from datetime import datetime,timezone
from pathlib import Path
from coinbase_paper.gate import PaperGate,parse_time
from options_paper.account import Account as OptionsAccount
from options_paper.quotes import save_quotes
from options_paper.market_data import AlpacaData
from options_paper.tradier import TradierData
from options_paper.webull import WebullData
from prediction_paper.account import Account as PredictionAccount
from prediction_paper.providers import PublicData
from prediction_paper.strategy import validate_config
from prediction_paper.cli import cycle as prediction_cycle
from .runtime import SingleWorker,atomic_json
from .spot import SpotData


def stamp(): return datetime.now(timezone.utc).isoformat()


def spot_cycle(db,stop,provider):
    gate=PaperGate(db)
    try:
        actions=[]
        rows=gate.db.execute("SELECT * FROM proposals WHERE status IN ('Open','Approved') ORDER BY created").fetchall()
        for p in rows:
            if p['status']=='Approved' and Path(stop).exists():
                actions.append({'id':p['id'],'status':'blocked_by_stop_file'});continue
            if p['status']=='Approved' and parse_time(p['expires'])<=datetime.now(timezone.utc):
                actions.append({'id':p['id'],'status':'approval_expired'});continue
            if p['status']=='Open':
                quote=provider.quote(p['pair'])
                actions.append(gate.evaluate_exit(p['id'],quote['bid'],quote['at']))
            else:
                candle=provider.completed_candle(p['pair'])
                quote=provider.quote(p['pair'])
                # Recheck stop AFTER network I/O and before any simulated entry.
                if Path(stop).exists():
                    actions.append({'id':p['id'],'status':'blocked_by_stop_file'});continue
                from decimal import Decimal
                if Decimal(quote['ask'])>Decimal(p['entry']):
                    actions.append({'id':p['id'],'status':'entry_trigger_not_met'});continue
                actions.append(gate.simulate_entry(p['id'],quote['ask'],candle,quote_utc=quote['at']))
        return {'status':'ok','actions':actions,'account':gate.status()}
    finally: gate.close()


def options_cycle(db,provider_name):
    if not provider_name: return {'status':'disabled','reason':'quote provider not configured'}
    if not Path(db).is_file(): return {'status':'blocked','reason':'paper account not initialized'}
    account=OptionsAccount(db)
    try:
        state=account.status();contracts=[p['contract'] for p in state['positions']]
        if not contracts: return {'status':'ok','positions':0,'risk_profile':state['risk_profile']}
        clients={'alpaca':AlpacaData,'tradier':TradierData,'webull':WebullData}
        report=save_quotes(account,clients[provider_name]().option_quotes(contracts))
        return {'status':'ok','valuation':report,'action':'quotes and exit suggestions only; approval remains required'}
    finally: account.close()


def run_cycle(state,prediction_config=None,options_db=None,options_provider=None,spot_provider=None,prediction_provider=None):
    state=Path(state);state.mkdir(parents=True,exist_ok=True);stop=state/'STOP'
    report={'mode':'PAPER_RESEARCH_ONLY','started_at':stamp(),'new_entries_stopped':stop.exists(),'components':{}}
    atomic_json(state/'heartbeat.json',{**report,'status':'running'})
    tasks={'coinbase':lambda:spot_cycle(state/'coinbase.sqlite',stop,spot_provider or SpotData())}
    tasks['options']=lambda:options_cycle(options_db or state/'options.sqlite',options_provider)
    def prediction():
        if not prediction_config: return {'status':'disabled','reason':'config not supplied'}
        cfg=validate_config(json.loads(Path(prediction_config).read_text()))
        account=PredictionAccount(state/'prediction.sqlite',cfg['initial_cents'])
        try:
            if not cfg['approved_markets'] and not account.open_positions():
                return {'status':'blocked','reason':'no reviewed market rules; no network or paper entries'}
            decisions=prediction_cycle(prediction_provider or PublicData(),account,cfg,state/'prediction-events.jsonl',stop)
            return {'status':'ok','decisions':decisions,'account':account.report()}
        finally:account.close()
    tasks['prediction']=prediction
    for name,task in tasks.items():
        try: report['components'][name]=task()
        except Exception as exc:
            # Avoid copying provider responses/credentials into long-lived status files.
            report['components'][name]={'status':'error','error_type':type(exc).__name__}
    report['finished_at']=stamp()
    report['status']='degraded' if any(v['status']=='error' for v in report['components'].values()) else 'completed'
    report['runtime_scope']='local worker only; FX requires a separately running MT4 demo terminal'
    atomic_json(state/'heartbeat.json',report)
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state-dir',type=Path,default=Path('paper_data/operations'))
    p.add_argument('--prediction-config',type=Path)
    p.add_argument('--options-db',type=Path)
    p.add_argument('--options-provider',choices=['alpaca','tradier','webull'])
    p.add_argument('--cycles',type=int,default=1,help='zero means keep running')
    p.add_argument('--interval',type=int,default=60)
    args=p.parse_args(argv)
    if args.cycles<0 or args.interval<60:p.error('cycles >=0 and interval >=60 required')
    count=failures=0
    try:
        with SingleWorker(args.state_dir/'worker.lock'):
            while args.cycles==0 or count<args.cycles:
                report=run_cycle(args.state_dir,args.prediction_config,args.options_db,args.options_provider)
                print(json.dumps(report,sort_keys=True),flush=True)
                count+=1
                failures=failures+1 if report['status']=='degraded' else 0
                if failures>=3:return 1
                if args.cycles and count>=args.cycles:break
                deadline=time.monotonic()+min(args.interval*2**failures,600)
                while time.monotonic()<deadline:time.sleep(min(1,max(0,deadline-time.monotonic())))
        return 1 if failures else 0
    except KeyboardInterrupt:return 130
    except (OSError,RuntimeError,ValueError) as exc:
        print(json.dumps({'mode':'PAPER_RESEARCH_ONLY','status':'failed','error_type':type(exc).__name__}))
        return 1


if __name__=='__main__':raise SystemExit(main())
