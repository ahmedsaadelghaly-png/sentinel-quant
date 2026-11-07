# ADR 0007 — Evaluation statistics and G6 thresholds

- Status: accepted, thresholds subject to the user's review
- Date: 2026-11-06

## Context
MASTER_PLAN §6 requires G6 thresholds to be fixed in M3, before testing. A threshold chosen after seeing a result is not a test.

## Decision
- **G6 passes only with deflated Sharpe at least 0.95 and PBO at most 0.25.** A deflated Sharpe of 0.95 is the usual 95% confidence level. PBO of 0.5 means selection is picking noise, so 0.25 asks for clear evidence against that. The PBO figure is a judgement call, not a standard.
- **Thresholds are code constants,** not config: changing one takes a code change and an ADR.
- **All registry trials of a strategy count towards deflation,** including cost stress runs, which errs on the strict side. PBO compares only trials on identical datasets, and needs at least four.
- **The variance of trial Sharpes is never taken below the sampling variance of one estimate.** With few similar trials, the sample variance alone would nearly remove the luck benchmark.
- **Statistics use daily returns,** since hourly bars would inflate the observation count.
- **Bootstrap:** stationary blocks with mean length 20 days, fixed seed. Measured coverage of nominal 95% intervals: 91% at 500 observations, 95 to 97% at 2,000. Intervals on short histories run slightly narrow.
- **numpy** is added for resampling and CSCV.
- **Equity curves** are stored per run under `runs/equity/`, because PBO needs them.

## Consequences
A G6 pass says the result is unlikely to be luck on that data. It does not cover G3 to G5, so the report says so. With fewer than four trials the verdict can be NOT_ASSESSED but never PASS.
