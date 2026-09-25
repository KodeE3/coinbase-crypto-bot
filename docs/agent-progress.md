# Trading Finisher progress

Updated: 2026-09-25. Project: options paper-account experiment in KodeE3/coinbase-crypto-bot.
Working branch: `codex/options-paper-foundation`; draft pull request: #2.

## Completed milestone and result

This implementation milestone is a runnable, offline paper-trading MVP and reusable autonomous coding
agent. It is complete locally: fictional entries, persistent accounts, saved valuations,
reviewed exits, a complete unattended fictional demo, and automated regression checks.
The trading strategy remains an unvalidated tutorial; the full trading product and live operation
are not complete. The user's broad request to finish the project does not define requirements
for the future trading features listed below.

Implemented this milestone:

- VS Code `Trading Finisher` custom agent, usable directly or as a subagent, with bounded
  coding autonomy, completion gates and this resume log.
- `python -m options_paper.demo` runs a finite fictional buy/restart/mark/sell cycle with no
  prompts or network. Its temporary database is deleted; existing user accounts are untouched.
  It emits JSON with $10,078.70 final cash and $78.70 fictional realized P/L after fees.
- Manual simulated exits can no longer substitute a different bid at the same timestamp
  as a saved quote. UTC daily-loss checks now align with UTC event recording when the
  caller supplies a clock in another timezone. Snapshot closes must be a JSON list.
- Regression coverage for these three fixes and the repeatable, isolated unattended command.

## Verification evidence

- Baseline: 27 tests passed before changes.
- Updated suite: 32 tests passed locally via `python -m unittest discover -s tests -v`.
- Demo exercises account reopen, profit-target rule evaluation and fee-inclusive sale.
- Offline/no-input test fails if the demo attempts a socket or input prompt.
- The existing-account subprocess test starts in a separate working directory containing
  a sentinel account and verifies it is unchanged.
- GitHub Actions already runs unittest discovery under Python 3.10 and 3.12. Remote CI
  results must be checked for the final pushed commit; local success is not remote success.
- Agent format checked against the official VS Code custom agents reference. Actual VS Code
  agent loading/invocation is not tested in this container, which has no running VS Code UI.

## Remaining external blockers and resume action

0. **Publishing was blocked by automatic approval review.** Local changes are committed, but
   the push to `KodeE3/coinbase-crypto-bot` / `codex/options-paper-foundation` was rejected
   because publishing to that destination lacked explicit user authorization under the review.
   Remote branch remains at `4080bdce84bd2b199e297d33b996a5b201741ef2`; draft PR #2 was not
   updated. Request approval for this exact destination and PR update; do not use another
   transport to bypass the rejection. Offline implementation and testing are complete.
1. **Authenticated data access is unverified.** When Alpaca credentials are available through
   authorized environment secrets, run `python -m options_paper.market_data --symbol SPY`.
   For OPRA, supply actual unexpired option symbols to its `--contracts` argument. Record
   only redacted outcome, feed and quote timestamps. Do not buy access or silently downgrade
   to indicative quotes. If secrets/entitlement are absent, retain this blocker.
2. **User's VS Code host has not loaded the agent yet.** Open this branch, select Trading
   Finisher in the agent picker and use the resume prompt in README.md. Host permissions,
   available tools, subscription and session limits determine whether it can execute there.
3. **Future product scope is not implemented:** automatic option discovery and entry-snapshot
   assembly, historical options replay/out-of-sample validation, expiry settlement, broker
   paper-order integration and persistent background monitoring. These are distinct future
   milestones, not requirements to claim the offline demo complete. Select one only when
   the task specifies that scope; never infer authorization for real-money execution.

If resuming with no new task and these are still the only blockers, recheck the documented
completion gates and report the bounded milestone complete. Do not request ordinary design
decisions from the user or continue indefinitely.
