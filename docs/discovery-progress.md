# Options discovery milestone

Updated: 2026-09-29. Repository: KodeE3/coinbase-crypto-bot. Extends draft PR #2,
`codex/options-paper-foundation`. Paper simulation only; no live-money execution.

## Verified starting state

- Main: `edb116f6a7c42fa277b06b7da632c9f09933354a`; three separate open experiment PRs.
- Draft PR #2: `3bc6b7af40fdc2e9b82f47925420b624a20ab9c7`. Options CI run
  [36082884906](https://github.com/KodeE3/coinbase-crypto-bot/actions/runs/36082884906)
  passed. Includes paper ledger, reviewed exits, Alpaca quote refresh and offline demo.
  The older publishing blocker was resolved by the September 25 publication.
- PR #1: BTC candle/backtest experiment at `55de9bf`, latest PR CI passed. Its notes
  report later validation losses and no promoted profitable strategy.
- PR #3: prediction-market research at `1114f81`, latest two PR workflows passed. Its
  notes report public-data collection with entries blocked pending contract review.
- This milestone changes only options work. Other experiment branches remain separate.
- Source files retrieved through the GitHub app at the pinned PR #2 SHA. An older local
  source import had different hashes and was not used as the baseline.
- Baseline: 32 tests passed. No Alpaca credentials present in this environment.

## Completed bounded milestone

`python -m options_paper.discovery --symbol SPY --output paper_data/entries/spy-001.json`
discovers a bounded call universe and writes an immutable entry snapshot. It joins completed
stock bars, paper contract metadata/OI, completed-session option volume and OPRA quotes/greeks.
The existing file-review CLI can consume the output without changing its strategy or risk limits.

Checks cover standard contract identity, bounded complete pagination, unique contracts,
quote freshness at collection completion, numeric/schema validation and dated liquidity data.
Source/feed/filter/timestamp provenance and exclusion counts are retained. No candidates is
a saved rejection observation. Failed collection never publishes a partial snapshot; existing
files are never replaced. Requests are GET-only to allowlisted data paths and the paper catalog.
No broker orders, account reads, subscriptions, or simulated trades occur during discovery.

## Verification

- 51 tests passed on bundled Python 3.12.14: 32 existing and 19 new discovery tests.
- Mocked discovery -> JSON -> paper buy, fees and duplicates; metadata/volume/quote failures;
  pagination/cycles/bounds; batches over 100 contracts; oldest-quote times, collection aging
  and session rollover; stale confirmation and unchanged $200 limit; fixed GET endpoints;
  error redaction; CLI no-account/no-prompt behavior; atomic output/overwrite refusal.
- `python -m options_paper.demo` completes the isolated fictional buy/restart/mark/sell
  cycle. Its $78.70 fictional P/L verifies accounting only, not profitability.
- `git diff --check` passed. Existing CI runs the full suite on Python 3.10 and 3.12.
- Windows sandbox Python 3.12 `mkdir(0o700)` creates inaccessible temporary directories.
  Local tests used a workspace-only `sitecustomize.py` to use inherited ACLs for those
  temporary directories. It is excluded from repository/deliverables; Linux CI must
  verify the unmodified code with normal temporary-directory behavior.
- Check final published commit CI separately; baseline CI is not evidence for new code.

## Remaining risks and next steps

1. Authenticated paper-catalog/OPRA access is unverified. Configure paper credentials through
   authorized environment secrets, run a market-hours collection and inspect redacted
   feed/timestamp/diagnostic evidence. Do not purchase access or downgrade feeds.
2. Volume is from the latest completed session, OI has reporting-date granularity and greeks
   have no independent timestamp. These constrain contemporaneous liquidity/greek claims.
3. Universe: 21–45 DTE, strikes within 80–120% of the last stock close. Default stock feed
   is IEX; latest completed bars tolerate up to seven calendar days. No exchange-calendar
   validation or arbitrary adjusted-deliverable support.
4. Entry remains a supplied-ask simulation with a 15-minute freshness bound; prices are
   not refreshed during entry confirmation. Snapshot files are provenance records, not
   cryptographically authenticated provider evidence. Fill quality is not modeled.
5. Next bounded research milestone: forward observations under frozen rules and fee/slippage-aware
   evaluation with an untouched chronological holdout. Resolve authenticated access first.
   No profit or reliable income is demonstrated.
6. Historical options replay, expiry settlement, paper broker integration and persistent
   monitoring remain separate unfinished milestones. Live-money execution is not authorized.
