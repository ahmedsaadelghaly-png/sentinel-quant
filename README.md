# Sentinel Quant

Research-first automated trading for spot crypto and US stocks, with a separate binary-options track.

**Principle:** prove the edge before risking capital. The bot trades automatically within user-defined daily risk limits, starts on simulation/testnet, and only reaches real money after strategies pass every validation gate and the user explicitly approves.

## Status
MVP-8 and the M3 statistics are code complete: an automated paper bot with a local control panel. Nothing here has proven an edge, and live trading is not available. See `docs/PROGRESS.md`.

## Quick start
```bash
uv sync --locked --extra dev
source .venv/bin/activate
cp .env.example .env            # fill in testnet keys later; never commit .env
sentinel-quant check-config     # validates configs/default.yaml
pytest
```

## Market data
Public mainnet data, no API keys needed. Symbols, timeframe and start date come from the config.
```bash
sentinel-quant data download                 # download or extend history under data/
sentinel-quant data download --since 2024-01-01 --until 2024-02-01
sentinel-quant data download --full          # re-fetch the range to detect restated bars
sentinel-quant data report                   # verify checksums, print the quality report
sentinel-quant data report --strict          # also fail on gaps and zero-volume bars
```

## Backtest, bot and control panel
```bash
sentinel-quant backtest                      # run the configured strategy; logged in the registry
sentinel-quant validate                      # gates G2 to G6; the holdout stays unseen
sentinel-quant evaluate 1                    # statistical report and G6 verdict for a registry run
sentinel-quant run                           # start the bot in the configured mode (sim or paper)
sentinel-quant gui                           # control panel at http://127.0.0.1:8765
sentinel-quant kill-switch on                # refuse every order (also: off, status)
sentinel-quant report 2026-11-05             # daily report for a UTC date
```
See `docs/runbooks/operating.md`.

## Key documents
- `MASTER_PLAN.md` — architecture, milestones, gates, daily risk controls
- `RESEARCH_PROMPT.md` — strategy research program
- `CLAUDE.md` — rules for AI-assisted sessions
- `docs/research/trading_strategies/` — strategy catalog (205 entries)
- `docs/decisions/` — architecture decision records

## Layout
```
sentinel_quant/
  config/  data/  features/  strategies/  filters/  backtest/  evaluation/
  registry/  selection/  risk/  execution/  ledger/  ops/  gui/
  binary/   # Track B: own strategies, backtest, evaluation, risk, execution
configs/  tests/  docs/  scripts/
```
