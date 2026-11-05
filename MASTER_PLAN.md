# Sentinel Quant — Master Plan (v2)

> Single source of truth for building **Sentinel Quant** — a new project started from scratch (successor of the QuickEdge experiments).
> GUI reference design: the "Sentinel Quant — Trading Terminal UI" canvas (Command Center, Daily Risk Controls, Strategy Lab, Binary Options Terminal).
> Companion documents: `RESEARCH_PROMPT.md` (former QUICKEDGE_RESEARCH_PROMPT_v2) (research program), `docs/research/trading_strategies/` (research outputs).
> Place this file at the repo root. Claude Code sessions should read it together with `CLAUDE.md` and the current milestone's section.

---

## 1. Mission

Build a research-first trading platform that **proves a statistically defensible edge after realistic costs before risking capital**, for:

- **Track M (Main):** US stocks and spot crypto.
- **Track B (Binary):** binary options, as a fully separate instrument with its own pipeline.

Success is not "the highest backtest profit". Success is: strategies that survive out-of-sample, walk-forward and paper trading; a risk engine that cannot be bypassed; and an AI layer that chooses well **and is allowed to say NO TRADE**.

---

## 1.1 Top Priority: Automated Trading (Automation-First Delivery)

The user's #1 goal is a system that **buys and sells automatically within a daily risk budget and daily targets set by the user**. The plan is therefore delivered automation-first: build a thin but complete automated loop early (on paper/testnet), then improve strategies inside it.

**MVP — "Automated Paper Bot" (built before the full M1–M7 scope):**

| Step | Minimal version | Taken from |
|---|---|---|
| MVP-1 | New repo `sentinel-quant` + git + config + secrets + logging | M0 |
| MVP-2 | Crypto spot data only (1–3 liquid pairs, 1 exchange via ccxt), live candles + history | M1 (lite) |
| MVP-3 | Event-driven backtester with fees/slippage, golden tests | M3 (lite) |
| MVP-4 | **Daily risk controller** (§1.2) + kill switch | M4 |
| MVP-5 | One simple, well-documented strategy (e.g. time-series momentum or Donchian breakout) — a placeholder to exercise the loop, not a profit claim | M5 (lite) |
| MVP-6 | **Trading daemon**: scheduler → data → signal → risk check → order → fill → ledger → reconciliation, running 24/7 on **exchange testnet / paper** | M8 (early) |
| MVP-7 | Telegram/e-mail alerts + daily report (P&L, risk usage, trades, why each trade was taken or refused) | O |
| MVP-8 | Web control panel following the GUI reference design: Command Center + Daily Risk Controls (start/stop, kill switch, limits, positions, today's P&L, decision log) | M9 (lite) |

**MVP exit:** the bot runs unattended on paper for 2+ weeks, respects every daily limit in every test, recovers from restarts and disconnects, and reconciles with the exchange daily. After that, M1–M7 expand data, markets (US stocks), strategies and the AI layer **inside the same loop**. Real money still requires the §6 gates and explicit approval.

## 1.2 Daily Risk & Target Controls (user-configurable)

```yaml
daily_controls:
  risk_per_trade_pct: 0.5        # % of equity risked per trade (stop distance × size)
  max_daily_loss_pct: 2.0        # hard stop: flatten/close and stop trading for the day
  max_daily_trades: 10
  max_open_positions: 3
  max_total_exposure_pct: 50
  max_consecutive_losses: 4      # pause for the day
  daily_profit_lock_pct: 3.0     # OPTIONAL: when reached, stop opening new trades and trail/close existing ones
  trading_window_utc: ["00:00", "23:59"]
  reset_time_utc: "00:00"
```

Design rules:
- **The daily profit target is a stopping rule, not a goal the system chases.** When it is reached, the bot stops opening new positions (and may tighten stops). It must **never** increase size, trade more, or loosen rules to reach a target — that converts a target into a risk-increasing loop.
- Daily loss limit is enforced by the risk engine **before** every order (projected worst-case loss including open positions), not only after losses happen.
- Limits are checked against equity at the daily reset time; changes to limits take effect next day unless they make limits stricter (stricter = immediate).
- Every limit hit is logged, alerted, and shown in the daily report.
- Expect many days with no trades or small losses: there is no strategy that produces a fixed daily return; the system's job is to trade only when a validated strategy gives a signal and the risk budget allows it.

---

## 2. Non-Negotiable Principles

1. **Prove the edge before risking capital.** No strategy reaches real money without passing every gate in §6.
2. **No automatic live trading.** Live mode is off by default; enabling it requires the user's explicit approval per strategy, per platform.
3. **Risk engine has veto power** over every order, in every track. It runs independently of strategies and of the AI layer.
4. **Track separation.** Track M and Track B never share statistics, backtests, risk limits, paper accounts or reports.
5. **Official APIs only.** No reverse-engineered APIs, scraping, or browser automation for execution.
6. **Reproducibility.** Every result is reproducible from versioned code + versioned data + recorded config + recorded random seeds.
7. **Every experiment is counted.** All variants tried are logged, so multiple-testing corrections (deflated Sharpe, PBO) are honest.
8. **Sharia awareness.** Every strategy/instrument carries a Sharia status; no rulings are issued by the system; uncertain cases are flagged for scholar review.
9. **Risk-adjusted objective.** Optimize Sharpe/Calmar or return under a drawdown cap — never raw profit.
10. **Security by default.** Trade-only API keys, no withdrawal permission, IP allow-listing, secrets outside the repo.
11. **Independence from Aqel Markets and legacy QuickEdge code.** No shared code, data stores or architecture.

---

## 3. Target Architecture

```
                         ┌────────────────────────────────────────────┐
                         │                GUI (Terminal)              │
                         │  Research · Backtests · Paper · Risk ·     │
                         │  Main Terminal · Binary Options Terminal   │
                         └───────────────▲────────────────────────────┘
                                         │ API (read models, commands)
┌──────────────┐   ┌──────────────┐   ┌──┴───────────┐   ┌─────────────────┐
│  Data Layer  │──▶│ Feature Lib  │──▶│  Strategies  │──▶│ Signal / AI      │
│ ingest,clean │   │ cached,      │   │ + Filters    │   │ Selection Layer  │
│ PIT, storage │   │ versioned    │   │ (plugins)    │   │ (NO TRADE ok)    │
└──────┬───────┘   └──────────────┘   └──────────────┘   └────────┬────────┘
       │                                                          │
       │            ┌──────────────────────────────┐              ▼
       └───────────▶│ Backtest Engine (event-driven│      ┌───────────────┐
                    │  + vectorized screener)      │      │  RISK ENGINE  │◀── Kill switch
                    └──────────────┬───────────────┘      │  (veto)       │    (independent)
                                   ▼                      └───────┬───────┘
                    ┌──────────────────────────────┐              ▼
                    │ Evaluation & Experiment      │      ┌───────────────┐
                    │ Registry (all trials logged) │      │ Execution     │
                    └──────────────────────────────┘      │ Adapters      │
                                                          │ sim · paper · │
                                                          │ ccxt · IBKR/  │
                                                          │ Alpaca · BO   │
                                                          └───────┬───────┘
                                                                  ▼
                                                        Ledger & Reconciliation
```

Track B reuses the Data Layer and Feature Library **by import only**; it has its own Strategy library, Backtest engine, Evaluation, Risk engine, Paper account, Execution adapter and GUI terminal.

### 3.1 Module responsibilities

| Module | Responsibility | Key rules |
|---|---|---|
| `data` | Ingest, clean, store OHLCV, trades, L2 (later), fundamentals, corporate actions, calendars | Point-in-time; survivorship-free universes; adjusted + raw prices; data versioning with checksums |
| `features` | Indicators and transforms (FEATURE entities) | Pure functions; no look-ahead (tested); cached by (dataset version, params) |
| `strategies` | One plugin per STRATEGY | Standard interface (§3.2); no sizing inside strategies |
| `filters` | Composable gates (FILTER entities, SMC concepts, sessions, regimes) | Must be A/B testable on a baseline |
| `backtest` | Event-driven reference engine + fast vectorized screener | Spread, commission, slippage, partial fills, borrow fees, halts, delistings, venue fees |
| `evaluation` | Metrics and statistical tests | Net and gross; DSR, PBO, bootstrap CIs; per-regime breakdown |
| `registry` | Experiment tracking | Every run: code hash, data version, config, seed, metrics, trial count |
| `selection` | Strategy weighting / meta-model (Phase 21 design) | Must beat equal-weight baseline OOS; logs reasons for every decision |
| `risk` | Pre-trade and portfolio limits, kill switch | Separate process/flag; cannot be disabled by strategy or AI code |
| `execution` | Broker/exchange adapters | Common interface; sim and paper adapters first; idempotent order IDs |
| `ledger` | Orders, fills, positions, cash; reconciliation with broker | Source of truth for P&L; daily reconciliation report |
| `binary` | Entire Track B (strategies, backtest, eval, risk, adapter) | Never imports `risk`, `evaluation` or `ledger` of Track M |
| `gui` | Terminal and dashboards | Read-only by default; trading actions behind confirmations |
| `ops` | Config, secrets, logging, monitoring, alerts | Structured logs; alerts on limit breaches, disconnects, reconciliation diffs |

### 3.2 Core interfaces (conceptual)

```python
class Strategy(Protocol):
    metadata: StrategyMetadata  # id, entity refs, markets, timeframe, sharia_status, evidence

    def required_data(self) -> DataSpec: ...
    def compute_features(self, data) -> FeatureFrame: ...
    def generate_signals(self, features) -> SignalFrame: ...  # direction, strength, timestamp
    def entry(self, signal, market) -> EntrySpec: ...
    def stop_loss(self, position, market) -> Price | None: ...
    def take_profit(self, position, market) -> Price | None: ...
    def exit(self, position, market) -> bool: ...


class RiskEngine(Protocol):
    def size(self, signal, portfolio) -> Quantity: ...
    def check(self, order, portfolio) -> Approved | Rejected(reason): ...
    def kill_switch_engaged(self) -> bool: ...


class ExecutionAdapter(Protocol):
    def balances(self) -> Balances: ...
    def positions(self) -> list[Position]: ...
    def place(self, order: Order) -> OrderAck: ...  # idempotent client_order_id
    def cancel(self, order_id) -> CancelAck: ...
    def fills(self, since) -> list[Fill]: ...


class BinaryAdapter(Protocol):  # Track B only
    def quote(self, asset, direction, expiry, stake) -> BinaryQuote: ...  # payout at entry
    def buy(self, quote) -> ContractAck: ...
    def status(self, contract_id) -> ContractStatus: ...
    def settlement(self, contract_id) -> Settlement: ...
```

### 3.3 Suggested stack (validate in Milestone 0)

- Python 3.12, `uv` or pip-tools for locked dependencies.
- Polars (or pandas) for data, Parquet files + DuckDB for queries.
- Pydantic for configs and schemas; `pytest` + `hypothesis` for tests (including look-ahead tests).
- `ccxt` for crypto exchanges; `ib_async` (IBKR) and/or Alpaca SDK for US stocks.
- SQLite/Postgres for registry and ledger.
- GUI: FastAPI backend + a web frontend (or Streamlit for an early internal version).
- Scheduling: simple service with APScheduler or systemd timers before anything heavier.

### 3.4 Repository layout

```
sentinel_quant/
  data/  features/  strategies/  filters/  backtest/  evaluation/
  registry/  selection/  risk/  execution/  ledger/  ops/
  binary/            # Track B: strategies/ backtest/ evaluation/ risk/ execution/
  gui/
configs/             # versioned, no secrets
tests/               # unit, look-ahead, integration, golden backtests
scripts/
docs/
  research/trading_strategies/        # research program outputs
  research/trading_strategies/binary_options/
  architecture/  decisions/ (ADRs)  runbooks/
MASTER_PLAN.md
RESEARCH_PROMPT.md
CLAUDE.md
```

---

## 4. Workstreams

| WS | Name | Content |
|---|---|---|
| R | Research | Research program phases 0–21 + BO-0…BO-5 |
| E | Engineering core | Data, features, backtest, evaluation, registry |
| S | Strategies & validation | Implement and validate strategies in research order |
| K | Risk & portfolio | Risk engine, kill switch, portfolio construction |
| X | Execution | Adapters, paper trading, ledger, reconciliation |
| A | AI selection layer | Meta-model / weighting with NO TRADE |
| B | Binary track | Everything Track B |
| G | GUI | Terminals and dashboards |
| O | Ops & security | Secrets, monitoring, alerts, backups, runbooks |

Research (R) runs in parallel with Engineering (E). Strategy testing starts as soon as the first research category and the backtest engine are both ready.

---

## 5. Milestones

Each milestone has an exit gate. Do not start a milestone whose prerequisites are not met. One milestone (or one sub-step) per Claude Code session; update `docs/PROGRESS.md` at the end of each session.

### M0 — Foundation (new repository, from scratch)
- Create a new repository `sentinel-quant` with git from the first commit. The old QuickEdge repos stay untouched as read-only references; nothing is copied without review.
- Optional: skim old QuickEdge code for ideas only (`docs/architecture/LEGACY_NOTES.md`), no code import.
- Set up: dependency locking, lint/format, `pytest`, CI (GitHub Actions or local pre-commit), config schema, secrets handling (`.env` excluded from git), structured logging.
- Write/refresh `CLAUDE.md` with the §2 principles and session rules.
**Exit:** clean repo, CI green, first ADR (stack choice) merged.

### M1 — Data layer
- Crypto first (cheaper, 24/7, free trade data): daily + intraday OHLCV for a fixed universe from at least two exchanges via `ccxt`; store as versioned Parquet.
- US stocks: daily adjusted + raw OHLCV, corporate actions, **survivorship-free universe** (include delisted). Evaluate providers in research Deliverable 8.
- Data quality checks: gaps, duplicates, outliers, timezone, split adjustments; quality report per dataset version.
- Trading calendars and session definitions (Asia/London/NY; US RTH/ETH).
**Exit:** reproducible dataset build; quality report clean; dataset versions referenced by ID.

### M2 — Feature library
- Implement FEATURE entities needed by the first strategies (MA, EMA, ATR, RSI, Donchian, VWAP, z-score, swing points with explicit confirmation lag, FVG, session features).
- **Look-ahead test harness:** for every feature, computing on data truncated at t must equal the full-history value at t.
**Exit:** all features pass look-ahead tests; cached and versioned.

### M3 — Backtest engine & evaluation
- Event-driven engine (reference) + vectorized screener; both must agree on golden tests.
- Cost models per venue: commission, spread, slippage (fixed + volatility-scaled), borrow fees, exchange fees.
- Golden tests: buy-and-hold, random-entry strategy (should show ≈ zero edge minus costs), hand-computed toy cases.
- Evaluation: CAGR, Sharpe, Sortino, Calmar, max DD, profit factor, expectancy, win rate, exposure, turnover, holding time, tail metrics; **deflated Sharpe, PBO, bootstrap CIs**, net vs gross.
- Experiment registry: every run logged with code hash, data version, config, seed, trial count.
**Exit:** golden tests pass; one full report generated end-to-end from the registry.

### M4 — Risk engine & simulated execution
- Risk engine: risk per trade, daily loss limit, max exposure (gross/net/per asset/per sector), max drawdown, correlation caps, **independent kill switch** (file/flag/process the engine checks before every order).
- Sim adapter + ledger + reconciliation (sim vs ledger).
- Backtests route all orders through the same risk engine used later in paper/live.
**Exit:** risk tests (limit breaches always rejected; kill switch blocks everything) pass.

### M5 — Baseline strategies (Track M)
- Implement and validate 3 baselines with strong literature support, chosen from research outputs (e.g. time-series momentum, Donchian breakout, cross-sectional/dual momentum).
- Full validation protocol (§6) on crypto first, then US stocks.
**Exit:** baseline reports published; these become the benchmarks every later strategy must beat or diversify.

### M6 — Strategy factory (iterative)
- Work through the research ranking (Phase 19 output) in order: implement → validate → record → accept/reject.
- Filters (SMC/ICT concepts, sessions, regimes) tested only as **A/B add-ons** to an accepted baseline.
- Rejected strategies stay in the registry with their reports (they count as trials).
**Exit (rolling):** a set of accepted strategies with low pairwise correlation.

### M7 — Portfolio & AI selection layer
- Equal-weight portfolio of accepted strategies (mandatory baseline).
- Then: inverse-vol/risk parity → rule-based regime switching → statistical regimes → supervised meta-model (per research Phase 21).
- Every decision logged with features and reasons; output includes cash / NO TRADE.
**Exit:** selection layer adopted only if it beats equal weight out-of-sample net of costs and turnover; otherwise equal weight is used.

### M8 — Paper trading (Track M)
- Adapters: `ccxt` testnet/paper, then Alpaca paper and/or IBKR paper (whichever is available to the user).
- Run continuously ≥ 3 months or a pre-defined minimum trade count per strategy.
- Daily reconciliation; drift report: paper vs backtest (fills, slippage, signal agreement).
**Exit:** paper performance within pre-registered tolerance of backtest; no unexplained reconciliation differences.

### M9 — GUI
- Internal dashboards first: data status, research catalog browser, experiment registry, backtest reports, risk-limit usage, paper positions.
- Main Terminal: positions, orders, signals with reasons, risk panel, kill switch.
- Binary Options Terminal is built in Track B (B5), visually distinct.
**Exit:** user can operate paper trading and inspect every decision from the GUI.

### M10 — Live readiness (Track M)
- Security review (you are the right person for this): key scopes, IP allow-list, secrets storage, dependency audit, threat model for the execution path.
- Runbooks: start/stop, kill switch, broker outage, partial fills, reconciliation failures.
- Small live allocation, cash account (Sharia/margin considerations), per-strategy user approval.
**Exit:** written approval; live starts with minimum size and hard daily loss cap.

---

## 6. Validation Gates (every Track M strategy)

| Gate | Requirement |
|---|---|
| G1 Definition | Deterministic rules, data spec, Sharia status, evidence level from research |
| G2 In-sample | Positive net expectancy with realistic costs; parameter count and trials logged |
| G3 Out-of-sample | Held-out period never touched during development; edge persists |
| G4 Walk-forward | Rolling re-fit; stable performance across windows |
| G5 Robustness | Parameter neighborhood stable; Monte Carlo / bootstrap; cost stress (×2 costs); regime breakdown |
| G6 Statistics | Deflated Sharpe > threshold; PBO below threshold (thresholds fixed in M3 before testing) |
| G7 Paper | Paper results within tolerance of backtest over the minimum period |
| G8 Approval | User's explicit approval for live |

---

## 7. Track B — Binary Options (separate pipeline)

| Step | Content | Exit gate |
|---|---|---|
| **B0 Platform due diligence** | Research prompt §15.2: licence on regulator register, Egypt availability, regulator warnings, official API, ToS on automation, withdrawal terms, settlement feed | User reviews verdicts. **If no platform is ELIGIBLE, Track B continues as research + simulation only.** |
| B1 Research & library | BO strategy catalog per expiry bucket; P(win) vs break-even `1/(1+p)` | Catalog reviewed |
| B2 Backtest & evaluation | Separate engine; platform settlement rules; win-rate CIs, EV per $1, max consecutive losses, per expiry/regime; required sample size | Only strategies with OOS CI lower bound above break-even become candidates |
| B3 Risk engine | Max stake, daily exposure, daily loss, max consecutive losses, max simultaneous contracts, min payout, allowed expiries, independent emergency stop; martingale prohibited | Risk tests pass |
| B4 Execution & paper | Official API adapter (ELIGIBLE platforms only), demo account, reconciliation of every settlement | Paper consistent with backtest |
| B5 Terminal & AI | Binary Options Terminal with break-even rate shown; separate AI evaluator that defaults to NO TRADE | User can operate demo from the GUI |
| B6 Live decision | All research-prompt §15.10 conditions, including Sharia review status | Explicit written approval |

---

## 8. Research ↔ Engineering Timeline

```
Research:   P0-1 ✅ │ P2 evidence │ P3…P16 profiles (category by category) │ P17-19 │ P20 │ P21
                     │ BO-0 ───────│ BO-1…
Engineering: M0 │ M1 │ M2 │ M3 │ M4 │ M5 ─────── M6 (consumes each finished category) ── M7 │ M8 │ M9 │ M10
Binary:                         B1 │ B2 │ B3 (needs M1–M3 data/features) │ B4 │ B5 │ B6
```

Rough effort for one person part-time with Claude Code (adjust after M0): M0–M4 ≈ 6–10 weeks; M5–M6 continuous; M8 paper ≥ 3 months by design. Track B depends heavily on the B0 verdict.

---

## 9. Working Method with Claude Code

1. Each session: read `CLAUDE.md`, `MASTER_PLAN.md`'s current milestone, and `docs/PROGRESS.md`; do one milestone step; run tests; update PROGRESS; propose a commit (do not push without approval).
2. Every non-trivial design choice → short ADR in `docs/decisions/`.
3. Definition of done for any code: tests (including look-ahead tests where relevant), type checks, docs updated, registry entry for any experiment.
4. Research sessions follow `RESEARCH_PROMPT.md` (former QUICKEDGE_RESEARCH_PROMPT_v2); engineering sessions follow this plan. Never mix both in one session.
5. Review points for the user: end of every milestone, every BO gate, and every strategy acceptance.

---

## 10. Key Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Backtest overfitting | Trial counting, DSR/PBO, untouched OOS, walk-forward, paper gate |
| Look-ahead bias | Truncation tests on every feature; event-driven reference engine |
| Survivorship bias | Survivorship-free stock universes; delisted crypto assets kept |
| Costs underestimated | Venue-specific cost models; ×2 cost stress test; paper drift report |
| Data vendor changes | Versioned local storage; provider abstraction |
| Broker/platform access from Egypt | Verify early (M1/M8 prep, B0); adapters keep the system broker-agnostic |
| Regulatory exposure (crypto, binary options) | Primary-source checks; research-only mode when not eligible |
| Key leakage / account compromise | Trade-only keys, IP allow-list, secret manager, no secrets in repo |
| Runaway automation | Independent kill switch, daily loss caps, live off by default |
| Sharia non-compliance | Per-entity status; cash account; flagged instruments excluded from rankings until reviewed |
| Scope creep | Milestone gates; one workstream per session |

---

## 11. Immediate Next Steps

1. Create the new `sentinel-quant` repository (git from day one).
2. Add `MASTER_PLAN.md` (this file), `RESEARCH_PROMPT.md`, and the Phase 0–1 research outputs under `docs/research/trading_strategies/`.
3. Run **MVP-1** (scaffold, tooling, config schema incl. `daily_controls`, secrets, logging) in Claude Code.
4. Build **MVP-2 → MVP-8** (automated paper bot) — this is the priority path.
5. Research Phase 2 and BO-0 continue in parallel, in separate sessions, feeding strategies into the running loop.
