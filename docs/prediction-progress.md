# Prediction bot progress

User request: build a prediction-market bot and add necessary GitHub resources.

Implemented independently on `codex/prediction-paper-bot` from `main`. Existing
options PR #2 is untouched. No additional repos are needed for this standard-library
implementation. No real orders, brokerage credentials, or account mutations exist.

Delivered: public discovery, conservative experimental BTC terminal-threshold model,
per-contract terms review, transaction-safe simulated accounting, restart deduplication,
fee/slippage modeling, position/daily budgets, stop file, exchange-result settlement,
recorded observations, chronological holdout replay, reports, offline demo, and CI.

Validated locally: 25 tests covering both trade sides, win/loss settlement, persistence,
duplicate protection, rules drift, malformed/stale data, missing candles, no future
candle leakage, budget limits, transactional rollback, fee rounding, chronology,
pagination failures, HTTP errors, response bounds, no redirects, and GET-only calls.

Open limitations:
- External API connectivity could not be validated in this environment.
- Default live-contract approvals are intentionally empty. No current contract's
  full settlement basis has been verified. Default live runs only collect observations.
- Coinbase prices are an imperfect proxy for the official settlement benchmark.
- Model is uncalibrated; synthetic demo returns are not historical performance.
- Replay requires recorded observations and outcomes; no historic fill reconstruction.
- No hosted service, real execution, Robinhood connection, or autonomous rule approval.

Next bounded milestone: verify public feeds in an unrestricted Codespace, identify
a suitable BTC terminal-threshold contract and its exact settlement benchmark,
collect forward observations and official outcomes, then compare probability accuracy
and fee-adjusted performance on untouched data. Keep all execution simulated.
