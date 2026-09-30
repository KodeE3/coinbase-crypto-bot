# Webull quote integration checkpoint — 2026-09-30

## Implemented and verified offline

- `WebullData.option_quotes` validates standard equity/ETF contracts, then retrieves
  production option snapshots for existing symbols. It supports the paper refresh and
  reviewed-exit flow, including a fresh fetch after confirmation and reapproval if price
  or exit eligibility changes. It does not discover entries or submit broker orders.
- Fixed production host `api.webull.com`; GET only; exactly two allowlisted paths:
  `/trading/instruments/options/contracts/list` and `/market-data/options/snapshots/list`.
  The first path is static instrument data, despite its `/trading/` prefix. Account,
  order, token-creation, transfer and exercise routes are not supported.
- Standard-library v3 signing matches the official published known-answer vector.
  Secret stays local to signing. Optional access token is sent in a header. No automatic
  token creation, 2FA changes, environment switch or provider fallback.
- Maximum 100 requested contracts, batches of 20, ten metadata pages per batch,
  2 MB response cap and 10-second request timeouts. A conservative per-instance budget
  of 50 requests per endpoint per 60 seconds stops without sleeping or retrying. The
  provider quota is shared across processes/app-key users; server 429 also stops the run.
- A batch requires complete unique identities, matching OCC/catalog/snapshot identifiers
  and strike, USD, standard American equity/ETF contracts and one regular physical
  100-share deliverable. Cash, adjusted, unknown, index and expiry-day contracts reject.
  Liquidate-only contracts may be quoted; that does not authorize a new entry.
- Snapshot `quote_time` is explicitly epoch milliseconds. Every quote must be no more
  than 60 seconds old at collection completion, with no future timestamps. No fallback
  to `last_trade_time` or download time. Sub-cent prices are rejected without rounding.
- Capture writes immutable JSON without opening an account or prompting for a trade.
  Failure leaves no partial observation; existing output paths cannot be overwritten.

## Connect and run

1. Obtain approved Webull OpenAPI access and the needed OPRA non-display entitlement.
   An app/account connection or mobile-app quote subscription does not establish this.
2. Configure `WEBULL_APP_KEY` and `WEBULL_APP_SECRET` as runtime/Codespaces secrets. If
   your application's 2FA requires an access token, obtain it through Webull's authorized
   flow and configure `WEBULL_ACCESS_TOKEN` securely. Do not disable 2FA or paste secrets
   into chat. These variables are read by this adapter; `.env` is not loaded automatically.
3. Use an actual unexpired standard option symbol from your provider. Replace the example
   variable below; it is deliberately a placeholder, not a recommended contract:

```bash
OPTION_SYMBOL='REPLACE_WITH_ACTUAL_UNEXPIRED_OCC_SYMBOL'
python -m options_paper.webull --contracts "$OPTION_SYMBOL" --output paper_data/quotes/webull-001.json
```

The placeholder fails locally before a data request. With a real symbol and authorized
access, run during regular option market hours and inspect source, quote timestamp,
contract identity and limitations in the saved observation. A failure/rejection is useful
evidence; never relax validation to manufacture a usable quote.

For an existing local paper account containing standard actual-symbol positions:

```bash
python -m options_paper.cli --provider webull --refresh-quotes --account paper_data/webull-research.sqlite3
python -m options_paper.cli --provider webull --refresh-quotes --review-exits --account paper_data/webull-research.sqlite3
```

An empty account reports no positions and makes no provider request. Create reviewed paper
entries from existing Tradier/Alpaca discovery snapshots using the usual `--snapshot` flow.
Use a separately named account for experiments whose entry and exit data sources differ;
record that source combination when evaluating results. This is local simulation, not
Webull's app paper account or its sandbox order system.

## Data limitations

The official `quote_time` field is the snapshot-generation time. Separate bid/ask event
times are not provided and remain null. The response also does not identify the actual
feed entitlement/delay, so `feed: opra_entitlement_required` states a requirement, not a
verified subscription. A fresh timestamp alone is not proof of real-time market access.

Greeks and OI exist in the snapshot schema but have no independent timestamps/reporting
dates; this quote-only milestone does not consume them for entries. Underlying-history
behavior and option discovery date filters still need verification. No entry fields are
fabricated or borrowed from a different provider to claim Webull discovery support.

The 60-second limit applies at Webull collection time. The existing generic account
valuation/file-import policy remains 15 minutes; a saved mark is an estimate, not a live
execution quote. Provider-refresh reviewed exits always fetch again. Quote-capture JSON
retains source/contract provenance; the existing paper marks table retains prices and
timestamps only. Keep captures for research; a durable per-mark source audit is still needed.

## Verification and blockers

- 88 local tests pass on Linux/Python 3.12.14: 69 existing plus 19 Webull tests.
- Tests include official signature vector, request/response bounds, timestamp units,
  standard deliverables, pagination, late-batch failure, redaction, missing secrets,
  quote capture and an end-to-end paper refresh/reapproval/exit cycle with mock data.
- Offline demo passes with no input, no network, a disposable account and zero open
  positions at completion. Its prices and P/L are fictional accounting examples.
- Webull key, secret and access token are absent in this runtime. Tradier and Alpaca
  credentials are also absent. No authenticated request was attempted or claimed.
- Remote CI must be checked against the published commit; local success is separate.

## Next steps toward paper and live operation

| Gate | Current state | Required evidence |
|---|---|---|
| Provider connectivity | Blocked by missing credentials | One regular-hours observation with verified entitlement and documented timestamp meaning |
| Entry discovery | Tradier/Alpaca implemented; Webull pending | Verified US history schema and bounded Webull discovery -> immutable entry -> reviewed paper entry |
| Research audit | Captures available; ledger provenance incomplete | Persist provider/policy per mark and trade, including rejected observations and configuration version |
| Strategy validation | Not demonstrated | Frozen rules, chronological out-of-sample/forward observations, fee/slippage-inclusive results and drawdown; predefined acceptance criteria |
| Expiry and fill realism | Not implemented | Explicit expiry handling, fill assumptions and failure cases; stock bars alone are insufficient |
| Broker sandbox | Not implemented | Supported option flow, idempotency, partial fills, restart/reconciliation, cancel/replace and disconnect tests |
| Live operation | Not enabled | Passed preceding gates, explicit capital/loss limits, monitoring, kill switch, operational runbook and separate live-order authorization |

Next independent coding task: persist quote/entry provenance and evaluation records, then
add chronological research reporting. Webull's next provider extension is verified history
and discovery. Credentials are required for connectivity evidence, not for these offline
coding tasks. Passing software tests does not establish positive trading expectancy.

Official references checked 2026-09-30:

- https://developer.webull.com/apis/docs/reference/option-snapshot/
- https://developer.webull.com/apis/docs/reference/option-contract-list/
- https://developer.webull.com/apis/docs/authentication/signature/
- https://developer.webull.com/apis/docs/authentication/overview/
- https://developer.webull.com/apis/docs/market-data-api/overview/
- https://developer.webull.com/apis/docs/rate-limits/
