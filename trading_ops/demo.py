"""Finite, offline scanner-to-exit demonstration using a disposable fictional account."""
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from coinbase_paper.gate import PaperGate, money
from .scanner import candle_end
from .worker import run_cycle


class FictionalData:
    def __init__(self):
        self.exit_price=None

    def daily_candles(self,pair,count=21,now=None):
        end=int(candle_end(now).timestamp())
        rows=[[end-(count-i)*86400,'99','101','100','100','10'] for i in range(count)]
        rows[-1]=[end-86400,'100','104','100','103','12']
        return rows

    def quote(self,pair):
        return {'bid':self.exit_price or '102.9','ask':self.exit_price or '103',
                'at':datetime.now(timezone.utc).isoformat()}

    def completed_candle(self,pair):
        return candle_end(datetime.now(timezone.utc)).isoformat()


def run_demo():
    with tempfile.TemporaryDirectory(prefix='spot-scanner-demo-') as directory:
        state=Path(directory);provider=FictionalData()
        report=run_cycle(state,spot_provider=provider,scan_spot=True)
        candidate=report['components']['spot_scanner']['results'][0]
        assert candidate['status']=='Pending'
        # A restart must leave the proposal unfilled until explicit approval.
        report=run_cycle(state,spot_provider=provider,scan_spot=True)
        assert report['components']['coinbase']['account']['cash_usd']=='100'
        gate=PaperGate(state/'coinbase.sqlite')
        try:
            assert gate.db.execute('SELECT count(*) FROM fills').fetchone()[0]==0
            gate.decide(candidate['id'],True)  # Fixture approval only, in the temporary DB.
        finally:
            gate.close()
        report=run_cycle(state,spot_provider=provider)
        assert report['components']['coinbase']['actions'][0]['status']=='Open'
        provider.exit_price=str(money(candidate['target'])+1)
        report=run_cycle(state,spot_provider=provider)
        assert report['components']['coinbase']['actions'][0]['status']=='Closed'
        replay=run_cycle(state,spot_provider=provider)
        account=replay['components']['coinbase']['account']
        assert account['closed_trades']==1 and account['reconciled']
        assert replay['components']['coinbase']['actions']==[]
        return {'mode':'FICTIONAL_OFFLINE_DEMO','uses_real_market_data':False,
            'approval_required':True,'duplicate_exit_prevented':True,'account':account,
            'note':'Synthetic prices test software behavior; this is not strategy performance.'}


if __name__=='__main__':
    print(json.dumps(run_demo(),indent=2,sort_keys=True))
