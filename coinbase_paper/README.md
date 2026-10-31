# Coinbase Paper Approval Gate — v0.7

The current version adds a reconciled cash ledger, paper stop/target exits, restart-safe
migration, concurrent exit deduplication and fresh quote requirements. It is included
in the cross-project worker. See [the current operations guide](../docs/trading-operations.md).

`simulate_entry` and the HTTP simulate endpoint now require `quote_utc`; the CLI uses
`--quote-at`. Quote age must be at most 60 seconds and its timestamp must follow approval.
`evaluate_exit` handles observed stop/target crossings only. No live order endpoints exist.

The following sections are historical v0.2–v0.6 notes; where they describe missing cash
ledgers/exits, those gaps are resolved in v0.7. Cloud deployment, Notion writing and live
account synchronization remain unimplemented in this Python runtime.

# Coinbase Paper Approval Gate — v0.2

**Local prototype, paper-only. No exchange order, withdrawal, transfer, or conversion capability.**

## Working now

- `gate.py`: SQLite-backed proposal state machine: Pending → Approved/Rejected/Expired → simulated Open, with explicit decision and entry checks. Long-only BTC/ETH/SOL spot; fixed fee/slippage assumptions, structural stop, $1 planned risk per trade, $3 daily planned-risk cap, $100 maximum modeled buying power, and 2:1 minimum modeled net reward/risk. Prevents duplicate proposal IDs, duplicate fills, and simultaneous open paper positions.
- `importer.py`: offline Coinbase-fill staging. Stable `Coinbase|portfolio|product|trade_id` keys; idempotent reimport; conflicting records quarantined for review; quote-sized fill conversion to base units; original fee currency preserved; paginated-history completeness must be asserted by the caller, never assumed. Maintains import-run audit rows.
- `cli.py`: offline local operator commands for proposals, approvals, paper entry, status and JSON fill fixtures. **Do not expose this CLI to untrusted users.**
- `tests/`: 20 passing local automated tests at build time.

## Quick start

Requires Python 3.10+; no third-party dependencies.

```bash
python -m unittest discover -s tests -v
python cli.py --db demo.sqlite status
python cli.py --db demo.sqlite propose demo-1 BTC-USD 100 95 120 0.1 2030-01-01T00:00:00Z
python cli.py --db demo.sqlite decide demo-1 approve
# This is a simulated fill, not a Coinbase order; supply a current UTC candle timestamp:
python cli.py --db demo.sqlite paper-entry demo-1 100 2026-10-26T00:00:00Z
```

The sample entry command uses a historical candle timestamp and will be rejected when stale. Supply a current completed candle for a valid simulation.

To stage a JSON array of Coinbase-shaped **fixture** fills without accessing Coinbase:

```bash
python cli.py --db import.sqlite import-fixture examples/fills.json --portfolio demo
python cli.py --db import.sqlite import-fixture examples/fills.json --portfolio demo
```

The second run should report duplicates, not new inserts.

## Critical limitations

1. **No live Coinbase API polling and no automatic Notion writes are implemented in this Python package.** The separately scheduled ChatGPT automation is not a substitute for a verified backend worker.
2. **No authenticated web service or secure remote approval UI.** `decide()` assumes a trusted operator; do not expose it directly.
3. **No paper closing/settlement, cash ledger, reconciliation of deposits/withdrawals, or realized P&L**. Planned-risk budget is not realized-loss tracking.
4. **No concurrent multi-process integration tests, deployment monitoring, retry queue, or database backups**. SQLite is suitable for local prototyping, not an assumed hosted multi-worker system.
5. Fee/slippage assumptions are fixed conservative approximations; model results are not guaranteed execution prices.
6. Import staging and the paper gate share a database path if selected but have separate tables; staged fills do not authorize paper trades. No exchange credentials should be stored in Notion or in this repository.
7. This project is separate from the earlier `coinbase-crypto-bot` repository and has not been committed or deployed there.

## Next production milestones

- Build a read-only Coinbase pagination worker with durable checkpoints and authenticated access, verifying complete portfolio and history coverage.
- Implement authenticated Notion synchronization with idempotent upserts, conflict handling, and retry logging.
- Add a backend authorization boundary that binds user identity, proposal ID, expiry and one-time approval token; keep real trading endpoints absent.
- Add cash/position ledgers, exits, fees, reconciliation and comprehensive failure-injection tests.
- Deploy with persistent storage, access controls, observability and backups; verify one full unattended run before claiming production readiness.

## v0.3 authenticated local API (paper-only)

Set a random 32+ character `PAPER_API_TOKEN` environment variable, then run `python server.py` from this directory. The API binds to `127.0.0.1:8000` by default. `GET /health` is public; all other endpoints require `Authorization: Bearer <PAPER_API_TOKEN>`.

Supported routes: `GET /proposals`, `POST /proposals`, `POST /proposals/{id}/decision`, and `POST /proposals/{id}/simulate`. Requests and responses use JSON. A proposal includes `id`, `pair`, `entry`, `stop`, `target`, `quantity`, `expires`; decisions include `approve` (JSON boolean); simulation includes `market_price` and `candle_utc` (ISO 8601 with timezone). This API has no live trade route. Use an HTTPS reverse proxy and a durable mounted database volume before any internet-facing deployment. **Do not expose this prototype publicly yet:** it lacks rate limiting, Notion webhook signature verification, CSRF considerations for browser use, multi-operator authorization, and robust concurrent processing. It is a single-process development server.

Notion approval queue polling and Coinbase ingestion workers are **not yet connected** to this HTTP service. Never interpret changing a Notion status field as sufficient authorization to execute a simulated fill. The API requires a separate authenticated decision call, and simulation requires another call after checking conditions.

## v0.5 offline Notion reconciliation planner

`notion_sync.py` plans idempotent fill creates, detects conflicting/duplicate Notion keys and invalid amounts, and explicitly denies treating Notion status as execution authorization. It **does not make Notion API calls** or poll Coinbase; applying planned creates requires a credentialed, retry-safe worker. This module does not constitute a PostgreSQL migration or live service.

## v0.6: Notion adapter (local, dry-run ready)

`notion_adapter.py` converts staged Coinbase fills to the Trade Fills database's
Notion property shape and parses existing pages for reconciliation. The worker
must first read **all** existing Notion rows (including pagination), then run
`plan_staged_to_notion`; do not write if pagination fails or any conflict exists.
No credentials, HTTP writer, scheduled worker, or cloud persistence are bundled.

**Important:** `to_notion_properties` assumes the named Notion database columns
have compatible types (Select/Number/Date/Rich Text/Checkbox). Inspect the live
schema before using it. The adapter's `Live observed` mode means *historical
Coinbase execution observed in a read-only API*, not authorization for a trade.
Never use Notion's `Approved` status to bypass the paper-only gate.

Run `python -m unittest discover -s tests -v` from the project root.
