# CLAUDE.md — rules for every session in this repo

Read `MASTER_PLAN.md` (current milestone) and `docs/PROGRESS.md` before doing anything.

## Non-negotiables
1. Prove the edge before risking capital. No strategy reaches real money without passing gates G1–G8 (MASTER_PLAN §6).
2. Live trading is OFF by default. Never set `mode: live` or `live_trading_approved: true`; only the user does that.
3. The risk engine has veto power over every order. Never add code paths that bypass it or the kill switch.
4. Track M (stocks/crypto) and Track B (binary options) never share stats, backtests, risk limits, accounts or reports. `sentinel_quant/binary/` must not import Track M `risk`, `evaluation` or `ledger`.
5. Official APIs only. No scraping, reverse-engineered APIs or browser automation for execution.
6. Every experiment/variant is logged in the registry (needed for deflated Sharpe / PBO).
7. The daily profit lock is a stopping rule. Never increase size or trading frequency to reach a target. No martingale.
8. Secrets only via `SQ_*` environment variables. Never write keys into code, configs, logs, tests or commits.
9. No look-ahead: every feature gets a truncation test.
10. Independent from Aqel Markets and the legacy QuickEdge repos (ideas only, no code import).

## Session workflow
- One milestone step per session. Research sessions follow `RESEARCH_PROMPT.md`; engineering sessions follow `MASTER_PLAN.md`. Never both in one session.
- Before finishing: `ruff check .`, `mypy sentinel_quant`, `pytest` must pass. Update `docs/PROGRESS.md`. Propose a commit; do not push without approval.
- Non-trivial design choices get an ADR in `docs/decisions/`.

## Commands
```bash
uv venv && uv pip install -e ".[dev]"
sentinel-quant check-config --config configs/default.yaml
ruff check . && ruff format --check . && mypy sentinel_quant && pytest
```
