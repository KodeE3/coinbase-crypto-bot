# Breakout trade diagnosis and one-filter experiment

**Conclusion: reject the tested rising-trend filter.** Price losses and execution costs both matter, while development profit is dominated by one trade. The simple filter delayed losing entries instead of removing them and reduced development return. No strategy was promoted and no forward trading was started.

## Where the money went

Amounts below are for the saved $10,000 simulated accounts. Price-only P/L uses the original executed quantity and the modeled reference prices before slippage. It is an accounting decomposition of the same trade path, not a fresh zero-cost strategy backtest.

| Segment | Trades | Price-only P/L | Fees | Slippage | Net P/L | Small gross gains turned into losses |
|---|---:|---:|---:|---:|---:|---:|
| development | 9 | $346.85 | $105.28 | $17.55 | $224.02 | 4 |
| validation_before_gap | 3 | $-16.68 | $33.94 | $5.66 | $-56.28 | 1 |
| validation_after_gap | 3 | $-73.39 | $33.57 | $5.59 | $-112.55 | 0 |

Five of six later trades lose money before costs. Across those six trades, price-only P/L is -$90.07, fees plus slippage cost $78.76, and net loss is $168.83. Costs account for about 47% of that net loss. Every later trade exits under the channel/SMA rule, not the fixed stop. This supports failed follow-through as a problem; it does not prove a specific market regime caused the losses.

Development profit is concentrated: the November 6-24, 2024 trade made $281.18, exceeding the total $224.02 development gain. The other eight trades sum to -$57.15. Removing that winner is only a concentration diagnostic, not an alternative strategy backtest. Four development trades had small price gains wiped out by costs.

## One targeted hypothesis

Development entries with a falling 200-hour SMA over the preceding 24 hours: four trades, four losses. Hypothesis: requiring a strictly rising 200-hour SMA may reject weak breakouts. The lag was fixed at one day with no slope-threshold search. No volume, volatility or additional trend filter was added.

Implemented an opt-in research parameter, rising_trend_hours=24. It checks only completed prior closes and requires 224 hours of warmup. Stops, size/risk limits, exits and the three-loss permanent halt remain unchanged. The parameter defaults to zero and is not enabled in any CLI preset.

## Development-only result

Matched comparison: August 28, 2024 to August 20, 2025, UTC, end exclusive. The one-day shift from the earlier experiment supplies complete 224-hour warmup; the unfiltered trade list and results remain identical. The candidate was rejected here without evaluating it on later validation or the old holdout.

| Metric | Unfiltered breakout | Rising-average filter |
|---|---:|---:|
| Net return (%) | 2.24 | 1.88 |
| Maximum marked-close drawdown (%) | 1.28 | 1.38 |
| Closed trades | 9.00 | 9.00 |
| Profit factor | 3.31 | 2.43 |

Both versions halt on January 7, 2025 after nine closed trades. The four initially blocked entries return later, after the slope turns positive. They are delayed by 16, 10, 27 and 54 hours. For example, the October 28 loss grows from $2.05 to $17.38. It is incorrect to estimate improvement by merely deleting losing trades from the original log: the bot will make new decisions after an entry is blocked.

## Decision and next research boundary

Do not enable this filter in a paper preset. Retain its implementation and experiment as a reproducible rejected hypothesis. The default strategy, existing presets and all risk limits remain unchanged. The next hypothesis should address failed follow-through or excessive cost relative to expected move, with criteria specified before testing. Avoid adding a stack of filters selected from these few trades.

The permanent three-loss halt remains latched. A manual review should inspect data integrity, price/cost attribution, and recent behavior before anyone chooses a new paper session; restarting must not erase the old ledger or be counted as one uninterrupted performance record. No automatic restart policy was introduced.

## Verification and limitations

All 22 unit tests pass locally. New tests check falling/flat-average rejection, prior-close timing, unchanged exits and 224-hour warmup. Every trade attribution reconciles price P/L minus fees and slippage to logged net P/L. The repository diagnosis runner exactly reproduces all 15 trade-attribution rows.

The initial strategy and later segments have already been inspected; this is exploratory analysis, not a pristine holdout result. There are only nine development and six later trades. Hourly OHLC cannot establish exact intrabar sequence or live fills. This analysis demonstrates why this one filter was rejected, not that no profitable strategy can exist.

## Reproduce

From the repository folder:

```powershell
python research/diagnose_trades.py --runs ../strategy-improvement/experiments.json --csv ../backtest-study/btc-usd-hourly-with-gaps.csv --out diagnosis-results
python research/test_rising_filter.py --csv ../backtest-study/btc-usd-hourly-with-gaps.csv --out filter-development.json
```

Delivered files: trade-attribution.csv and trade-attribution.json (15 closed trades); filter-development.json (full settings, trades and summaries for the matched development test).
