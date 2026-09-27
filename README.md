# coinbase-crypto-bot
    Python crypto trading bot for Coinbase — starting with paper trading and BTC-USD

## Prediction-market paper bot

Run the offline demo with Python 3.10+ (no installs or credentials):

```bash
python -m prediction_paper.cli demo
```

[Setup, live-data collection, paper trading and replay](prediction_paper/README.md).
Uses Kalshi public data and Coinbase BTC candles with a persistent simulated account,
limits, fee modeling, and finalized settlement. No real-money execution.
Default live-contract approvals are empty pending settlement-rule review.
Synthetic demo profit is not evidence of a profitable strategy.
