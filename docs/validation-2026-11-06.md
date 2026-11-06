# Spot scanner validation — November 6, 2026

This checkpoint adds the opt-in daily-breakout paper scanner to the combined
automation build at `66a47a05d9c9ed168064dd3b7f66050772fd3cab` (draft PR #4).
See [the scanner specification and commands](spot-scanner.md).

## Implemented

- BTC/ETH/SOL completed-daily signal discovery with one unresolved proposal,
  fee-inclusive risk/cash sizing, source evidence and explicit Pending approval.
- Persistent per-asset cooldowns and proposal identities across worker restarts.
- Protective exits before entry checks; a blocked/broken proposal no longer aborts
  the remaining checks. Expiration affects only unfilled proposals.
- Offline `inspect` command for reviewing recorded evidence and event history.
- Finite offline scanner-to-approved-entry-to-exit demo in a temporary account.

## Local verification

Python 3.12, Linux:

- Root suite: **166 passed** (`python -m unittest discover -s tests -q`).
- Coinbase suite: **56 passed**, run inside `coinbase_paper` with
  `python -W ignore::ResourceWarning -m unittest discover -s tests -q`.
- Total: **222 passed**, including 30 new checks relative to the prior checkpoint.
- New scanner demo and the existing options/prediction demos all passed.
- `git diff --check` passed; worker CLI exposes the opt-in `--scan-spot` flag.

Regression cases include completed-bar timing, missing/duplicate/future data,
stale/wide/nonfinite quotes, fees at multiple price scales, remaining cash and loss
budgets, restart and concurrent duplicate attempts, transactional evidence rollback,
STOP changes during requests, explicit-approval enforcement, expiry and next-day
identity, failed-breakout rejection, error redaction and exit-before-entry ordering.

The Coinbase suite initially failed when invoked from the repository root because
the legacy package tests use local imports. Running from its documented working
directory passed; no tests were skipped to obtain the counts above.

## Public-data observation

One credential-free scan ran from **2026-11-06 15:26:56 to 15:27:06 UTC**
(10:26:56–10:27:06 AM America/New_York) against the public Coinbase Exchange
candles endpoint. All three assets supplied a validated contiguous 21-day completed
window. BTC-USD, ETH-USD and SOL-USD each returned `no_breakout` under the frozen
rule. No ticker was requested because no asset reached the quote stage. No
proposal, simulated fill or live order was created. The temporary fictional account
remained at $100 and was deleted after the check.

This verifies that the candles read and signal path worked once; it does not verify
authenticated Coinbase account access, a current qualifying quote, uptime or edge.
The API schema and timing assumptions were checked against the primary references
linked in the scanner runbook. Repeated historical polling is bounded by persisted
cooldowns; the new scanner remains disabled unless requested with its flag.

## Runtime boundaries and next evidence

No live-order capability, approval-policy relaxation, paid hosting, new scheduled
task or persistent background process was added. Existing FX and options runtime
dependencies from the October checkpoint remain. MT4 was not compiled or run in
this work. No profitability backtest or forward-performance result is claimed.

The next evidence milestone is a durable paper observation run with operator
approvals and timestamped decisions, followed by the chronological evaluation
described in the scanner specification. The GitHub workflow now includes this
branch, both Python versions (3.10/3.12), both suites and the new offline demo.
Remote CI results must be read for the pushed commit; local success is separate.
