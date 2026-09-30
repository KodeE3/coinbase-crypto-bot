# Webull integration workflow

Updated: 2026-09-30. Applies to the options paper-research branch and draft PR #2.
This adds Webull to the development workflow. A Webull runtime adapter, comparison gate
and sandbox executor are **planned, not implemented**. Current commands support only
Alpaca and Tradier; `--provider webull` is not a valid command yet.

## Current workflow and priority

Tradier remains the selected primary data provider; Alpaca remains available. Both feed
the existing strategy, risk checks and local paper account. Webull will first be an
independent read-only observation source, then an explicitly selected research provider.

1. Continue the [Tradier connectivity checkpoint](tradier-checkpoint.md#resume-from-here)
   when its production data token is available. Save rejected observations as well as
   candidates. Do not delay this work while waiting for Webull approval.
2. The next Webull coding milestone is the bounded read-only adapter described below.
   Implement and test offline fixtures while credentials or entitlements are unavailable.
3. Verify authenticated Webull data separately, then add optional comparison reports.
4. Continue frozen-rule forward observations, options replay/out-of-sample evaluation
   and expiry settlement. These research milestones still matter; adding another broker
   does not establish strategy performance.
5. Consider a separate sandbox execution milestone only after data validation. The
   existing local simulator remains the execution path until that milestone is complete.

The Coinbase and prediction-market experiment branches remain separate. This workflow
does not connect Webull data to those strategies or enable real-money orders.

## Access gate

An account/app connection is distinct from developer OpenAPI access. Webull documents
an access application and App Key/App Secret, plus an official Python SDK. US stock/ETF
historical and real-time OpenAPI data requires a subscription. Options coverage, Greek
availability, historical depth and sandbox parity must be verified against the specific
endpoints and the account's entitlements; do not assume stock access includes them.

Use runtime environment secrets named `WEBULL_APP_KEY` and `WEBULL_APP_SECRET` for the
future adapter. These are project conventions, not variables automatically consumed by
the official SDK. Check presence only; never print values or store them in snapshots,
logs, source, CLI arguments or chat. Do not purchase subscriptions as part of this work.
Configure production-data and sandbox environments explicitly using the official host
matrix; never silently switch environments after a failure. Sandbox observations must
stay labeled test data and cannot be used as live-price confirmation.

## Milestone 1: read-only data adapter

Before coding network calls, pin the official SDK version or documented endpoint schemas
and record which fields and timestamp units are actually supplied. Use only the minimum
data endpoints required for completed underlying bars, standard option identity and
bid/ask snapshots. No account or order client is needed.

Acceptance criteria:

- The adapter has fixed HTTPS hosts, a market-data endpoint allowlist, bounded requests,
  pagination and response sizes, timeouts, redirect blocking and redacted errors. If the
  SDK cannot enforce these constraints, use a reviewed restricted transport instead.
- Normalize into the existing snapshot/quote interfaces, retaining original bid/ask
  timestamps, source, environment, feed, collection time and a distinct Webull policy ID.
  Never rejuvenate a quote with its fetch time. Preserve missing Greek timestamps and OI
  reporting dates as unknown; do not invent them from another field or provider.
- Cross-check OCC identity, underlying, expiry, strike, right and standard 100-share
  multiplier. Reject malformed/nonstandard contracts, duplicates, crossed prices,
  future/stale timestamps and incomplete/exhausted collections. Recheck freshness at
  collection completion. Preserve existing strategy, fees and account risk limits.
- Discovery is enabled only if the verified endpoints supply the inputs the strategy
  requires (including delta, volume and OI). If not, ship quote-only validation support
  and document the exact missing inputs; do not fill them from unrelated observations.
- Add an explicit provider selection to discovery and quote refresh only when the
  corresponding capability is complete. No provider fallback. Existing Alpaca/Tradier
  defaults and full-symbol entry/exit confirmations continue to work.
- Fixtures/mocks cover collection -> immutable JSON -> reviewed local paper entry where
  discovery is supported, quote-refresh/reapproval, schema/identity/timestamp failures,
  401/403/429, timeouts, redaction, bounds and prevention of account/order calls.
- All existing tests and the offline demo pass. With authorized credentials, collect one
  regular-hours observation and record only redacted status, environment, feed, timestamps
  and exclusions. Offline passing tests alone do not verify authenticated connectivity.

## Milestone 2: independent quote comparison

Compare only the same verified contract and compatible production feeds. Retain both
observations; do not average prices or mix one source's bid with the other's ask. Proposed
initial research policy: both bid/ask pairs at most 60 seconds old, at most 5 seconds apart,
and midpoint difference no greater than `max($0.05, 5% of the primary midpoint)` per share.
These are starting research thresholds requiring calibration, not validated trading rules.

First save comparison reports without changing proposal selection. Then, after reviewing
observations, add an explicitly enabled paper-entry gate: identity/feed mismatch, stale or
missing data, excessive time skew or price disagreement yields a saved rejection. No
unvalidated fallback on outage. Tests must cover threshold boundaries, time skew, unknown
feeds, zero midpoint, unavailable comparison source and unchanged default behavior.

## Milestone 3: isolated sandbox execution

Confirm that Webull's sandbox supports the required options orders and status events;
the existence of a sandbox host does not prove equivalence to app paper trading. Use a
separate adapter and sandbox-only credentials, with an allowlisted sandbox host and a
hard rejection of production order hosts. Keep local simulation and sandbox ledgers distinct.

Define acceptance around idempotency, partial fills, cancel/replace, reconnects, status
reconciliation, rate limits and fees/slippage comparison. Test duplicate/out-of-order events
and timeouts without retrying into duplicate orders. Production execution requires a separate
explicitly authorized milestone; it is outside this workflow update.

## Evidence and resume

The workflow update changes documentation and coding-agent priorities only. Runtime
provider support, signal behavior and order capabilities are unchanged. No Webull connection
was tested. Resume with Milestone 1; complete offline implementation before reporting any
credential or entitlement blocker. Retain the Tradier research path throughout.

Official references checked 2026-09-30:

- [OpenAPI onboarding](https://developer.webull.com/apis/docs/getting-started/)
- [Market-data prerequisites and SDK usage](https://developer.webull.com/apis/docs/market-data-api/getting-started/)
- [Data API and environment hosts](https://developer.webull.com/apis/docs/market-data-api/data-api/)
- [Trading API overview](https://developer.webull.com/apis/docs/trade-api/overview/)
