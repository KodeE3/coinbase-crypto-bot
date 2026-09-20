# Strategy improvement experiment

**Decision: retain the baseline as the default; keep the new strategies experimental.** A weekly-breakout candidate improves development profit, but it fails both later internal validation segments and is sensitive to execution costs. No profitable replacement has been established.

## Fixed experiment

Compared the baseline against three predeclared candidates: slower SMA 50/200 with a 4% stop; weekly close breakout above 168 preceding closes with an SMA 200 trend filter, 72-hour channel/SMA exit and 4% stop; and the same breakout with a 6% trailing stop. The trailing stop uses prior completed closes only.

Account risk stays fixed: $10,000 initial cash, 0.5% planned risk, 20% cash allocation limit, 2% daily loss limit, 10% drawdown limit, and permanent halt after three consecutive losses. Wider stops reduce position size. No leverage or automatic restart was introduced.

Development: 2024-08-27 to 2025-08-20. Internal validation A: 2025-08-20 to 2025-10-25 16:00 UTC. Internal validation B: 2025-11-04 to 2026-02-20. All ends are exclusive. Each segment starts a fresh account; these returns must not be compounded as one live record.

Start dates ensure a full 200-hour warmup. Validation is split around missing Coinbase hours, with enough observed data after the gap to warm up. Every segment is contiguous and validated; no prices are filled. The previously examined six-month holdout is not evaluated here. These internal validation dates were already broadly observed in the earlier baseline study, so they are not a pristine unseen test.

## Baseline-cost results

Assumed per-side fees: 0.6%; adverse slippage: 0.1%. These are simulation assumptions, not verified account fees. All runs finish flat; returns include all fills and costs.

| Candidate | Development return | Trades / max drawdown | Validation A | Validation B |
|---|---:|---:|---:|---:|
| baseline | -1.10% | 3 / 1.10% | -1.01% | -0.92% |
| slow_trend | -1.09% | 3 / 1.21% | -0.39% | -1.76% |
| weekly_breakout | 2.24% | 9 / 1.28% | -0.56% | -1.13% |
| weekly_breakout_trailing | 1.11% | 10 / 0.84% | -0.41% | -0.82% |

The fixed-stop breakout is the strongest development candidate (+$224.02 versus -$109.99 baseline), but its later returns are negative. The trailing version reduces losses in both later segments but sacrifices development profit. All baseline-cost runs eventually halt, so these are not year-long records of continuous trading. The breakout development run halted on 2025-01-07 after nine closed trades; its later segments each halted after three losses.

## Cost sensitivity

| Candidate | Development at lower costs | Development at stress costs |
|---|---:|---:|
| baseline | -1.21% | -1.20% |
| slow_trend | -1.01% | -1.16% |
| weekly_breakout | 2.74% | -0.36% |
| weekly_breakout_trailing | 1.30% | -0.27% |

Lower assumptions: 0.2% fee and 0.05% slippage per side. Stress: 1% fee and 0.2% slippage. These rerun risk sizing, stop fills and halt decisions; results need not vary monotonically with fees because the trade sequence can change. Both breakout variants remain negative in both later validation segments under every tested cost assumption.

## Verification and limits

18 tests pass locally, including no-lookahead breakout entries, channel exits, trailing-stop timing, serialized restart state, full warmup and unchanged portfolio risk limits. The original 10 tests also still pass. The default baseline behavior is retained. Candidate selection is not based on the old holdout, and no parameters were changed after examining the candidate results.

Small trade samples and early halts preclude a reliable claim of sustained profitability. Missing-data periods are excluded rather than simulated. Hourly OHLC fills do not capture latency, spread variation, market depth or intrabar sequence. Final profits are historical simulations, not promised future returns.

## What changed

Added explicit --strategy presets to backtesting and paper mode, prior-close trailing stops, strategy-specific warmup, compatibility with existing baseline paper settings, regression tests, and a reproducible fixed experiment runner. Paper sessions require a new database when switching strategy. Real-order execution remains absent.

## Next research step

Keep the breakout as a research lead, not an approved trading strategy. Specify the next hypothesis and criteria before further tuning; use development data only and reserve genuinely new observations for a forward test. Do not automatically relax the three-loss halt to keep a disappointing strategy trading.

experiments.json contains the 12 baseline-cost runs. cost-sensitivity.json contains 24 further runs. The repository runner research/compare_strategies.py recreates them using the saved study CSV.
