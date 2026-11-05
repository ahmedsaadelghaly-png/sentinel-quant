# Sentinel Quant — Trading Strategies Research Program (Prompt v2)

> Run this inside the QuickEdge repository with Claude Code.
> This is a **multi-session** research program. Each session executes ONE phase (or one category batch) and stops.
> Start every session by reading `docs/research/trading_strategies/PROGRESS.md` and continuing from the next open item.

---

## 0. Role and Goal

Act as a senior quantitative researcher and trading-systems architect.

Goal: build an auditable, research-backed catalog of trading methodologies and a blueprint for testing them in QuickEdge.

The question for every entry is not "is this popular?" or "does this look profitable?" but:
**Is there a measurable, repeatable edge that survives realistic costs, and can QuickEdge test it with data it can actually get?**

---

## 1. Project Context

- QuickEdge: independent research, backtesting and paper-trading project.
- Core scope: **US stocks** and **spot crypto**, small capital, automated analysis, backtesting, paper trading.
- Live execution: out of scope for this work. Any future live trading requires explicit user approval.
- Sharia awareness is a project requirement (see §8).
- **Binary options** are an additional, fully separate track (§15) with their own research, data, backtests, risk engine, paper trading and reporting.
- QuickEdge is completely separate from Aqel Markets. Do not read, reuse, modify or reference Aqel Markets code.

---

## 2. Hard Rules (apply in every session)

### Repository safety
1. Run `pwd`, `git status`, and list the top-level tree. Confirm this is the QuickEdge repo. If it is not, write outputs to `./quickedge_research_output/` and touch nothing else.
2. Write only inside `docs/research/trading_strategies/`. Never overwrite a file you did not create in this program; if a name collides, stop and report.
3. Do not modify application code or config, install dependencies, connect to brokers, place trades, or commit/push.

### Source integrity (most important)
4. **Never cite a source you have not opened in this session or a previous one.** Every reference must be fetched (web fetch / search result) and recorded in `BIBLIOGRAPHY.md` with: ID (e.g. `REF-042`), authors, title, year, venue, URL or DOI, type (peer-reviewed / working paper / official doc / book / practitioner), date accessed.
5. Profiles cite references by ID only (`[REF-042]`). No free-text citations.
6. If you recall a paper but cannot verify it, write `[UNVERIFIED: author, year, topic]` and add it to `OPEN_QUESTIONS.md`. Do not invent DOIs, page numbers, sample periods or results.
7. Never report win rates, Sharpe ratios, returns or profit factors unless they come from a cited source, and always state that source's sample period, market, and whether costs were included. Otherwise write: **"Performance not independently established."**
8. YouTube, influencers, courses, Discord/Telegram groups, and strategy vendors are never evidence. They may be cited only as the *origin of a claim* (type = practitioner).
9. Causal stories (e.g. "institutions hunt retail stops") are hypotheses unless a cited source tests them. Label them `Hypothesis (untested)`.

### Context management
10. Keep `PROGRESS.md` updated after every category: what was done, counts, next step. A new session must be able to resume from it alone.
11. If you are running low on context, finish the current entry, update `PROGRESS.md`, and stop. Do not compress remaining entries into thin placeholders.

---

## 3. Taxonomy — classify BEFORE profiling

The original list mixes different kinds of things. Assign every entry exactly one **Entity Type**:

| Type | Meaning | Examples |
|---|---|---|
| `STRATEGY` | Self-contained rule set producing entries and exits; independently backtestable | Donchian breakout, time-series momentum, pairs trading |
| `FILTER` | Context/condition that gates another strategy; not tradable alone | Kill zones, daily bias, premium/discount, regime filter |
| `FEATURE` | Indicator or transformation used as input | RSI, ATR, VWAP, z-score, POC |
| `MODEL` | Statistical/ML method that turns features into forecasts | Logistic regression, HMM, XGBoost, LSTM, Kalman filter |
| `FRAMEWORK` | Discretionary analytical school; must be operationalized before testing | Wyckoff, Elliott Wave, ICT/SMC, Market Profile, Gann |
| `EXECUTION` | How to fill orders, not whether to trade | VWAP/TWAP/POV, smart order routing, iceberg |
| `RISK` | Sizing, stops, allocation, portfolio controls | Kelly, volatility targeting, risk parity, trailing stop |

Also assign a **Scope Flag**:
- `CORE` — feasible on US stocks or spot crypto with OHLCV/fundamental data a small project can obtain.
- `CORE-DATA` — in scope but needs tick, Level 2, or paid feeds.
- `OUT-OF-SCOPE` — needs options, futures, perpetuals, leverage, colocation/HFT infrastructure, or large capital.

### Canonical-home rule (deduplication)
Each concept gets one canonical entry; other categories cross-reference it. Pre-resolved duplicates in the input list:

| Concept | Canonical home | Cross-ref from |
|---|---|---|
| Pairs trading, cointegration | B (Mean Reversion) | F, I |
| Statistical arbitrage | F (Quant) | B, I |
| Opening Range Breakout | K (Time-based) | C |
| VWAP (feature) / VWAP reversion (strategy) / VWAP execution | E / B / L — three separate entities | — |
| Cross-sectional momentum = momentum factor | A | F |
| Insider transactions | G | J |
| RSI divergence vs. SMT divergence | B / D — distinct | — |
| Fibonacci retracement + OTE | C (feature) | D |

Flag any further duplicates you discover and resolve them the same way.

---

## 4. Input Inventory (minimum; add legitimate methods you discover)

**A. Trend/Momentum:** MA crossover, EMA trend, SMA 50/200, MACD, RSI momentum, breakout, Donchian, Turtle, time-series momentum, cross-sectional momentum, relative strength, ROC, ADX trend, Parabolic SAR, Supertrend, momentum rotation.
**B. Mean Reversion:** RSI OB/OS, Bollinger, MA reversion, VWAP reversion, z-score, statistical mean reversion, pairs, cointegration, Ornstein-Uhlenbeck, RSI divergence, CCI, Keltner, adaptive mean reversion, short-term reversal.
**C. Price Action / S&R:** S/R, supply & demand zones, break & retest, horizontal levels, trendlines, channels, candlestick patterns (pin bar, engulfing, inside/outside bar), rejection, failed breakout, swing high/low, pivot points, Fibonacci retracement/extension, chart patterns (H&S, double top/bottom, flags, pennants, triangles, wedges).
**D. SMC/ICT:** liquidity sweep, equal highs/lows, buy/sell-side liquidity, FVG, inverse FVG, order/breaker/mitigation blocks, BOS, MSS, CHOCH, displacement, premium/discount, OTE, SMT divergence, Judas swing, Power of Three/AMD, kill zones, daily bias, IPDA, liquidity pools, inducement, balanced price range.
**E. Volume/Order Flow:** volume profile, fixed-range VP, POC, VAH/VAL, VWAP, anchored VWAP, volume breakout, OBV, CVD, footprint, order book imbalance, absorption, iceberg detection, delta divergence, time & sales, VSA, MFI, A/D line.
**F. Quant/Statistical:** stat arb, factor & multi-factor models, value, quality, low-volatility, residual momentum, Kalman filter, HMM, regime switching, Bayesian models, Monte Carlo, ML signals, RL, time-series forecasting, linear/logistic regression, random forest, gradient boosting/XGBoost, neural nets, LSTM, transformers, PCA strategies, clustering, anomaly detection.
**G. Fundamental/Macro:** value, growth, quality, dividend, earnings surprise/PEAD, earnings momentum, news trading, interest rates, inflation, GDP, central bank, yield curve, sector rotation, event-driven, merger arbitrage, financial-statement analysis, cash-flow strategies, insider activity.
**H. Volatility:** volatility breakout, Bollinger squeeze, ATR-based, expansion/contraction, IV vs RV, skew, straddle, strangle, iron condor, volatility regimes.
**I. Arbitrage:** spatial, triangular, cross-exchange, index, ETF, futures-spot, cash-and-carry, reverse cash-and-carry, funding-rate arbitrage.
**J. Sentiment/Behavioral:** fear & greed, news sentiment, social/Reddit sentiment, Google Trends, contrarian, crowded trades, short interest, analyst revisions, put/call ratio, institutional holdings (13F).
**K. Seasonality/Time:** day-of-week, month-end, January effect, turn-of-the-month, session-based, London open, NY open, ORB, closing auction, commodity seasonality, crypto weekend effect, intraday time-of-day patterns, overnight vs intraday returns.
**L. Execution/Algo:** market making, HFT, scalping algorithms, VWAP/TWAP/POV, SOR, iceberg, liquidity seeking, arrival price.
**M. Risk/Portfolio:** risk parity, equal weight, volatility targeting, Kelly, fixed fractional, dynamic sizing, trailing stop, scale in/out, rebalancing, drawdown control, correlation-based allocation, max risk per trade, exposure limits, risk of ruin.
**N. Other frameworks:** auction market theory, Market Profile, Wyckoff, Elliott Wave, harmonics, Gann, Ichimoku, Renko, Heikin-Ashi, point & figure, fractals, adaptive systems, multi-timeframe analysis, hybrid multi-strategy systems.

---

## 5. Profile Templates (one per Entity Type)

Every entry gets a full profile — but the fields depend on its type. Do not force 34 fields onto Kelly or XGBoost.

### 5.1 Common header (all types)
ID · Name · Aliases · Entity Type · Scope Flag · Canonical category · Cross-refs · Origin (verifiable, with REF) · Core idea (≤3 sentences) · Evidence level (§7) · Sharia status (§8) · QuickEdge priority (§9).

### 5.2 STRATEGY
1. Market hypothesis — *why* the edge should exist (risk premium / behavioral / structural / microstructure), labeled Tested or Hypothesis.
2. Mathematical definition — formulas, parameters, default values with sources.
3. **Operational rules** (deterministic, no discretion): entry, exit, stop, target, re-entry, time stop. Written as pseudocode.
4. Long implementation · Short implementation (note: spot crypto short = margin borrowing; US stock short = locate/borrow fees + SSR).
5. Position sizing — reference RISK entities by ID.
6. Suitable / unsuitable regimes, assets, timeframes.
7. Data: minimum data, granularity, history length, survivorship/point-in-time needs.
8. Costs & capacity: turnover estimate, cost sensitivity (low/med/high), break-even cost per trade if derivable.
9. Evidence: findings by REF with market, period, cost treatment; conflicting findings; post-publication decay if documented.
10. Validation plan: parameters to sweep, number of variants tested (for multiple-testing correction), out-of-sample split, benchmark.
11. Overfitting risks · Common implementation mistakes.
12. Complexity (1–5) · Automation feasibility (1–5) · Compute cost (low/med/high).
13. QuickEdge module notes (§6 interface).
14. Related strategies & complementary filters.

### 5.3 FILTER / FRAMEWORK
- Discretionary definition as practitioners describe it (cite origin).
- **Operationalization:** at least one deterministic, codeable definition (e.g. "FVG = bar[i-1].high < bar[i+1].low"). If multiple are plausible, list them — each is a separate test variant.
- How to test it: as a filter applied to a baseline STRATEGY vs. the same baseline without it (A/B).
- Ambiguity score (1–5): how much results depend on interpretation.
- Hindsight-bias risk: can the concept be labeled only after the fact?

### 5.4 FEATURE
Formula · parameters · look-ahead risk (e.g. pivots/zigzag repaint) · data needed · strategies that use it.

### 5.5 MODEL
Problem framing (classification/regression/regime) · target definition · feature leakage risks · required sample size · validation (purged/embargoed CV) · interpretability · evidence in finance with REFs · known failure modes.

### 5.6 EXECUTION
Objective (minimize impact/slippage vs. benchmark) · when relevant at QuickEdge's capital size (likely rarely) · broker/exchange support.

### 5.7 RISK
Formula · assumptions · failure modes (e.g. Kelly with estimated edge → overbetting; use fractional) · how it plugs into the Risk Engine.

### 5.8 OUT-OF-SCOPE (any type)
Short profile: what it is, why out of scope (data/instrument/capital/infrastructure/Sharia), what would need to change for it to enter scope. Do not spend full research effort here.

---

## 6. QuickEdge Integration Blueprint

Describe a layered architecture (conceptual only — no code changes):

1. **Market Data** — OHLCV, ticks, trades, order book, fundamentals (point-in-time), corporate actions, news, sentiment, economic calendar. Minimum dataset per strategy.
2. **Feature Engineering** — shared, cached, versioned feature library (FEATURE entities).
3. **Strategy Engine** — each STRATEGY is a module implementing:
   `initialize() · validate_data() · calculate_features() · generate_signal() · calculate_entry() · calculate_stop_loss() · calculate_take_profit() · evaluate_exit() · get_metadata()`
   Position sizing is NOT a strategy method; it belongs to the Risk Engine.
4. **Filters** — FILTER entities as composable gates on signals.
5. **Signal Aggregation** — weighted, voting, confidence scoring, correlation-aware weighting, regime-based selection. Require that two strategies with signal/return correlation above a threshold are not counted as independent confirmation.
6. **Risk Engine** — central, with veto power: risk per trade, daily loss limit, max exposure, max drawdown, correlation limits, kill switch.
7. **Backtesting** — event-driven as the reference; vectorized only for fast screening. Model spread, commission, slippage, partial fills, borrow fees, exchange fees per venue, delistings, halts.
8. **Evaluation** — CAGR, Sharpe, Sortino, Calmar, max DD, profit factor, expectancy, win rate, exposure, turnover, holding time, tail risk, **plus**: deflated Sharpe ratio, probability of backtest overfitting, number of trials tested, performance net vs. gross of costs.
9. **Promotion pipeline** — Research → In-sample → Out-of-sample → Walk-forward → Monte Carlo / bootstrap → Paper trading (minimum duration and trade count defined up front) → User approval → (future) live. No automatic promotion.

---

## 7. Evidence Standard

### Evidence levels (assign one per entry, with justification)
- `E1 Research Supported` — multiple independent peer-reviewed studies, out-of-sample or post-publication evidence, survives costs in at least some settings.
- `E2 Promising` — some peer-reviewed or strong working-paper support, but limited markets/periods or cost treatment unclear.
- `E3 Weak/Mixed` — conflicting results, or edge disappears after costs / multiple-testing correction.
- `E4 Untested` — no rigorous study found; practitioner claims only.
- `E5 Not testable as stated` — requires discretion or hindsight; must be operationalized first.

### Mandatory methodological anchors
Find, verify, and cite (do not cite from memory) the literature on:
- Data snooping in technical trading rules (e.g. White's Reality Check, Hansen's SPA test, and studies applying them to technical rules).
- Multiple testing in finance and inflated t-statistic thresholds.
- Deflated Sharpe ratio and probability of backtest overfitting.
- Time-series and cross-sectional momentum; short-term reversal; pairs trading.
- Post-earnings-announcement drift; turn-of-the-month and other calendar anomalies.
- Anomaly decay after publication.
- Stop-loss order clustering and price cascades (FX microstructure literature).
- Transaction costs / market impact for small traders.
- ML in asset pricing; purged cross-validation.
- Crypto-specific studies (momentum, weekend effects, exchange fragmentation) — note how young and thin this literature is.

---

## 8. Sharia Considerations

1. First look in the repo for an existing Sharia policy (search docs for "sharia", "shariah", "halal"). If found, apply it. If not, say so and use the framework below provisionally.
2. Evaluate five layers separately: methodology · underlying asset · instrument · financing/leverage · execution structure.
3. Use authoritative standards where verifiable (e.g. AAOIFI Shari'ah Standards on financial papers/shares, recognized index screening methodologies). Cite them via the bibliography; do not paraphrase from memory.
4. Status per entry: `No methodology concern` · `Depends on instrument` · `Requires scholar review` · `Generally flagged in standards` — with the specific reason (riba via margin, short selling of unowned assets, gharar, derivatives, maysir, etc.).
5. Do not issue rulings. Technical validity ≠ permissibility. Uncertain → `Requires scholar review`.
6. Note explicitly: shorting spot crypto requires margin borrowing; US stock shorting requires borrowing shares and margin.

---

## 9. Scoring and Ranking (reproducible)

Score every STRATEGY on 1–5 for: evidence · data availability · implementation complexity (inverse) · automation feasibility · cost robustness · small-capital suitability · robustness across regimes/markets · Sharia compatibility.

- Publish the weights in `STRATEGY_RANKING_AND_ROADMAP.md` and compute scores with a formula, so the ranking can be recomputed if weights change.
- Sharia `Generally flagged` or Scope `OUT-OF-SCOPE` → excluded from rankings (listed separately).
- Separate rankings: US stocks · spot crypto · small capital · automated · long-term (holding ≥ weeks) · intraday.
- Verify current US small-account rules (e.g. Pattern Day Trader requirements — check whether they have changed recently) and cite the current FINRA/SEC source.

---

## 10. Execution Phases

Each phase ends by updating `PROGRESS.md` and stopping.

| Phase | Work | Outputs |
|---|---|---|
| **0 — Setup** | Repo checks (§2), directory, Sharia policy search, PROGRESS file | `PROGRESS.md`, `OPEN_QUESTIONS.md` |
| **1 — Inventory** | Classify every entry (type, scope, canonical home), assign IDs, dedupe | `TRADING_STRATEGIES_MASTER_CATALOG.md`, `MASTER_STRATEGY_DATABASE.csv` (skeleton) |
| **2 — Evidence base** | Build bibliography from §7 anchors before writing profiles | `BIBLIOGRAPHY.md`, `ACADEMIC_RESEARCH_AND_EVIDENCE.md` (draft) |
| **3…16 — Profiles** | One category per session (A, then B, …, N). Large categories (C, D, F) may be split in two | `profiles/<CATEGORY>_<name>.md`, CSV rows filled |
| **17 — Cross-cutting** | Data requirements, market compatibility, Sharia analysis, backtesting framework | Deliverables 5, 6, 8, 9 |
| **18 — Integration** | Architecture blueprint | Deliverable 3 |
| **19 — Ranking** | Scoring, rankings, roadmap | Deliverable 7 |
| **20 — Summary & QA** | Consistency checks (§12), executive summary, final counts | Deliverable 11 |
| **21 — Selection Layer design** | Design (not build) the strategy-selection meta-model per §14 | `STRATEGY_SELECTION_LAYER.md` |
| **BO-0 — Binary platform due diligence (GATE)** | §15.2. Can run any time; nothing else in §15 starts until the user reviews it | `binary_options/BO_PLATFORM_DUE_DILIGENCE.md` |
| **BO-1…BO-5** | §15.3–15.8, only after the BO-0 gate is passed | see §15.11 |

Profiles live in per-category files under `profiles/`; `STRATEGY_PROFILES.md` is an index linking to them.

---

## 11. Deliverables (all under `docs/research/trading_strategies/`)

1. `TRADING_STRATEGIES_MASTER_CATALOG.md`
2. `STRATEGY_PROFILES.md` (index) + `profiles/*.md`
3. `QUICKEDGE_INTEGRATION_BLUEPRINT.md`
4. `ACADEMIC_RESEARCH_AND_EVIDENCE.md`
5. `MARKET_COMPATIBILITY_MATRIX.md` — US stocks, spot crypto; forex, commodities, futures, options listed as out-of-scope reference only
6. `SHARIA_COMPLIANCE_ANALYSIS.md`
7. `STRATEGY_RANKING_AND_ROADMAP.md`
8. `STRATEGY_DATA_REQUIREMENTS.md` — per dataset: free / low-cost / paid tier, provider examples (verify current offerings and pricing pages), history depth, survivorship and point-in-time support
9. `BACKTESTING_AND_VALIDATION_FRAMEWORK.md`
10. `MASTER_STRATEGY_DATABASE.csv`
11. `QUICKEDGE_RESEARCH_EXECUTIVE_SUMMARY.md`
12. `BIBLIOGRAPHY.md` · `PROGRESS.md` · `OPEN_QUESTIONS.md`

### CSV schema (controlled vocabularies — no free text in enum columns)
`id, name, entity_type{STRATEGY|FILTER|FEATURE|MODEL|FRAMEWORK|EXECUTION|RISK}, scope{CORE|CORE-DATA|OUT-OF-SCOPE}, category{A..N}, subcategory, markets{US_STOCKS;SPOT_CRYPTO;FX;FUTURES;OPTIONS}, style{TREND|REVERSION|BREAKOUT|CARRY|EVENT|STAT_ARB|OTHER}, timeframe{INTRADAY|SWING|POSITION|LONG_TERM}, min_data{OHLCV_DAILY|OHLCV_INTRADAY|TICK|L2|FUNDAMENTAL|ALT}, features, long_support{Y|N}, short_support{Y|N|MARGIN_REQUIRED}, complexity{1-5}, automation{1-5}, cost_sensitivity{LOW|MED|HIGH}, evidence{E1..E5}, sharia_status, backtest_status{NOT_STARTED}, priority_score, refs (REF IDs separated by ;), cross_refs`

---

## 12. Quality Checks Before Finishing (Phase 20)

- Every `[REF-xxx]` exists in `BIBLIOGRAPHY.md`; every bibliography entry has a URL/DOI.
- No performance number without a REF.
- No duplicate canonical entries; every cross-ref resolves.
- Every STRATEGY has deterministic rules; every FRAMEWORK/FILTER has at least one operationalization.
- CSV row count = catalog count; enums valid.
- Count of `[UNVERIFIED]` items reported.

---

## 13. Final Report

1. Unique entries total, and by Entity Type, category, and scope.
2. Applicable to US stocks / spot crypto.
3. Requiring specialized data.
4. Counts per evidence level E1–E5.
5. Top 20 STRATEGY candidates for QuickEdge research, with score breakdown.
6. Recommended architecture (summary).
7. Data-provider dependencies and cost tiers.
8. Major implementation challenges.
9. Open research questions and unverified items.
10. Recommended research order: which strategies to test first, why, and what baseline each is compared against.

---

## 14. Phase 21 — Strategy Selection Layer (design document only)

The long-term goal: a meta-model that learns **which validated strategies to use, and with what weight, under which market conditions**. This phase designs it; building it comes after strategies are backtested.

### 14.1 Principles
- **Input universe:** only strategies that passed out-of-sample and walk-forward validation. Never feed the full catalog — the model would learn noise.
- **Objective:** risk-adjusted return (e.g. Sharpe, Calmar, or return subject to a max-drawdown constraint), net of costs. Never raw maximum profit — that objective learns to increase risk.
- **Prefer weighting over picking:** output a weight per strategy (including cash), not a single winner.
- **Risk Engine keeps veto power** over every allocation.

### 14.2 Design questions to answer (with cited literature where available)
1. **Regime features:** trend strength, realized volatility, volatility-of-volatility, correlation regime, liquidity, session, drawdown state. Which are computable without look-ahead?
2. **Training data:** per-strategy daily (or per-bar) net returns aligned with regime features, produced by the backtesting engine.
3. **Candidate approaches**, simplest first:
   - Equal weight across validated strategies (**mandatory baseline**).
   - Inverse-volatility / risk-parity weighting.
   - Rolling-performance weighting (recent risk-adjusted performance).
   - Rule-based regime switching (e.g. trend strategies on when ADX/volatility filter says trending).
   - Statistical regime models (HMM / regime-switching).
   - Supervised meta-model predicting each strategy's next-period risk-adjusted return.
   - Online learning / multi-armed bandits; RL last, only if simpler methods are beaten.
4. **Validation:** walk-forward only; purged/embargoed splits; count every configuration tried; report deflated Sharpe and probability of backtest overfitting.
5. **Acceptance criterion:** the selection layer is adopted only if it beats the equal-weight baseline out-of-sample, net of costs and extra turnover, with statistical significance. Otherwise use the baseline.
6. **Failure modes:** regime detection lag, switching costs, overfitting to few regime transitions, strategies that are correlated being treated as diversification.
7. **Explainability:** every allocation decision logs the features and reasons, so the user can audit why a strategy was chosen.

### 14.3 Output
`STRATEGY_SELECTION_LAYER.md` with: architecture, feature list, candidate approaches ranked by complexity, evidence from literature on strategy timing / regime switching (cite whether it has historically beaten simple diversification), validation protocol, acceptance criteria, and the data the backtesting engine must log to make this possible.

---

## 15. Binary Options Track (separate instrument, separate pipeline)

Binary options are **in project scope as a separate track**. They are not mixed with the stock/crypto catalog, statistics, rankings, risk engine or reports. All outputs go under `docs/research/trading_strategies/binary_options/`. Mark the existing catalog's binary-options mention as "→ see §15 track".

### 15.1 Instrument facts the research must establish (with REFs)
- Contract mechanics per platform: fixed-payout up/down (rise/fall, call/put, higher/lower, touch/no-touch), expiry grid (seconds to days), early close, strike rules, how the entry and settlement prices are sourced.
- **Who the counterparty is.** If the platform takes the other side of every contract, record it explicitly: this is a structural conflict of interest and affects price-feed trust.
- **Break-even math:** with net payout `p` on a win and full stake lost on a loss, break-even win rate = `1 / (1 + p)`. p = 1.00 → 50.0%; p = 0.85 → 54.1%; p = 0.80 → 55.6%; p = 0.70 → 58.8%. Ties/refund rules change this and must be modeled per platform.
- Whether the platform's price feed matches an independent reference feed (sample and measure the discrepancy).

### 15.2 Phase BO-0 — Platform due diligence (GATE: do this first)
For each candidate platform, verify from **primary sources only** (regulator registers, the platform's own legal/terms pages, official API docs) — never review/affiliate sites:
1. Legal entity, regulator and licence number; verify the licence on the regulator's own register.
2. Whether it accepts residents of **Egypt**; check Egypt FRA public warnings / negative lists for that platform.
3. Product-intervention status in major jurisdictions (EU/ESMA and national regulators, UK FCA, US CFTC/SEC, Australia ASIC, etc.) — record where retail binary options are banned and whether the platform is on any regulator warning list (incl. IOSCO I-SCAN).
4. **Official, documented, permitted API** for trading and historical data. Reverse-engineered/unofficial APIs, scraping, and browser automation are **not acceptable** for execution — if no official API exists, the platform is research-only/manual at most.
5. Terms of service on automated/algorithmic trading, account closure and profit-withholding clauses, KYC, deposit/withdrawal methods and documented withdrawal complaints from regulators (not forums).
6. Contract terms actually offered to Egyptian accounts: assets, expiries, payout ranges, minimum/maximum stake.
7. Historical price data availability and whether it is the same feed used for settlement.

**Output:** `BO_PLATFORM_DUE_DILIGENCE.md` with a table and a per-platform verdict: `ELIGIBLE` · `RESEARCH-ONLY (no official API / not available in Egypt)` · `REJECTED (unregulated, regulator warning, or ToS forbids automation)`. If **no platform is ELIGIBLE**, BO-1+ proceed as **offline research and simulation only**; no execution adapter is designed for a non-eligible platform.

**Stop after BO-0 and wait for the user's review.**

### 15.3 Research & strategy library (BO-1)
Separate catalog `BO_STRATEGY_CATALOG.md` + `BO_STRATEGY_DATABASE.csv`, IDs `BO-NNN`. Cover: price action, momentum, trend detection, mean reversion, volatility, support/resistance, statistical probability models, regime detection, time-of-day behavior — each **per expiry bucket** (≤1 min, 1–5 min, 5–60 min, hours, ≥1 day).
Reuse FEATURE/MODEL entities from the main catalog by ID; do not duplicate them.
For each strategy, the core question is: **what is P(win) at this expiry, and is it above the break-even rate for the actual payout?** Required evidence: research on short-horizon directional predictability (cite; note that very short horizons are close to a random walk after costs in most liquid markets — verify this from literature, do not assume it).

### 15.4 Backtesting & evaluation (BO-2)
- Separate engine: each trade = (entry time, direction, expiry, stake, payout at entry) → settled by the platform's own settlement rule on historical data.
- Data must come from the **platform's settlement feed** when available; otherwise measure feed mismatch and treat results as provisional.
- Metrics, per strategy **and per expiry bucket and regime**: win rate with confidence interval, break-even rate at actual payout, **net EV per $1 staked** = `P(win)·p − (1 − P(win))`, max consecutive losses, drawdown, number of trades, out-of-sample and walk-forward results, deflated/multiple-testing-adjusted significance.
- **Win rate alone is never a valid evaluation.** A strategy is only "candidate" if the lower bound of its out-of-sample win-rate confidence interval exceeds the break-even rate.
- Required sample size: compute the number of trades needed to distinguish the measured win rate from break-even at 95% confidence and report it (e.g. distinguishing 57% from 55.6% needs thousands of trades).

### 15.5 Risk engine (separate, BO-3 design)
Max stake per contract · max daily exposure · max daily loss · max consecutive losses (then halt) · max simultaneous contracts · minimum acceptable payout · allowed expiry list · **independent emergency stop** (separate process/flag that blocks all binary orders regardless of strategy state). No martingale or loss-recovery staking — explicitly prohibited.

### 15.6 Execution integration (BO-4 design, ELIGIBLE platforms only)
Adapter using only the official API: contract quote (payout at entry), buy confirmation with contract ID, open-contract status, settlement result and settlement price, reconciliation against the internal ledger. Paper/demo mode first. Real-money mode disabled by default and enabled only by explicit user authorization after §15.10 conditions are met.

### 15.7 AI evaluation layer
Independent from the stock/crypto selection layer. Inputs: probability estimate (calibrated — report calibration curves), payout, expiry, volatility, historical strategy performance. Decision rule: trade only if the calibrated lower-bound EV > 0 after all costs; otherwise **NO TRADE** (expected to be the most common output).

### 15.8 GUI design (BO-5 spec only)
"Binary Options Terminal", visually distinct from the conventional trading screens: asset, direction, duration, payout %, stake, potential return, potential loss, **break-even win rate for this payout**, strategy signal with its measured out-of-sample edge (or "no validated edge"), market analysis, contract status, settlement history, daily risk-limit usage, emergency stop button. A permanent risk notice panel shows the platform's regulatory status from BO-0.

### 15.9 Sharia
Evaluate per §8. Fixed-payout binary contracts are widely discussed in Islamic-finance literature in relation to maysir (gambling) and gharar; find and cite the relevant standards and fatwa bodies (e.g. AAOIFI, recognized fiqh academies), record the status, and flag `Requires scholar review` at minimum. Do not issue a ruling.

### 15.10 Conditions before any real-money binary trading
All must hold, documented: platform `ELIGIBLE` in BO-0 · official API · strategy passes §15.4 out-of-sample with CI above break-even · paper trading results consistent with backtest · Sharia review status recorded · user's explicit written approval.

### 15.11 Binary-track deliverables (under `binary_options/`)
`BO_PLATFORM_DUE_DILIGENCE.md` · `BO_STRATEGY_CATALOG.md` · `BO_STRATEGY_DATABASE.csv` · `BO_BACKTESTING_AND_EVALUATION.md` · `BO_RISK_ENGINE.md` · `BO_EXECUTION_INTEGRATION.md` · `BO_TERMINAL_GUI_SPEC.md` · `BO_SHARIA_ANALYSIS.md` · `BO_EXECUTIVE_SUMMARY.md`

---

Guiding principle: **Prove the edge before risking capital.**
