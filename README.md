# Coinbase BTC-USD paper bot

Python 3.11+ research baseline with no third-party dependencies. Reads public
Coinbase hourly candles, backtests a 20/50 simple moving average strategy, and
maintains a persistent simulated account. No keys or real-order endpoints.

## Start

Run from this folder:

```powershell
python -m unittest discover -s tests -v
python -m bot fetch --days 30 --out candles.csv
python -m bot backtest --csv candles.csv --out backtest.json
python -m bot paper
```

The first paper run creates paper.sqlite3 with $10,000 simulated cash and warms up
50 completed candles without historical startup trades. Run again after the next
hour closes, or use `python -m bot paper --watch` for an hourly foreground monitor.
Keep the terminal open and computer awake. Ctrl+C stops it. No service is installed.
Network/validation errors stop the process, preserving the last committed state.
Sessions over 72 hours behind require inspection and a new database.

## Rules

- BTC-USD hourly UTC, long-only, one position, no leverage.
- Prior-close fast SMA above slow SMA permits entry at the next bar open. Falling
  below or equal exits. This is an untuned research baseline, not a profitability claim.
- Assumed costs: 0.6% fee per side, 0.1% adverse slippage per fill. These are not
  a quote of your Coinbase fees. Set `--fee 0.006 --slippage 0.001` on paper/backtest.
- Position sizing targets 0.5% account risk at a 2% stop including modeled costs;
  entry spending is capped at 20% of cash. Gaps can exceed planned risk.
- Stop touches exit at the stop or a worse opening gap, with costs. Intrabar
  ordering, liquidity, latency and partial fills are not modeled.
- A 2% loss from UTC daily opening equity blocks entry for that day. A 10% drawdown
  or three consecutive losses permanently halts the session. Equity checks occur
  at bar open/close; liquidation follows at the next processed opening decision.
  Reported drawdown uses marked closes, not intrabar lows.
- Create an empty file named STOP before an update to latch the halt. Open simulated
  positions exit on the next processed candle. This is not an immediate market
  kill switch. Removing STOP does not reset a latched halt.
- To deliberately reset, retain the old database and use `--db new-paper.sqlite3`.

Paper mode is a **delayed candle simulation**: after a candle closes it records
hypothetical opening fills and stops. It is not a live quote execution simulator.
Brief outage catch-up uses historical candles. No actual orders are ever sent.

## Data and records

The [Coinbase candle API](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles)
is paginated below its 300-candle limit. The reader excludes incomplete candles,
validates OHLCV and continuity, and rejects missing data instead of filling prices.
Requests have timeouts and bounded retries.

backtest.json contains settings, metrics and every fill with fees and realized P/L.
Open positions stay marked at the last close; future exit fees are not deducted.
Profit factor is null with no losing trades; win rate is null with no closed trades.
paper.sqlite3 stores settings, state and fills atomically. Repeated runs do not
repeat trades. Changed settings require a new database; concurrent writers fail.

Before real execution, test longer history, out-of-sample data, cost sensitivity
and forward simulation. Live orders, broker reconciliation, exchange-native stops
and deployment are not implemented.

## Tests

Tests cover accounting, costs, exposure, gaps, no-lookahead, duplicate runs,
restart persistence, risk halts, pagination and invalid data. GitHub Actions is
configured for Windows/Linux and Python 3.11-3.13.

## Experimental strategy presets

The baseline remains the default. Three optional research presets are available:

| Preset | Entry | Exit / stop |
|---|---|---|
| slow_trend | Prior SMA 50 above SMA 200 | Trend reversal / 4% fixed stop |
| weekly_breakout | Prior close above the preceding 168 closes and its SMA 200 | Prior close below preceding 72 closes or SMA 200 / 4% fixed stop |
| weekly_breakout_trailing | Same breakout entry | Same signal exit / 6% trailing stop |

Breakout presets require 200 completed warmup hours. Trailing stops rise using
only the previous completed close, never the current candle's high. Wider stops
reduce position size under the same 0.5% planned risk limit. The daily loss,
drawdown, exposure and three-loss permanent halt limits are unchanged.

```powershell
python -m bot backtest --csv candles.csv --strategy weekly_breakout --out breakout.json
python -m bot paper --strategy weekly_breakout --db breakout-paper.sqlite3
```

Use a separate paper database when changing strategy. Existing baseline databases
remain compatible. No candidate is automatically promoted: the weekly breakout
earned +2.24% in development but lost in both later internal validation segments.
Higher modeled costs also erased its development gain. See
[research findings](research/findings.md) for periods and limitations.

To reproduce the fixed 36-scenario research comparison with the saved hourly data:

```powershell
python research/compare_strategies.py --csv ../backtest-study/btc-usd-hourly-with-gaps.csv --out research-results
```

This runner validates contiguous data within each chosen segment. It does not fill
gaps, skip active positions across gaps, or use observations on/after 2026-02-20.

### Trade diagnosis

[Trade-level findings](research/trade-diagnosis.md) separate price losses from
fees and slippage and document a rejected rising-SMA entry filter. The filter
reduced development return from 2.24% to 1.88% and is not enabled in any preset.
Its opt-in research configuration (`rising_trend_hours=24`) requires 224 prior
hours and changes entry eligibility only. Default behavior remains unchanged.

```powershell
python research/diagnose_trades.py --runs ../strategy-improvement/experiments.json --csv ../backtest-study/btc-usd-hourly-with-gaps.csv --out diagnosis-results
python research/test_rising_filter.py --csv ../backtest-study/btc-usd-hourly-with-gaps.csv --out filter-development.json
```
