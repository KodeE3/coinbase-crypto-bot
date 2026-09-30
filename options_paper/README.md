# Options paper account

For the selected alternative to Alpaca, start with [Tradier setup](#tradier-alternative).

An educational simulator for one-contract long calls. No broker order connection or real orders. An optional read-only Alpaca adapter fetches market data. The signal is an unvalidated 5-day/10-day moving-average example. All demo prices are fictional.

## Unattended offline demo

```bash
python -m options_paper.demo
```

This command completes one fictional buy, account restart, quote update and profit-target sale
without any prompts, credentials or network access. It always creates a fresh temporary
account and deletes it afterward; it does not open your saved accounts. The JSON report shows
cash falling from $10,000 to $9,849.35 at entry, then ending at $10,078.70 with $78.70 fictional
realized P/L. Both $0.65 fees are included. Repeated runs produce the same report. The command
terminates after the example and does not monitor markets or validate profitability.

The regular commands below retain their explicit simulated-trade confirmation prompts.

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
- Closing requires the exact contract confirmation and a nonnegative bid. Exit quotes must not predate entry or the saved quote, and cannot change the saved bid at the same timestamp. Expiry-day and later closes are rejected because settlement/exercise is not implemented.

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

A quote or position that changes while approval is pending must be reviewed again. The database migration adds a marks table without resetting existing cash, positions, or history. Quotes can come from supplied files or the optional Alpaca refresh command below.


## Connect Alpaca market data (optional)

The adapter makes GET requests only to allowlisted market-data paths on `https://data.alpaca.markets` and the contract-catalog path `/v2/options/contracts` on `https://paper-api.alpaca.markets`. It never submits an order or reads a brokerage account balance. It uses the standard library; systems must have IANA timezone data. Requests have a 10-second timeout, bounded response size, and no credential-forwarding redirects. Errors do not print API keys or provider response bodies.

Set these two environment variables through your GitHub Codespaces secrets, with repository access enabled, then restart your Codespace:

- `APCA_API_KEY_ID`
- `APCA_API_SECRET_KEY`

Use credentials from your Alpaca paper account for discovery. Do not put keys in source code, commit them, or paste them into chat. This module does not automatically load `.env` files. No subscriptions are purchased by the code.

Test the stock-data connection:

```bash
python -m options_paper.market_data --symbol SPY
```

This returns completed daily closes, timestamps and the explicitly selected `iex` feed (one exchange, not consolidated market coverage). Today's daily bar is excluded using America/New_York time. `--stock-feed sip` requests consolidated data if entitled. Pagination and an eleven-completed-bar minimum are checked. This diagnostic is informational and does not by itself select or buy an option.

To check options access, append `--contracts` followed by actual, unexpired standard option symbols from your provider. Fictional `DEMO-...` symbols are rejected. Option quotes explicitly request `opra`; Alpaca documents that the alternative `indicative` feed has modified quotes and delayed trades, so there is no automatic fallback. OPRA access depends on your data entitlement. A 403 error means you should check access before proceeding, not change your broker account or purchase anything blindly.

Refresh the actual-symbol positions already in the local snapshot simulation account:

```bash
python -m options_paper.cli --refresh-quotes
python -m options_paper.cli --refresh-quotes --review-exits
```

Use `--account path/to/account.sqlite3` if you previously selected a custom account. No open positions means no network call. `--demo` is incompatible with provider refresh. The first command saves and values the quotes without trading. The second prompts for each suggested simulated exit, fetches that quote again after confirmation, and refuses the sale if its bid or exit eligibility changed. An unchanged price with a newer timestamp can proceed. Original quote timestamps are retained; stale/future/missing/invalid quotes reject the entire update rather than generating substitute prices. Outside market hours, quotes may fail the 15-minute freshness rule; that is expected.

This is an on-demand refresh, not a background streaming service. Automatic discovery and entry snapshot assembly are available through the separate command below. Historical stock bars alone cannot validate an options strategy. Authenticated provider access remains unverified in the implementation environment.

Provider references:

- https://docs.alpaca.markets/us/reference/optionlatestquotes
- https://docs.alpaca.markets/us/reference/stockbars
- https://docs.github.com/en/codespaces/managing-your-codespaces/managing-your-account-specific-secrets-for-github-codespaces

## Automatic discovery and entry snapshots

```bash
python -m options_paper.discovery --symbol SPY --output paper_data/entries/spy-001.json
```

Requires Python 3.10+, IANA timezone data (`America/New_York`), Alpaca **paper** API
credentials, and access to OPRA option snapshots. Linux/Codespaces normally includes timezone
data; Windows Python may require the `tzdata` package. The command runs once, prints a JSON
summary and stops. It has no account argument, trade prompt, order endpoint or background loop.

| Data | Source and timing |
|---|---|
| Underlying trend | Up to 30 completed split-adjusted daily stock bars; minimum 11. `iex` by default; `--stock-feed sip` if entitled. |
| Identity and open interest | Paper contract catalog, with reporting date preserved. OI must be dated between the latest completed stock session and the current New York date. |
| Bid, ask and delta | OPRA snapshots. Quotes must be no more than 15 minutes old and not future-dated. No indicative fallback. |
| Volume | Option daily bar for the latest completed underlying session, **not current intraday volume**. Missing data excludes the contract. |

Discovery covers active, tradable standard calls expiring in 21–45 calendar days, with
strikes between 80% and 120% of the latest completed stock close. This is a bounded research
universe, not the entire option chain. OCC symbol, root, underlying, expiry, strike and
100-share size must agree; adjusted roots and other sizes are excluded. The metadata
checks do not model arbitrary corporate-action deliverables.

All discovery pages must finish: ten pages per collection, at most 1,000 discovered contracts,
and enrichment in sorted batches of at most 100. Invalid/looping pagination, duplicate
identities, duplicate daily bars, provider errors or exhausted limits abort without saving
a new snapshot. Malformed/ineligible metadata and missing/stale quote, delta or volume
data exclude the contract and increment a diagnostic count. A complete scan with no usable
contracts is saved as a rejected research observation; it is not a trading signal.

Output includes underlying bars, feeds, filters, collection times, original quote times,
volume and OI dates, exclusion counts, and the existing strategy's proposal preview.
The snapshot `as_of` is the **oldest included quote**, not its download time. Quotes are
checked again after collection; data that aged out is excluded. Provider greeks have no
independent timestamp, so `greeks_timestamp` is explicitly null. A fresh quote does not
establish that delta was recomputed at that instant.

Snapshots are written completely before becoming visible, using a same-filesystem hard link.
Use a filesystem supporting hard links (such as NTFS or ext4). Existing output files are
never overwritten. Fix reported dependency/output issues and rerun with a new filename.
Outside trading hours, stale quotes commonly yield no candidate.

To review a saved observation for a **local simulated buy**, run promptly:

```bash
python -m options_paper.cli --snapshot paper_data/entries/spy-001.json
```

The CLI recomputes the proposal, asks for the full contract symbol, then rechecks freshness
and account risk limits. It does not trust `proposal_preview` as authorization or refresh
prices during entry confirmation. Regenerate stale snapshots. Original delta, spread,
volume (100), OI (500), fee, $200/2% entry, exposure, duplicate-position and daily realized-loss
rules remain unchanged. A preview can pass strategy filters but fail account limits;
many SPY contracts may exceed the small example budget. Do not loosen limits to force entry.

Run `python -m unittest discover -s tests -v` and `python -m options_paper.demo`.
Tests exercise mocked collection through saved JSON and a reviewed paper purchase,
pagination/batching, stale/malformed data, quote aging, redacted errors, atomic output,
overwrite refusal and unchanged account risk limits.

Next: verify paper-catalog/OPRA connectivity with configured secrets, collect dated forward
observations with frozen rules (including rejections), then evaluate options results with
costs and an untouched chronological holdout. Expiry settlement, historical options replay,
executable fill modeling and background monitoring remain unimplemented. Neither a generated
candidate nor the fictional demo establishes profitable income.

Provider schema references checked 2026-09-29:

- https://docs.alpaca.markets/us/reference/get-options-contracts
- https://docs.alpaca.markets/us/reference/optionsnapshots
- https://docs.alpaca.markets/us/reference/optionbars
- https://github.com/alpacahq/alpaca-py/blob/master/tests/trading/trading_client/test_option_routes.py

## Tradier alternative

Tradier now supports both automatic entry discovery and quote refresh for reviewed exits.
The adapter permits GET requests only to four market-data paths on `api.tradier.com`:
`history`, `options/expirations`, `options/chains`, and `quotes`. It has no broker account,
order, exercise, cancellation or live-execution interface. Production **data** does not
change the local simulator into production trading.

### Configure access

1. Obtain a production API token through your own Tradier account's API settings.
   Sandbox tokens are unsuitable for this strategy: Tradier documents delayed sandbox
   quotes and no sandbox Greeks. No account is opened or subscription purchased by the bot.
2. Store it as `TRADIER_ACCESS_TOKEN` in the runtime's environment secrets. In Codespaces,
   add a Codespaces secret with access to this repository, then restart the Codespace.
   A GitHub Actions secret does not automatically become a Codespaces environment variable.
   Never put the token in chat, source files, command arguments, or committed configuration.
   This project does not load `.env` files automatically.
3. Check out the updated `codex/options-paper-foundation` branch. Python 3.10+ and IANA
   timezone data are required, as for the existing adapter.
4. Run during regular market hours with a new output filename:

```bash
python -m options_paper.discovery --provider tradier --symbol SPY --output paper_data/entries/spy-tradier-001.json
```

Discovery saves an observation and proposal preview, never an account or trade. Missing
credentials, authentication/access errors, malformed collections, duplicates, unexpected
pagination, or exhausted limits stop collection. There is no automatic provider or sandbox
fallback. HTTP failures are redacted; redirects are blocked and response sizes are bounded.
`--stock-feed` applies only to Alpaca and is rejected with Tradier.

Then optionally review the saved snapshot for a local simulated buy:

```bash
python -m options_paper.cli --snapshot paper_data/entries/spy-tradier-001.json --account paper_data/tradier.sqlite3
python -m options_paper.cli --provider tradier --refresh-quotes --account paper_data/tradier.sqlite3
python -m options_paper.cli --provider tradier --refresh-quotes --review-exits --account paper_data/tradier.sqlite3
```

The full-symbol entry/exit confirmations and all paper-account risk limits still apply.
Exit review fetches the selected quote again after confirmation; a changed bid or lost exit
condition requires another review. Specify `--provider tradier` on each refresh command;
the compatibility default remains Alpaca. Keep provider experiments in separate paper accounts.

### Data policy and research limits

- Discovery examines all returned expirations 21–45 days away, standard 100-share calls,
  and strikes within 80–120% of the latest completed underlying close. Bounds are 20
  expirations, 10,000 total chain rows (including puts/out-of-universe rows), 1,000 candidate
  calls, and 2 MB per response. Exceeding a bound fails the scan instead of ranking a subset.
- Underlying history uses completed daily dates and up to 30 closes, with an 11-bar minimum
  and latest session no more than seven days old. Tradier's reported historical adjustments
  are not guaranteed to match Alpaca's split-adjusted history; corporate actions need review.
- Both bid and ask timestamps must be at most 15 minutes old and not future-dated. Their
  older timestamp is retained, and freshness is checked after chain collection. Timestamp
  seconds and milliseconds are normalized explicitly. Old observations cannot be refreshed
  by changing their download timestamp.
- `volume` is **current-day provider volume**, unlike Alpaca's completed-session volume.
  OI is supplied as a number without a reporting date; `open_interest_date` stays null.
  No reporting date is inferred from the quote or previous close.
- Tradier documents **hourly** ORATS Greeks. `updated_at` is preserved. Explicitly zoned
  timestamps must not be future-dated or more than 90 minutes old. Official examples also
  contain timezone-free timestamps: those must match the current New York calendar date,
  but their intraday age cannot be verified and no timezone is invented. These observations
  are labeled `provider_timezone_unspecified`; a fresh quote does not prove a fresh delta.
- Missing or invalid Greeks, prices, dates or liquidity values exclude the candidate and
  increment diagnostics. Unknown OI date and Greek timezone are explicit provider limitations,
  not proof of freshness. The unchanged illustrative strategy may still produce a paper
  proposal from such data. Do not interpret it as a validated execution recommendation.
- Results carry `policy_id: tradier-intraday-v1`. Do not pool them with Alpaca observations
  as though feed, liquidity timing and adjustment policies were identical.

Current checkpoint: all 69 tests pass locally, including 18 Tradier tests. Authenticated
Tradier connectivity is **not yet verified** because the token is absent in this runtime.
Next: configure the secret, collect one market-hours observation, inspect timestamps and
exclusion counts, then gather forward paper research under frozen rules. No live orders or
profitability claims are part of this checkpoint.

References checked 2026-09-29:

- [Tradier market-data coverage and Greek cadence](https://docs.tradier.com/docs/market-data)
- [Token settings](https://web.tradier.com/user/api)
- [Option chains](https://docs.tradier.com/reference/brokerage-api-markets-get-options-chains)
- [Option expirations](https://docs.tradier.com/reference/brokerage-api-markets-get-options-expirations)
- [Quote field definitions and timestamp examples](https://docs.tradier.com/docs/quotes)
- [Historical-data limitations](https://docs.tradier.com/docs/historical-data)
