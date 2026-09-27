# Prediction bot progress

User request: build a prediction-market bot and add necessary GitHub resources.

Implemented independently on `codex/prediction-paper-bot` from `main`. Existing
options PR #2 is untouched. No additional repos are needed for this standard-library
implementation. No real orders, brokerage credentials, or account mutations exist.

Delivered: public discovery, conservative experimental BTC terminal-threshold model,
per-contract terms review, transaction-safe simulated accounting, restart deduplication,
fee/slippage modeling, position/daily budgets, stop file, exchange-result settlement,
recorded observations, chronological holdout replay, reports, offline demo, and CI.

Validated locally and in Codespaces: 27 tests covering both trade sides, win/loss settlement, persistence,
duplicate protection, rules drift, malformed/stale data, missing candles, no future
candle leakage, budget limits, transactional rollback, fee rounding, chronology,
pagination failures, HTTP errors, response bounds, no redirects, and GET-only calls.

Open limitations:
- Public Kalshi and Coinbase connectivity verified in Codespaces on 2026-09-27;
  the original chat runtime remains restricted.
- Default live-contract approvals are intentionally empty. No current contract's
  full settlement basis has been verified. Default live runs only collect observations.
- Coinbase prices are an imperfect proxy for the official settlement benchmark.
- Model is uncalibrated; synthetic demo returns are not historical performance.
- Replay requires recorded observations and outcomes; no historic fill reconstruction.
- No hosted service, real execution, Robinhood connection, or autonomous rule approval.

Next bounded milestone: identify
a suitable BTC terminal-threshold contract and its exact settlement benchmark,
collect forward observations and official outcomes, then compare probability accuracy
and fee-adjusted performance on untouched data. Keep all execution simulated.


## Real-data verification — 2026-09-27

Opened the existing `organic system` Codespace after user sign-in and explicit
workspace-trust approval. Created an isolated detached worktree at
`/workspaces/prediction-data-check`, preserving the options checkout and its changes.

Found stale Coinbase default-endpoint caching (Age 141, 350 candles). Fixed the
adapter to request an explicit 240-minute completed window, retaining the cache
freshness guard. Added request-window and stale-cache regressions; 27 tests pass.

The fixed bot completed a public-data collection cycle: 318 market observations,
240 candles per observation, 5,626,757 bytes saved to `data/events.jsonl`. Actual
candle chronology/volatility/freshness validation passed. All 318 decisions were
`unreviewed_rules`. Paper bankroll stayed $100; zero paper or real trades occurred.
No continuous process or schedule was started. Existing provider credentials were
not needed or read. No settlement-rule approvals were added.
