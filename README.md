# Trading bot experiments

This repository contains the options paper-account experiment on the `codex/options-paper-foundation` branch. The original Coinbase BTC bot project is separate work.

Start the fictional options demo:

```bash
python -m options_paper.cli --demo
```

Read [the complete options tutorial](options_paper/README.md) for buying, closing, checking balances, and running tests. Python 3.10+ is required; no extra packages or brokerage credentials are needed.

For an unattended fictional trade cycle, run `python -m options_paper.demo`. It uses a disposable
account, prints a JSON report, and stops. It requires no input, credentials or network access.

## Automatic option discovery (paper research only)

With Alpaca paper credentials and OPRA data access configured in the environment:

```bash
python -m options_paper.discovery --symbol SPY --output paper_data/entries/spy-001.json
```

This saves a dated entry snapshot and proposal preview without creating an account or
recording a trade. See [setup, safeguards and limitations](options_paper/README.md#automatic-discovery-and-entry-snapshots).

## Autonomous coding agent

The repository includes [Trading Finisher](.github/agents/trading-finisher.agent.md), a VS Code
custom agent that handles implementation, testing and documentation without routine questions.
Open this branch in VS Code, select **Trading Finisher** in the Chat agent dropdown, and send:

> Resume docs/agent-progress.md. Complete the next unblocked coding milestone, run the tests
> and offline demo, fix failures, and update the progress notes. Make routine decisions yourself.

Other agents can invoke it as a subagent when supported by their host. This file does not start
an always-running service; a supported active agent session is required. Tool approvals and
session limits still apply. It is authorized to improve the simulator, not to trade real funds.
Progress and remaining integration blockers are recorded in [the resume log](docs/agent-progress.md).

Agent format reference: https://code.visualstudio.com/docs/agent-customization/custom-agents
