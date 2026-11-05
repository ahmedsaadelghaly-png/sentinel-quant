# Sentinel Quant

Research-first automated trading for spot crypto and US stocks, with a separate binary-options track.

**Principle:** prove the edge before risking capital. The bot trades automatically within user-defined daily risk limits, starts on simulation/testnet, and only reaches real money after strategies pass every validation gate and the user explicitly approves.

## Status
MVP-1 (foundation) — see `docs/PROGRESS.md`.

## Quick start
```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
cp .env.example .env            # fill in testnet keys later; never commit .env
sentinel-quant check-config     # validates configs/default.yaml
pytest
```

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
