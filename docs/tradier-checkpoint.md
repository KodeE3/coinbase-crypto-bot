# Tradier checkpoint — 2026-09-30

User selected Tradier with credentials stored as environment secrets after requesting an
alternative to Alpaca. This checkpoint extends PR #2 at `1a224ed` without live execution.

## Implemented

- New `TradierData` adapter: fixed HTTPS host, four allowlisted market-data paths, GET only,
  environment token, timeouts, bounded responses, redirect blocking and redacted failures.
- `discovery --provider tradier`: completed underlying history, expiration and standard-call
  discovery, bid/ask/Greek/liquidity validation, bounded universe, immutable entry snapshots.
- `cli --provider tradier --refresh-quotes [--review-exits]`: the existing mark/exit workflow
  now works with Tradier, including quote re-fetch and reapproval after a changed bid.
- Account confirmation, fee, freshness, exposure, duplicate and loss controls retained.
- Provider-specific provenance makes intraday volume, undated OI, Greek cadence/timezone
  ambiguity, and historical adjustment limitations explicit. No provider fallback.

## Validation and evidence

- 69 local tests passed on Python 3.12.14: 51 existing + 18 Tradier tests.
- Tests cover discovery -> saved JSON -> paper purchase, full quote-refresh exit review,
  missing credentials/Greeks/liquidity, numeric identity checks, timestamps, duplicates,
  collection bounds, HTTP failures, redaction, endpoint allowlist and no fallback.
- Initial added test failed because a NUL cannot be inserted into an OS environment
  variable. Fixed the test to mock the environment read directly; application behavior
  remains validated without writing that malformed value to the OS environment.
- Same workspace-only Windows temporary-directory ACL shim as the prior milestone;
  it is excluded from source and deliverables. Verify the published revision with Linux CI.
- Token presence check returned false. No authenticated Tradier request has been made.
- Robinhood exploration retrieved history and 587 option catalog rows, but option-quote
  requests returned 403. No working Robinhood price feed was claimed. Its prototype and
  incomplete capture remain outside the repository under work/; they are not shipped.
- Tradier was selected by the user. Its sandbox lacks Greeks and has delayed data; only
  production market-data access is implemented. No account, order or exercise API exists.

## Resume from here

1. Ensure this checkpoint is published on draft PR #2 and check its exact-commit CI.
2. Configure `TRADIER_ACCESS_TOKEN` through runtime/Codespaces secrets using a production
   data token; restart the runtime. Do not request or print credentials in chat.
3. Run during regular market hours with a new output path:
   `python -m options_paper.discovery --provider tradier --symbol SPY --output paper_data/entries/spy-tradier-001.json`.
4. Inspect redacted feed, bid/ask timestamps, Greek-time basis, OI limitation, diagnostics
   and preview. A complete rejection observation is a valid result; do not loosen limits
   or relabel stale/undated inputs just to obtain a candidate.
5. Continue frozen-rule forward paper research. Use a separate Tradier paper account and
   explicit `--provider tradier` for each quote refresh. No persistent monitoring is running.

Read the Tradier section of `options_paper/README.md` before connecting. Income/strategy
profitability, fill realism, historical replay and expiry settlement remain unvalidated or
unfinished. This is a resumable paper-research checkpoint, not a completed trading product.
