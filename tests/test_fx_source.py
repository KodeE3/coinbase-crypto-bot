"""Source regression guards only. These do NOT compile or execute MQL4."""
import unittest
from pathlib import Path

class FXSourceTests(unittest.TestCase):
    def setUp(self):
        self.source=(Path(__file__).parents[1]/'fx/FX_AutoTrader_v2_2.mq4').read_text()

    def test_demo_and_fail_closed_defaults(self):
        for text in ['EnableDemoAutoTrading = false','EmergencyKillSwitch = true',
                     'CalendarCheckedAndClear = false','CalendarClearUntilUTC = 0',
                     'ACCOUNT_TRADE_MODE_DEMO','if(!IsDemo())']:
            self.assertIn(text,self.source)
        self.assertEqual(self.source.count('OrderSend('),1)

    def test_persist_intent_before_submission_and_never_retry(self):
        timer=self.source.split('void OnTimer()')[1]
        self.assertLess(timer.index('GlobalVariableSet(PendingKey(),(double)bar)'),timer.index('OrderSend('))
        self.assertLess(timer.index('GlobalVariablesFlush()'),timer.index('OrderSend('))
        self.assertIn('submission unresolved; no retry',timer)
        self.assertIn('GlobalVariableGet(PendingKey())>0',self.source)

    def test_expiring_calendar_independent_clock_and_terminal_lock(self):
        for text in ['CalendarClearUntilUTC>now','CalendarClearUntilUTC-now<=86400',
                     'GetTickCount()-LastServerAdvance','ServerAdvanced',
                     'GlobalVariableTemp(WorkerLock)','GlobalVariableSetOnCondition(WorkerLock,OwnerToken,0)',
                     'SYMBOL_TRADE_TICK_SIZE','SYMBOL_TRADE_TICK_VALUE','IsTesting()?']:
            self.assertIn(text,self.source)
