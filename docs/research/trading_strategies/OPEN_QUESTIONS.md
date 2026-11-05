# Open Questions

## Repository
- **Q1.** Repo has no `.git` at root. Initialize git before the research grows, so every phase is a reviewable diff?
- **Q2.** Is there an existing Sharia policy inside `CLAUDE.md`, `README.md`, `config.yaml` or `configs/`? Filenames don't mention it; contents not yet checked. If none exists, §8 framework is used provisionally.

## Classification decisions for the user
- **D1. Failed Breakout (C) vs Liquidity Sweep (D):** kept as two STRATEGY entries because level definitions differ (generic swing high vs SMC liquidity pools), but operationally near-identical. Alternative: merge into one strategy with level-source as a parameter.
- **D2. MSS vs CHOCH:** merged into one FEATURE. Split if you use a specific source that defines them differently.
- **D3. Candlestick and chart patterns:** individual patterns classified as FEATURE (detectors); only the umbrella "Candlestick Pattern Trading" is a STRATEGY. Each pattern becomes a test variant of it.
- **D4. Macro items (rates, inflation, GDP, central bank, yield curve):** classified as FILTERs on stocks/crypto, since trading them directly needs bonds/futures (out of scope).

## Unverified
(none yet — Phase 2 starts the bibliography)
