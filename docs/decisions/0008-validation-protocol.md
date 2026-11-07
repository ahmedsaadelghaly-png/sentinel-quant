# ADR 0008 — Automated validation protocol

- Status: accepted, thresholds approved by the user on 2026-11-07
- Date: 2026-11-06

## Context
Gates G3 to G5 need data the strategy has not seen, and evidence that the result survives small changes. A held-out period is worthless if a routine command can read it.

## Decision
- **Holdout by default.** Bars from `validation.holdout_start` are removed before `backtest` and `validate` run. Opening them takes an explicit flag and is written to the registry. A run with no record counts as having seen them.
- **One use.** After the first opening, G3 reports NOT_ASSESSED rather than a pass.
- **Walk-forward re-fit:** parameters are chosen by net Sharpe on each training period from a 3 by 3 grid, then measured only on the following test period. Training bars warm the strategy up.
- **Every variant is a trial,** which raises the deflation bar, as it should.
- **Fixed thresholds** (code constants, set before any strategy was tested):
  - G2: net P&L and expectancy above zero.
  - G3: holdout Sharpe above zero and at least half the development Sharpe.
  - G4: at least 60% of windows positive, and stitched return above zero.
  - G5: at least 70% of neighbouring parameters positive, net profit at double costs, at least half of calendar years positive.
- **G1, G7 and G8 are never automated,** and the report says it does not approve anything.

These percentages are judgement calls, not standards.

## Consequences
A full validation takes about two minutes on two symbols. Validation is written for the Donchian strategy and needs generalising when a second strategy arrives. The holdout date is fixed, so it needs moving forward deliberately as data grows, with new data counted as unseen only for strategies designed before it existed.
