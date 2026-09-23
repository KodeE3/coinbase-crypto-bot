# Options paper prototype

This isolated Python standard-library prototype proposes one **long call** from a supplied JSON snapshot. It uses a simple 5-day versus 10-day moving-average rule, a rising latest close, and filters on days to expiration, delta, bid/ask spread, volume, open interest, and maximum premium. These are example rules, **not a validated profitable strategy**.

Run from the repository root with Python 3.10+:

```bash
python -m options_paper.cli --demo
python -m unittest discover -s tests -v
```

The demo uses fictional historical prices and a fictional `DEMO-...` contract. Press Enter to skip, or type its full symbol to record an illustrative buy in `options_paper_journal.jsonl`. The sample sets $10,000 paper equity and allows at most the smaller of 2% of equity or $200 premium, with one 100-share contract. It assumes an immediate buy at the quoted ask and shows the bid value; **no execution or realistic fill is guaranteed**. The JSONL journal records opens only, not realized returns.

To try your own snapshot, use `python -m options_paper.cli --snapshot path/to/snapshot.json`. Follow `sample_snapshot.json`'s schema; include a timezone in `as_of` and a snapshot no older than 15 minutes. Each `closes` entry represents one completed daily bar. Quotes and bars must come from a properly licensed, trustworthy feed; this prototype does not fetch or verify them. It does not check market hours, quote synchronization, halts, corporate actions, broker rules, commissions, slippage beyond the displayed spread, exercise, or expiry. Do not treat a proposal as an order ticket.

No API credentials, network access, broker adapter, order submission, automatic execution, position exits, or real-money mode are included. Before expanding it, obtain historical underlying **and option-chain** data, define a genuine backtest with transaction costs and out-of-sample evaluation, then add a broker-supported paper account and controlled exits. Long options can lose their entire premium, and holding to expiration can trigger exercise. Keep this sample isolated from the Coinbase crypto bot; Coinbase crypto markets are not the U.S. listed options market.
