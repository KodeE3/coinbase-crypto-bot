import json
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
from coinbase_paper.gate import PaperGate
from trading_ops.runtime import SingleWorker,atomic_json
from trading_ops.worker import run_cycle,spot_cycle,main
from trading_ops.spot import SpotData


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def approve(self):
        now=datetime.now(timezone.utc)
        g=PaperGate(self.root/'coinbase.sqlite')
        try:
            g.propose('p','BTC-USD',100,95,120,'.1',(now+timedelta(hours=1)).isoformat())
            g.decide('p',True)
        finally:g.close()

    def provider(self,price='100'):
        class Provider:
            def quote(self,pair):return {'bid':price,'ask':price,'at':datetime.now(timezone.utc).isoformat()}
            def completed_candle(self,pair):return datetime.now(timezone.utc).isoformat()
        return Provider()

    def test_unconfigured_cycle_is_offline_and_honest(self):
        with patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('network')):
            result=run_cycle(self.root)
        self.assertEqual(result['status'],'completed')
        self.assertEqual(result['components']['options']['status'],'disabled')
        self.assertEqual(result['components']['prediction']['status'],'disabled')
        self.assertEqual(json.loads((self.root/'heartbeat.json').read_text()),result)

    def test_approved_entry_and_exit_resume_on_next_cycle(self):
        self.approve()
        result=run_cycle(self.root,spot_provider=self.provider())
        self.assertEqual(result['components']['coinbase']['actions'][0]['status'],'Open')
        result=run_cycle(self.root,spot_provider=self.provider('120'))
        self.assertEqual(result['components']['coinbase']['account']['closed_trades'],1)
        result=run_cycle(self.root,spot_provider=self.provider('120'))
        self.assertEqual(result['components']['coinbase']['actions'],[])

    def test_stop_during_data_fetch_prevents_entry(self):
        self.approve();provider=self.provider();original=provider.quote
        def quote(pair):
            (self.root/'STOP').touch();return original(pair)
        provider.quote=quote
        result=spot_cycle(self.root/'coinbase.sqlite',self.root/'STOP',provider)
        self.assertEqual(result['account']['cash_usd'],'100')
        self.assertEqual(result['actions'][0]['status'],'blocked_by_stop_file')

    def test_stop_does_not_disable_protective_paper_exit(self):
        self.approve();run_cycle(self.root,spot_provider=self.provider())
        (self.root/'STOP').touch()
        r=run_cycle(self.root,spot_provider=self.provider('94'))
        self.assertEqual(r['components']['coinbase']['account']['closed_trades'],1)

    def test_component_failure_preserves_other_checks_and_redacts_error(self):
        self.approve();provider=self.provider()
        provider.quote=lambda pair:(_ for _ in ()).throw(ValueError('super-secret-token'))
        r=run_cycle(self.root,spot_provider=provider)
        self.assertEqual(r['status'],'degraded')
        self.assertEqual(r['components']['options']['status'],'disabled')
        self.assertNotIn('super-secret',json.dumps(r))

    def test_os_lock_blocks_second_worker_and_releases(self):
        with SingleWorker(self.root/'lock'):
            with self.assertRaises(RuntimeError):
                with SingleWorker(self.root/'lock'):pass
        with SingleWorker(self.root/'lock'):pass

    def test_atomic_status_failure_preserves_old_status(self):
        p=self.root/'status.json';atomic_json(p,{'ok':1})
        with self.assertRaises(ValueError):atomic_json(p,{'bad':float('nan')})
        self.assertEqual(json.loads(p.read_text()),{'ok':1})

    def test_empty_prediction_rules_never_fetch(self):
        config=self.root/'config.json';config.write_text('{}')
        with patch('prediction_paper.providers.PublicData._get',side_effect=AssertionError('network')):
            result=run_cycle(self.root,config)
        self.assertEqual(result['components']['prediction']['status'],'blocked')

    def test_endless_failures_stop_after_three_and_single_cycle_returns_failure(self):
        with patch('trading_ops.worker.run_cycle',return_value={'status':'degraded'}),patch('builtins.print'),patch('trading_ops.worker.time.monotonic',side_effect=[0,1000,0,1000]):
            self.assertEqual(main(['--state-dir',str(self.root),'--cycles','0']),1)
        with patch('trading_ops.worker.run_cycle',return_value={'status':'degraded'}),patch('builtins.print'):
            self.assertEqual(main(['--state-dir',str(self.root)]),1)

    def test_spot_write_or_unknown_resource_never_reaches_network(self):
        data=SpotData()
        with patch.object(data.opener,'open',side_effect=AssertionError('network')):
            for pair,resource in [('BTC-USD','orders'),('../orders','ticker'),('DOGE-USD','ticker')]:
                with self.assertRaises(RuntimeError):data._get(pair,resource)
