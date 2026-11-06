# Coinbase spot research scanner

The worker can discover a new paper trade proposal using public Coinbase Exchange
data. It scans BTC-USD, ETH-USD and SOL-USD in that fixed order and stops at the first
candidate that can be queued. This is an experimental daily-breakout rule, not a
ranking model, forecast, proven edge or live trading integration.

## Run and review

From the repository root with Python 3.10+:

```bash
python -m trading_ops.demo
python -m trading_ops.worker --state-dir paper_data/operations --scan-spot
python coinbase_paper/cli.py --db paper_data/operations/coinbase.sqlite status
```

The demo is entirely fictional, offline and disposable. The second command uses
public market data and a persistent local paper account; it runs one cycle and exits.
No credentials or exchange account are used by the scanner. Without `--scan-spot`,
the scanner is disabled and existing worker behavior is preserved.

Copy an actual proposal ID from the scan report or `status`, then inspect it:

```text
python coinbase_paper/cli.py --db paper_data/operations/coinbase.sqlite inspect PROPOSAL_ID
```

This shows the exact proposal, source candles, quote timestamp, cost model, risk
calculation and event history. It does not change approval. To explicitly approve
or reject that **paper** proposal, use one of these commands with its actual ID:

```text
python coinbase_paper/cli.py --db paper_data/operations/coinbase.sqlite decide PROPOSAL_ID approve
python coinbase_paper/cli.py --db paper_data/operations/coinbase.sqlite decide PROPOSAL_ID reject
```

Only run the decision you intend. A later worker cycle checks the approval, expiry,
new quote and current account constraints before a simulated entry. Notion status
changes never authorize entry. Adding `--cycles 0 --interval 60` keeps the worker
running on a suitable durable host; this change does not start such a service.

## Frozen research specification: daily-breakout-v1

| Item | Rule |
|---|---|
| Universe | Long-only BTC-USD, ETH-USD, SOL-USD; separate from options and FX budgets |
| Hypothesis | A completed daily close above the preceding 20 daily highs may continue upward enough to cover costs; unvalidated |
| Inputs | 21 contiguous completed UTC daily OHLCV bars, with no invented missing bars |
| Signal | Latest completed close strictly above the maximum high of the preceding 20 bars |
| Proposal quote | Timestamp within 60 seconds, positive uncrossed bid/ask, spread at most 0.5% of ask; bid still above breakout; ask at most 1% above signal close |
| Entry | Limit-style simulated buy at or below proposed ask after explicit approval; observed entry price must remain strictly above recorded breakout floor |
| Stop | Lowest low of the last five completed daily bars, including the signal bar |
| Target | Price yielding at least 2.5 times the modeled stop loss after entry/exit fees and slippage |
| Costs | Existing persisted model: 0.9% fee and 0.1% slippage per side; illustrative, not verified account pricing |
| Size | Round down to 0.00000001 units; fit available fictional cash, $100 entry-cost ceiling, $1 per-trade planned loss and remaining daily budgets |
| Daily limits | Both $3 cumulative planned entry risk and $3 gross realized losses plus new planned risk, resetting at UTC midnight |
| Proposal expiry | Earlier of four hours from detection or next UTC daily boundary |
| Position exit | Existing sampled stop/target handling, adverse gaps and net cash ledger; no maximum holding time or time-based exit implemented |
| Queue | At most one unresolved Pending/Approved proposal or Open position for this scanner; fixed asset priority |
| Repeat signals | One proposal per strategy, pair and signal day, including rejected, expired or closed proposals |

The candidate calculation reserves round-trip modeled costs. If `E` is the entry,
`S` the stop, `f` the fee and `s` slippage, unit planned loss is
`E*(1+s)*(1+f) - S*(1-s)*(1-f)`.
Quantity is the lesser of remaining risk divided by unit loss and available cash
divided by fee-inclusive entry cost, rounded down. The target is solved from that
net loss, not from a gross chart-distance ratio. Actual gaps can exceed planned loss.
Simulation precision is not an exchange lot-size/minimum-order guarantee.

## Reliability and evidence

- Incomplete current-day candles are excluded. Duplicate, missing, future, unaligned,
  malformed and nonfinite observations fail closed. Responses may be unsorted or
  contain older bars; the selected completed window must still be contiguous.
- A no-breakout result is cached until the next UTC day. Other attempts have a
  persisted one-hour cooldown, including provider failures, to avoid candle polling
  every worker minute. A failed asset does not prevent checking the next asset.
- Queue and risk capacity are rechecked inside the proposal transaction. The
  proposal and full signal evidence are written together. A crash before the scan
  log is saved cannot recreate the same proposal ID.
- `STOP` blocks discovery and new entries, including when created during data
  requests. It does not block existing protective paper exits. The worker checks
  open positions before entries and isolates errors by proposal.
- `spot_scan_runs` stores outcomes and redacted error types. Proposal evidence is
  retained in the existing `PROPOSE` event and available with `inspect`, even after
  a later heartbeat overwrites the latest status report. No automated retention
  policy or external alert delivery is added.

Coinbase describes the ticker as a last-trade/best-bid/ask snapshot. Its timestamp
is not independent proof of bid/ask freshness. Historical data may omit intervals;
this scanner rejects gaps instead of filling them. REST polling and sampled exits
do not model continuous liquidity, latency, execution priority or intracycle prices.

## Evaluation still required

No backtest, win-rate estimate or profitability result is produced by this change.
The parameters above are a frozen research hypothesis, not selected on the smoke
scan. Freeze the implementation before collecting chronological evaluation data.
Compare net account return with cash and a cost-adjusted buy-and-hold benchmark
over the same periods; report trade count, expectancy, drawdown, exposure and open
position marks. Record approval delay and rejected signals so selection effects
remain visible. Keep development data separate from an untouched later holdout,
and test worse fees, delayed execution and adverse gaps before considering any
separate execution review. Synthetic demo gains are not market-performance evidence.

Primary API references reviewed November 6, 2026:

- [Coinbase candles](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles)
- [Coinbase ticker](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-ticker)
