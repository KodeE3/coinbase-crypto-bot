# FX AutoTrader v2.2 — demo-only reliability update

Derived from v2.1. Keeps the nine-pair hybrid signal, 80/100 minimum score,
0.5% planned risk, two-position maximum, 2% daily equity stop, three-loss cooldown,
shared-currency exposure checks, and demo-only execution. Orders are OFF and the
kill switch is ON by default. There is no live-account override.

New safeguards:
- Persist signal bars and a pending submission marker before OrderSend. A restart
  with an unresolved marker latches the kill switch. Any rejected/uncertain submission
  stops further attempts; broker history must be reconciled manually before clearing
  pending and kill variables. A conservative failed attempt can therefore skip a trade.
- One v2.2 instance per demo account per terminal, using an atomic terminal lock.
- Expiring manual calendar clearance: `CalendarCheckedAndClear=true` also requires
  `CalendarClearUntilUTC` strictly in the future and at most 24 hours away. This is
  **not** an automatic news feed. Keep the computer clock correct and review every
  event in the intended clearance interval before granting it.
- A monotonic elapsed-time watchdog detects frozen server quote time. No entry
  occurs until server time advances after startup and the terminal is connected.
- Pending orders also count as overlapping currency exposure. Loss streaks include
  different tickets closed during the same second. Tick size/value use symbol
  properties; slippage allowance is included in modeled stop sizing.
- A heartbeat UTC timestamp and chart status distinguish a running blocked scanner
  from a stopped terminal. Heartbeat alone does not establish a broker connection.

Installation: detach v2.1 and any other trading EA first. Copy the `.mq4` file into
MQL4/Experts, compile in MetaEditor, and resolve all warnings/errors. Compilation has
not been performed here. Attach only to an OANDA demo account. Do not attach multiple
terminals to the same demo account: terminal-global locks cannot coordinate separate
terminals, and v2.1 does not participate in the v2.2 lock protocol.

Forward-test with valid nine-pair history and broker symbol specifications. Confirm
disconnect/reconnect, restart immediately around submission, rejected orders, calendar
expiry, concurrent attachment rejection, quote stalls, minimum lots, gap slippage and
protective stop placement. Multi-symbol behavior cannot be established by the Python
source checks or by assuming MT4's single-symbol tester reproduces the portfolio.

New orders require all of: demo login, terminal AutoTrading, EnableDemoAutoTrading=true,
EmergencyKillSwitch=false, cleared persistent kill/pending flags, and unexpired reviewed
calendar clearance. Do not clear a pending marker until broker history and open positions
are reconciled. Kill controls stop new orders; they do not close existing positions.

Terminal variables use the account-specific FXAT prefix. Tester variables use a
separate FXAT_TEST prefix; use a clean tester state between independent test runs.
Legacy account-level FXAT_KILL flags are respected. Terminal global variables expire
after four weeks without access; long-offline resumes require manual reconciliation.
Keep terminal trade history set to All History for loss-streak checks.

Global variables are flushed before submission. Hardware/terminal failures still require
broker reconciliation. Fees, swaps and gaps can exceed planned risk. A post-fill stop-risk
mismatch latches the kill switch but does not automatically liquidate the position.
