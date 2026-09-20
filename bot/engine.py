"""Deterministic long-only SMA baseline with adverse execution costs."""
import math
from dataclasses import dataclass, asdict, field


@dataclass(frozen=True)
class Config:
    initial_cash: float = 10000
    fast: int = 20
    slow: int = 50
    risk: float = 0.005
    max_exposure: float = 0.20
    stop_pct: float = 0.02
    fee: float = 0.006
    slippage: float = 0.001
    daily_loss: float = 0.02
    max_drawdown: float = 0.10
    max_losses: int = 3

    def __post_init__(self):
        if not all(math.isfinite(v) for v in asdict(self).values()):
            raise ValueError('Configuration must be finite')
        if not 1 <= self.fast < self.slow or self.initial_cash <= 0 or self.max_losses < 1:
            raise ValueError('Invalid cash, SMA windows, or loss limit')
        for key in ('risk', 'max_exposure', 'stop_pct', 'daily_loss', 'max_drawdown'):
            if not 0 < getattr(self, key) < 1:
                raise ValueError(key + ' must be between zero and one')
        if not 0 <= self.fee < 0.1 or not 0 <= self.slippage < 0.1:
            raise ValueError('Invalid execution costs')


@dataclass
class State:
    cash: float
    qty: float = 0
    cost: float = 0
    stop: float = 0
    peak: float = 0
    day: int = -1
    day_equity: float = 0
    losses: int = 0
    halted: bool = False
    daily_halted: bool = False
    last: int = -1
    closes: list = field(default_factory=list)
    max_dd: float = 0


class Engine:
    def __init__(self, config, state=None):
        self.cfg = config
        self.s = state or State(config.initial_cash, peak=config.initial_cash)

    def step(self, c, kill=False):
        s, cfg = self.s, self.cfg
        if c.time <= s.last:
            return []
        if s.last >= 0 and c.time != s.last + 3600:
            raise ValueError('Cannot advance across a candle gap')
        events = []
        equity_open = s.cash + s.qty * c.open
        if s.day != c.time // 86400:
            s.day, s.day_equity, s.daily_halted = c.time // 86400, equity_open, False
        if kill:
            s.halted = True

        def sell(price, reason):
            fill = price * (1 - cfg.slippage)
            proceeds = s.qty * fill * (1 - cfg.fee)
            pnl = proceeds - s.cost
            events.append({'side': 'sell', 'price': fill, 'qty': s.qty, 'fee': s.qty * fill * cfg.fee, 'pnl': pnl, 'reason': reason})
            s.cash += proceeds
            s.qty = s.cost = s.stop = 0
            s.losses = s.losses + 1 if pnl < 0 else 0
            if s.losses >= cfg.max_losses:
                s.halted = True

        # Only previous completed closes inform this bar's opening decision.
        ready = len(s.closes) >= cfg.slow
        trend = ready and sum(s.closes[-cfg.fast:]) / cfg.fast > sum(s.closes[-cfg.slow:]) / cfg.slow
        if equity_open <= s.peak * (1 - cfg.max_drawdown):
            s.halted = True
        if equity_open <= s.day_equity * (1 - cfg.daily_loss):
            s.daily_halted = True
        exited = False
        if s.qty and (s.halted or s.daily_halted or not trend):
            sell(c.open, 'risk_halt' if s.halted or s.daily_halted else 'trend_exit')
            exited = True
        if not s.qty and trend and not exited and not s.halted and not s.daily_halted:
            fill = c.open * (1 + cfg.slippage)
            stop = fill * (1 - cfg.stop_pct)
            loss_per_unit = fill * (1 + cfg.fee) - stop * (1 - cfg.slippage) * (1 - cfg.fee)
            qty = min(s.cash * cfg.risk / loss_per_unit, s.cash * cfg.max_exposure / (fill * (1 + cfg.fee)))
            s.qty, s.stop = qty, stop
            s.cost = qty * fill * (1 + cfg.fee)
            s.cash -= s.cost
            events.append({'side': 'buy', 'price': fill, 'qty': qty, 'fee': qty * fill * cfg.fee, 'pnl': None, 'reason': 'sma_trend'})
        if s.qty and c.low <= s.stop:
            sell(min(c.open, s.stop), 'stop_loss')
        equity = s.cash + s.qty * c.close
        s.peak = max(s.peak, equity)
        s.max_dd = max(s.max_dd, 1 - equity / s.peak)
        if equity <= s.day_equity * (1 - cfg.daily_loss):
            s.daily_halted = True
        if equity <= s.peak * (1 - cfg.max_drawdown):
            s.halted = True
        s.last = c.time
        s.closes = (s.closes + [c.close])[-cfg.slow:]
        for event in events:
            event['time'] = c.time
        return events

    def report(self, events):
        s = self.s
        equity = s.cash + s.qty * (s.closes[-1] if s.closes else 0)
        pnl = [e['pnl'] for e in events if e['side'] == 'sell']
        wins = sum(p > 0 for p in pnl)
        losses = -sum(p for p in pnl if p < 0)
        return {'mode': 'paper_simulation', 'equity': equity, 'return_pct': (equity / self.cfg.initial_cash - 1) * 100,
                'max_drawdown_pct': s.max_dd * 100, 'closed_trades': len(pnl),
                'win_rate_pct': wins / len(pnl) * 100 if pnl else None,
                'profit_factor': sum(p for p in pnl if p > 0) / losses if losses else None,
                'expectancy_usd': sum(pnl) / len(pnl) if pnl else None,
                'open_btc': s.qty, 'cash': s.cash, 'halted': s.halted, 'daily_halted': s.daily_halted}
