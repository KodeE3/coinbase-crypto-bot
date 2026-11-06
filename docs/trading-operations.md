# Trading operations checkpoint — November 6, 2026

This branch combines the existing options and prediction research packages with
the Coinbase paper gate and an updated FX demo EA. It has **no Python live-order
interface**. The only broker-order call is inside the MT4 EA, which rejects live
accounts. No brokerage settings, live orders or funds are changed by this work.

## What runs automatically

| Component | Implemented behavior | Remaining runtime dependency |
|---|---|---|
| Coinbase paper | Worker checks open-position exits first, then explicitly approved entries, fresh quotes/risk and cash reconciliation. Optional BTC/ETH/SOL daily scanner queues new Pending proposals with evidence. | Durable Python host and explicit operator approval. Scanner is opt-in and its strategy is unvalidated. |
| Options | Worker refreshes existing simulated positions with Alpaca, Tradier or Webull data and reports exit suggestions. | Configured provider credentials/data entitlement. Simulated buys and sells still require the existing exact-contract confirmation. |
| Prediction markets | Existing paper runner handles reviewed market rules, pricing, risk and final-result settlement. Supervisor gives it shared stop/status handling. | Reviewed current contract rules in the configuration. Empty approval maps remain blocked. Kalshi data model; not a Robinhood order integration. |
| FX v2.2 | Nine-pair MT4 demo scanner, persistent intent/signal state, expiring calendar clearance, single-instance lock, stale-feed watchdog and heartbeat. | Compile and forward-test on a running Windows MT4 demo terminal. Not compiled in this environment. |

These are separate simulated accounts. Budgets are not pooled. This is working
software for paper research, not evidence of a profitable strategy or an active
24-hour deployment. Existing ChatGPT scheduled alerts remain separate and unchanged.

## Start and inspect the Python worker

Python 3.10+ and a persistent local disk are required. Run from the repository root:

```bash
python -m trading_ops.worker --state-dir paper_data/operations --prediction-config prediction-config.json
```

This performs one cycle and stops. With no approved proposals, options provider
or reviewed prediction contracts, it makes no market-data request. The resulting
`paper_data/operations/heartbeat.json` names every component's status, including
disabled/blocked components; `completed` means the check finished, not all strategies
are enabled. To keep the worker running, add `--cycles 0 --interval 60` on a durable
machine. No host/service has been provisioned or started by this branch.

Add `--scan-spot` to enable public-data signal discovery; see the
[scanner rules and approval workflow](spot-scanner.md). With that flag, an otherwise
empty account can make market-data requests and create Pending paper proposals.
The scanner never approves proposals. A blocked entry no longer interrupts an
open-position exit check, and stale unfilled proposals are expired automatically.

Only one worker may use a state directory. The OS lock is released on process exit.
Three consecutive degraded cycles stop the process with a nonzero exit code.
Retries back off to a maximum ten-minute interval. A status file left at `running`
or older than the expected cycle interval plus request time is an unhealthy signal;
it is not automatically delivered as a notification. Keep it on a local filesystem,
not a shared network filesystem. Protect the host and local files from untrusted users.

Create `paper_data/operations/STOP` to block new paper entries. Already-open
Coinbase paper positions can still be closed by stop/target rules; prediction final
results can still settle. Options processing only refreshes quotes. Removing STOP
allows future approved paper entries. Stopping Python stops monitoring altogether.
The Python stop file does not control MT4; use the EA's own kill switch for FX.

## Coinbase approvals and accounting

The worker's Coinbase database is `paper_data/operations/coinbase.sqlite`. Existing
trusted local commands remain in `coinbase_paper/cli.py`; point `--db` at the same
absolute database path. `decide ID approve` is the explicit paper approval. Notion
status changes do not authorize entry. An old database migrates existing paper fills
once without resetting cash. Create a backup while the writer is stopped before
upgrading a real local journal. Imported live fills remain in separate staging tables.

Both entry and exit require a quote timestamp no more than 60 seconds old. Entry
quotes must follow approval and entries also require the latest completed daily candle
from the public adapter. API `/proposals/ID/simulate` now requires `quote_utc`;
the CLI uses `--quote-at`. Missing timestamps fail closed. The new exit endpoint is
`/proposals/ID/evaluate-exit`, with `market_price` and `quote_utc`.

The local ledger starts at $100, reserves actual entry cost and fees, credits net
exit proceeds, records realized P/L, and enforces $1 planned risk, $3 daily planned
risk and a $3 gross realized-loss-plus-new-risk budget. Gap losses can exceed the
planned stop. Quote sampling cannot detect every intracycle stop/target crossing.
Targets receive no favorable gap improvement; stops use the lower observed price.
Costs remain illustrative 0.9% per side plus 0.1% slippage and are persisted per database.
`/status` and the CLI reconcile initial cash + realized P/L = cash + open cost basis.
Cost-basis equity is not market value. Duplicate concurrent exits credit cash once.

Coinbase Exchange ticker timestamps represent the latest trade, not independently
timestamped bid/ask updates. The worker applies a conservative 60-second age rule
and rejects HTTP cache ages above 15 seconds. Public REST data has no broker
execution guarantee. A connected ChatGPT account does not supply Python credentials.

## Small options simulation profile

Create a separate paper account, never overwrite a legacy tutorial account:

```bash
python -m options_paper.cli --profile small --account paper_data/options-small.sqlite3 --status
```

This uses **$200 fictional starting cash**, a maximum $20 full-premium risk budget,
one open contract, 10% capital exposure, and a $20 daily gross-loss-plus-new-exposure
budget. It reserves both the illustrative $0.65 entry fee and a possible $0.65 exit
fee. With standard 100-share contracts, a $0.19 premium fails the $20 limit; a
$0.18 premium costs $19.30 including both modeled fees. This is a sizing ceiling,
not a recommendation to buy low-priced options or evidence such a contract meets
the liquidity/strategy filters. Actual broker fees are unverified here.

Profiles persist through restarts. An existing account cannot silently change from
the tutorial profile to small. Expired unresolved positions block new entries;
physical exercise and expiration settlement remain unimplemented.

For automatic quote refresh after configuring a provider, add these worker arguments:

```text
--options-db paper_data/options-small.sqlite3 --options-provider webull
```

Supported alternatives: `tradier` and `alpaca`. Credentials stay in the host's secret
environment; never pass them as arguments or commit them. Provider access must be
verified separately. Robinhood is not a Python adapter in this repository.

## Validation and limitations

Run both suites and demos with the checked-in GitHub Actions workflow. Tests cover
cash migration, restart, duplicate concurrent exit, transaction rollback, stale/future
data, kill changes during requests, local worker exclusion, small-account loss caps,
provider input validation, and preserved approval boundaries. FX checks are source
regression checks only; they do not compile MQL4 or simulate a broker.

No real market-performance backtest or untouched profitability holdout is claimed.
No cloud database migration, Notion writing worker, brokerage execution service,
notification delivery or paid hosting is enabled. The legacy Supabase SQL remains
a proposal and does not represent the new SQLite exit ledger.

Primary implementation references:
- https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-ticker
- https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles
- https://docs.mql4.com/dateandtime/timecurrent
- https://docs.mql4.com/globals/globalvariablesetoncondition
- https://docs.mql4.com/globals/globalvariabletemp
- https://docs.mql4.com/globals/globalvariablesflush
- https://docs.mql4.com/constants/environment_state/marketinfoconstants
