# Options paper account

An educational simulator for one-contract long calls. No broker connection, live quotes, or real orders. The signal is an unvalidated 5-day/10-day moving-average example. All demo prices are fictional.

## Try a complete trade

From the repository root, with Python 3.10 or newer (no packages to install):

```bash
python -m options_paper.cli --demo
```

Type `DEMO-SPY-20261023-C-110` to confirm the sample buy. Press Enter to skip.

```bash
python -m options_paper.cli --demo --status
python -m options_paper.cli --demo --close DEMO-SPY-20261023-C-110 --bid 1.80
```

Type the same contract symbol to confirm the simulated sale. Then inspect:

```bash
python -m options_paper.cli --demo --status
python -m options_paper.cli --demo --history
```

Expected example: start with $10,000; buy at $1.50 x 100 plus a $0.65 fee, leaving **$9,849.35**; sell at $1.80 x 100 minus a $0.65 fee, leaving **$10,028.70**, with **$28.70 realized profit**. This is arithmetic using invented quotes, not evidence of strategy performance.

The account persists in `paper_data/demo.sqlite3`, including after a restart. The identical proposal cannot be reused even after closing. To repeat the tutorial, choose a new file with `--account paper_data/demo2.sqlite3` on every command. Existing legacy JSONL journals are not imported: they lack the account and exit information needed for reliable balances.

## Snapshot simulation

```bash
python -m options_paper.cli --snapshot path/to/snapshot.json
python -m options_paper.cli --status
python -m options_paper.cli --close CONTRACT --bid 1.80 --as-of 2026-09-23T14:30:00Z
```

The last timestamp is an example; supply the actual quote time. Follow `sample_snapshot.json` for schema. `paper_equity` in that legacy fixture is ignored: the database owns the cash balance. Every new account starts with $10,000. Use completed daily closes and contemporaneous option quotes. Quote freshness is checked at proposal time and again at buy confirmation (15-minute maximum age). Prices are not refreshed automatically. Snapshot accounts use `paper_data/snapshots.sqlite3`; mixing demo and snapshot modes in one file is rejected.

The demo intentionally replays its fixed date, including a default exit quote date one day after the sample entry. `--as-of` can override the demo exit date. All fills are illustrative: buy at the supplied ask and sell at the supplied bid. There is no liquidity/depth model, partial fill, latency, or additional slippage model. Supplied quotes are not independently verified.

## Account rules

- Cash, positions, and trade events update together in a SQLite transaction, using integer cents.
- One contract per position and only one open position per underlying; three open positions maximum.
- Entry including the illustrative $0.65 fee cannot exceed the smaller of $200 or 2% of initial cash plus realized P/L.
- Aggregate open entry costs cannot exceed 10% of that same capital figure; entries also require sufficient cash.
- A 2% of initial-cash daily realized loss limit blocks further entries for that UTC recording date. It is not an unrealized-loss stop.
- Closing requires the exact contract confirmation and a nonnegative bid. Exit quotes must not predate entry. Expiry-day and later closes are rejected because settlement/exercise is not implemented.

`--status` reports open cost basis plus estimated net sale values when saved quotes are usable. Suggested exits always require approval; they are not automatic orders. The $0.65 fee and risk limits are tutorial assumptions, not broker pricing or personalized advice. Long options may lose their entire premium; exercise obligations are outside this simulator.

## Verification and next work

```bash
python -m unittest discover -s tests -v
```

GitHub Actions runs these tests on pushes to the options branch and pull requests into main. Tests cover balances through a restart, fees and realized P/L, duplicate trades, insufficient cash, entry/exposure/loss limits, stale approval, malformed data, account mode isolation, and invalid exits.

Next: a verified quote feed, historical option-chain replay with costs and out-of-sample evaluation, expiry/settlement modeling, then broker-supported paper integration. Do not judge strategy profitability from the demo.


## Update quotes and review exit rules

To run the new demo after completing the original buy/sell tutorial, use a fresh account filename. Start a position:

```bash
python -m options_paper.cli --demo --account paper_data/quotes-demo.sqlite3
```

Type `DEMO-SPY-20261023-C-110` to confirm. Load the first fictional quote:

```bash
python -m options_paper.cli --demo --account paper_data/quotes-demo.sqlite3 --quotes options_paper/sample_quotes.json
```

At a $1.80 bid, the open position has an estimated net sale value of $179.35, unrealized P/L of $28.70, and total estimated equity of $10,028.70. Cash remains $9,849.35. This quote triggers no exit rule. Quotes persist across process restarts:

```bash
python -m options_paper.cli --demo --account paper_data/quotes-demo.sqlite3 --status
```

Now load a later fictional quote at $2.30 and review the profit-target suggestion:

```bash
python -m options_paper.cli --demo --account paper_data/quotes-demo.sqlite3 --quotes options_paper/sample_exit_quotes.json --review-exits
```

Type the contract symbol to confirm, or Enter to leave the position open. Confirming results in $10,078.70 cash and $78.70 realized P/L after fees. Without `--review-exits`, quote updates save marks and show suggestions without recording trades. All figures use invented prices and illustrate accounting, not investment performance.

### Example exit policy

| Rule | Suggested exit when |
|---|---|
| Loss | Net estimated P/L is at or below -25% of entry cost |
| Profit | Net estimated P/L is at or above +50% of entry cost |
| Holding time | At least 7 elapsed calendar days since entry |
| Expiration | 2 or fewer calendar days before expiration |

Entry cost includes the buy fee. Estimated sale value is the bid times 100 minus the assumed sell fee; unrealized P/L includes both fees. These example policy constants live in `options_paper/quotes.py` and have not been optimized or validated as a strategy. A suggested stop is not a guaranteed loss cap. Rules are evaluated only when you run a command; there is no background monitor, scheduler, or broker order.

### Quote input and freshness

Use the two supplied quote JSON files as schema examples. A batch needs `as_of` and a nonempty `quotes` list. Every quote needs `contract`, `as_of`, `bid`, and `ask`. Use timezone-aware timestamps and cent-precision prices. Only open contracts are accepted. Zero bid is permitted for illustrative loss modeling and does not imply a real buyer exists. Expiry-day and expired positions are marked unavailable because settlement is not modeled.

In snapshot mode (omit `--demo`), quote ages are checked against the actual clock, including again when approving an exit. In demo mode the latest batch timestamp is the historical replay clock; the display explicitly labels all valuations historical and fictional. Each quote must be no older than 15 minutes at evaluation, cannot predate entry, and cannot replace a newer quote. Prices cannot change at an identical quote timestamp. Malformed batches are rejected atomically.

Partial batches are allowed, but missing or stale quotes make total estimated equity unavailable. This avoids presenting a partially priced portfolio as a complete balance. Total estimated equity is cash plus all usable net sale values, not verified brokerage equity. Entry risk limits still use initial cash plus realized P/L; they do not use these unrealized estimates. The daily loss guard still measures realized losses only.

A quote or position that changes while approval is pending must be reviewed again. The database migration adds a marks table without resetting existing cash, positions, or history. Quotes come from supplied files; automated market data acquisition remains a future step.
