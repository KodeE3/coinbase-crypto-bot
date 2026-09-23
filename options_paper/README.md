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

`--status` reports open **cost basis**, not current market value or live account equity. This version has manual closes, not automatic stop-losses or profit targets. The $0.65 fee and risk limits are tutorial assumptions, not broker pricing or personalized advice. Long options may lose their entire premium; exercise obligations are outside this simulator.

## Verification and next work

```bash
python -m unittest discover -s tests -v
```

GitHub Actions runs these tests on pushes to the options branch and pull requests into main. Tests cover balances through a restart, fees and realized P/L, duplicate trades, insufficient cash, entry/exposure/loss limits, stale approval, malformed data, account mode isolation, and invalid exits.

Next: verified underlying and option quote timestamps, mark-to-market reporting, modeled exits and expiration, historical option-chain replay with costs and out-of-sample evaluation, then broker-supported paper integration. Do not judge strategy profitability from the demo.
