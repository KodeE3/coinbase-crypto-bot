# BTC prediction-market paper bot

A working Python 3.10+ research bot with a persistent simulated account, public
Kalshi market discovery, Coinbase BTC candles, an experimental probability
model, automatic paper entries for reviewed contracts, finalized settlement,
and chronological replay. It uses only Python's standard library.

**No real-money execution exists. No credentials are needed or read. This is not
a proven profitable strategy.** The offline demo is synthetic, not a backtest.
Robinhood's trading interface is not integrated.

## Start in under a minute

On GitHub select branch `codex/prediction-paper-bot`, then **Code → Codespaces →
Create codespace on this branch**. In its terminal:

```bash
python -m prediction_paper.cli demo
python -m unittest discover -s tests -p 'test_prediction*.py' -v
```

The demo buys one fictional Yes and one fictional No position, settles a win
and a loss, and prints an account report. Its $0.54 simulated gain was designed
to exercise accounting and must not be interpreted as expected income.
It uses temporary files and leaves any existing account untouched.

For a local checkout:

```bash
git clone --branch codex/prediction-paper-bot https://github.com/KodeE3/coinbase-crypto-bot.git
cd coinbase-crypto-bot
python -m prediction_paper.cli demo
```

## Collect real market data

```bash
python -m prediction_paper.cli scan --series KXBTCD
python -m prediction_paper.cli run
python -m prediction_paper.cli report
```

`scan` prints markets, full terms, and hashes. `run` performs one scan and stores
observations in `data/events.jsonl`, with decisions/accounting in
`data/paper.sqlite`. The initial simulated bankroll is $100. Default approvals
are empty, so real contracts are observed but no paper entry is made until
their terms are reviewed. An empty series returns no trades; an unavailable
endpoint produces an error and a nonzero exit code, never fake live data.

To run continuously on your own active computer or Codespace:

```bash
python -m prediction_paper.cli run --cycles 0 --interval 60
```

Stop with Ctrl+C. Creating `STOP_PREDICTION_BOT` in the working directory blocks
entries on the next cycle while allowing settlement polling. Delete that file
to resume. Three consecutive cycle failures stop the process, with bounded
exponential delay between retries. Existing trades are preserved. A failure
does not reverse paper entries already committed earlier in that cycle.
Only run one collector per tape/account pair. This command is not a hosted
service: suspended Codespaces and closed processes do not continue running.

## Review a contract before enabling simulated entries

The model supports **BTC above a fixed threshold at a specified terminal time**,
with $1 binary payout, no early close, and 5 minutes–24 hours remaining. It does
not support ranges, touches, multivariate contracts, provisional listings,
15-minute up/down contracts, sports, or arbitrary settlement averages.

Read the exchange's full contract terms and identify the benchmark, observation
window, threshold, and fees. Coinbase is a **proxy**, not Kalshi's official
settlement feed. Averaging windows and benchmark differences can invalidate
the estimated edge. If these terms do not fit the model, do not approve the
contract. Automatic rule interpretation is intentionally not implemented.

After review, add an actual scanned ticker under `approved_markets` in
`prediction-config.json`, using its exact hash and verified observation time:

```json
{
  "ACTUAL-SCANNED-TICKER": {
    "rules_sha256": "COPY_THE_64_CHARACTER_HASH_FROM_SCAN",
    "observation_time": "2026-10-01T21:00:00+00:00",
    "fee_multiplier": 1,
    "accept_btc_proxy": true
  }
}
```

This is an illustrative entry, not a verified market. Observation time must
equal the scanned close time for this version. Verify the series fee multiplier
against the current fee schedule; do not assume every series uses 1. A changed
terms hash blocks entry until re-reviewed. Approval enables simulation only.
Never add API keys to this public repository.

## Strategy, costs, and controls

- Estimate minute log-return volatility from up to 240 completed, contiguous
  Coinbase candles (minimum 60). Exclude incomplete/future candles and reject
  stale, missing, duplicate, non-finite, or flat histories.
- Use a zero-drift lognormal terminal-price distribution, shrink predictions
  toward 50%, and cap extremes. This is an uncalibrated baseline, not AI insight.
- Compare both Yes and No against executable-side prices. No ask is derived
  from `1 - Yes bid`; available No size comes from Yes bid size.
- Add $0.01 per-contract slippage, conservative rounded fees, a 5-percentage-point
  model uncertainty allowance, and require another 5-point edge by default.
- Paper fill only if displayed top size covers the full configured quantity.
  Reject missing size and spreads over $0.08. Fills remain hypothetical: the
  simulator cannot guarantee queue position, book stability, or actual liquidity.
- Fixed quantity defaults to one, with $2 per-trade and per-event limits, $10
  open-cost cap, and $5 daily gross-loss budget. Open cost also reserves that
  daily budget; winning trades cannot replenish it. Days use UTC.
- SQLite transactions atomically save cash, position, complete entry evidence,
  settings, and an audit entry. A ticker is traded at most once, across restarts.
- Hold to finalized exchange result. Repeated settlement cannot pay twice;
  conflicting outcomes raise an error. Closed/determined markets remain pending.
  Unsupported voids, fractional settlements, and exchange corrections require
  reconciliation; they are not guessed from Coinbase price.

Costs use a configurable multiplier times `0.07 × quantity × price × (1-price)`.
The implementation deliberately rounds costs/fees up to whole cents and is a
conservative approximation, not exact current exchange billing or Robinhood
commissions. No exit fees are modeled because this version holds to settlement.

Quote freshness is based on HTTP receipt time and cache-age checks, not an
exchange book sequence. A recently received quote can still be stale upstream.
The provider uses fixed HTTPS origins, GET only, no redirects, no credentials,
a 10-second request limit, bounded response size, and bounded pagination.

## Replay and evaluate

Freeze your settings before collecting the evaluation period. Replay a later
recording with an explicit holdout start:

```bash
python -m prediction_paper.cli replay data/events.jsonl \
  --config prediction-config.json --since 2026-10-01T00:00:00+00:00
```

Replay uses receipt timestamps and the same strategy/risk/account code. Only
then-available completed candles enter forecasts; settlement events arrive
later. Out-of-order tapes are rejected. Replay uses a fresh in-memory account
and never overwrites your running account. The `--since` boundary excludes
earlier entry observations. It cannot prevent you from selecting favorable
parameters after seeing results; predeclare and freeze them yourself.

Live runs record settlement events for held paper positions. For evaluating
different hypothetical entries on old tapes, you must collect the missing
official outcomes separately in the same event schema; otherwise positions
remain open. This is recorded-data replay, not a bulk historical data downloader.

Reports include cash, open cost, realized profit/loss, realized drawdown, wins,
and Brier scores versus the entry market midpoint on **traded settled contracts
only**. Lower Brier is better. Equity at cost is not mark-to-market; worst-case
equity assumes all open positions lose. Correlated threshold contracts are not
independent samples, and traded-only scores have selection bias. No significance,
confidence interval, annualized return, or profitable-strategy claim is made.

Before considering any separate live-execution project, gather enough independent
forward observations across regimes, compare against no-trade/market baselines,
stress costs and latency, and investigate drawdowns and benchmark error. This
repository cannot unlock live execution with a flag.

## Dependencies and repositories

No additional repository or third-party Python package is required. Reusing this
repository keeps your options experiment separate and avoids adding unreviewed
trading frameworks or API-key handling. GitHub Actions tests Python 3.10, 3.12,
and 3.13, plus the offline demo; it does not schedule trading.

Authoritative interface references consulted during implementation:

- [Kalshi public data guide](https://docs.kalshi.com/getting_started/quick_start_market_data)
- [Kalshi markets API](https://docs.kalshi.com/api-reference/market/get-markets)
- [Kalshi fees](https://kalshi.com/docs/kalshi-fee-schedule.pdf)
- [Coinbase candles](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles)

Build validation (2026-09-27): all 27 automated tests pass locally and in the
user's Codespace. The public feeds are now verified there: one collection cycle
saved 318 Kalshi snapshots with 240 completed Coinbase candles per snapshot
(5,626,757 bytes). The strategy's candle validation passed. No orders were placed.

Coinbase's unbounded default request returned a cached response with Age 141 and
350 candles. The adapter now requests an explicit rolling four-hour window ending
at the last completed minute; the verified response returned 240 candles with no
Age header. Cache-age and strategy freshness checks remain enabled.

The verified Codespace checkout is `/workspaces/prediction-data-check`, separate
from the existing options checkout with uncommitted work. To collect another cycle:

```bash
cd /workspaces/prediction-data-check
python -m prediction_paper.cli run --cycles 1
```

Observations remain in `data/events.jsonl` and the paper account in
`data/paper.sqlite` inside that checkout, excluded from git. Only one cycle was
run; no continuous collector or scheduled service was started. At the observed
market count, each cycle writes approximately 5.6 MB, so monitor disk usage before
long unattended runs. The original chat runtime still cannot fetch the feeds;
the verification above was performed in the authenticated Codespace.
