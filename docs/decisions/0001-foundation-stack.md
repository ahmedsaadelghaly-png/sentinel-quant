# ADR 0001 — Foundation stack

- Status: accepted
- Date: 2026-11-06

## Context
Sentinel Quant starts from scratch (successor to the QuickEdge experiments). Priority is an automated paper-trading bot (MASTER_PLAN §1.1) with strict daily risk controls, built on foundations that keep research reproducible and secrets safe.

## Decision
- **Python 3.12+**, packaged with `pyproject.toml` (hatchling), environments via **uv**.
- **Pydantic v2** for config schema: frozen, `extra="forbid"`, cross-field validation. Unsafe combinations (live without approval, paper on mainnet, martingale, per-trade risk above daily loss) fail at startup.
- **pydantic-settings** for secrets, from `SQ_*` env vars / git-ignored `.env`. Config files containing key/secret/token fields are rejected.
- **structlog** JSON logs with a redaction processor that removes known secret values.
- Quality gates: **ruff** (lint + format, incl. bandit rules), **mypy --strict**, **pytest**, **detect-secrets** pre-commit, GitHub Actions CI.
- Default mode is `sim`; Track B (binary) disabled by default.

## Planned (separate ADRs when introduced)
Polars + Parquet + DuckDB (data), ccxt (crypto), FastAPI + web frontend (GUI), SQLite registry/ledger.

## Consequences
Strict typing and validation slow the first steps slightly but prevent silent misconfiguration in a system that places orders.
