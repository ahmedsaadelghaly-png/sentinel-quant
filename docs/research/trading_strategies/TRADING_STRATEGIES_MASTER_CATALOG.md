# Sentinel Quant — Trading Strategies Master Catalog

_Phase 1 output (inventory & classification). Profiles, evidence levels and Sharia status are filled in later phases._

## Summary

- **Unique entries:** 205
- **Merged duplicates:** 21 groups (31 input items absorbed into canonical entries)
- **Cross-references (listed in input under 2 categories):** 8
- **Added (not in input list):** 5
- **Applicable to US stocks:** 184 · **spot crypto:** 172

### By entity type

| Type | Count |
|---|---|
| STRATEGY | 77 |
| FILTER | 17 |
| FEATURE | 54 |
| MODEL | 18 |
| FRAMEWORK | 16 |
| EXECUTION | 7 |
| RISK | 16 |

### By scope

| Scope | Count |
|---|---|
| CORE | 173 |
| CORE-DATA | 13 |
| OUT-OF-SCOPE | 19 |

### By category

| Cat | Name | Count |
|---|---|---|
| A | Trend Following & Momentum | 14 |
| B | Mean Reversion | 13 |
| C | Price Action / S&R / Supply & Demand | 22 |
| D | Smart Money Concepts & ICT | 22 |
| E | Volume & Order Flow | 17 |
| F | Quantitative & Statistical | 24 |
| G | Fundamental & Macro | 16 |
| H | Volatility | 10 |
| I | Arbitrage | 6 |
| J | Sentiment & Behavioral | 11 |
| K | Seasonality & Time-Based | 11 |
| L | Algorithmic Execution | 10 |
| M | Portfolio & Risk Management | 15 |
| N | Other Frameworks | 14 |

Note: only **STRATEGY** entries are backtestable on their own. FILTERs/FRAMEWORKs are tested as A/B add-ons to a baseline strategy; FEATUREs/MODELs are inputs; EXECUTION/RISK belong to the execution and risk engines.


## A. Trend Following & Momentum

| ID | Name | Type | Scope | Min data | Aliases | Cross-refs | Notes |
|---|---|---|---|---|---|---|---|
| A-001 | Moving Average Crossover | STRATEGY | CORE | OHLCV_DAILY | SMA 50/200 golden/death cross; dual MA | A-EMA trend | SMA 50/200 merged here as a parameterization |
| A-002 | Price-vs-EMA Trend Following | STRATEGY | CORE | OHLCV_DAILY | EMA trend filter; price above/below MA | M-Volatility Targeting |  |
| A-003 | MACD Momentum | STRATEGY | CORE | OHLCV_DAILY | MACD signal-line cross |  |  |
| A-004 | RSI Momentum | STRATEGY | CORE | OHLCV_DAILY | RSI > 50/60 trend mode | B-RSI Overbought/Oversold | Opposite use of RSI to B; keep both, test separately |
| A-005 | Donchian Channel Breakout | STRATEGY | CORE | OHLCV_DAILY | N-bar high/low breakout; breakout trading | A-Turtle; C-Failed Breakout | Generic 'breakout trading' merged here |
| A-006 | Turtle Trading System | STRATEGY | CORE | OHLCV_DAILY | Turtle rules | A-Donchian; M-Fixed Fractional | Full system: Donchian entries + ATR (N) sizing + pyramiding |
| A-007 | Time-Series Momentum | STRATEGY | CORE | OHLCV_DAILY | TSMOM; absolute momentum | A-Momentum Rotation |  |
| A-008 | Cross-Sectional Momentum | STRATEGY | CORE | OHLCV_DAILY | Momentum factor; relative strength; 12-1 momentum | F-Residual Momentum; F-Multi-Factor | Canonical home for momentum factor (F) and relative strength |
| A-009 | Rate of Change (ROC) | FEATURE | CORE | OHLCV_DAILY | Momentum oscillator | A-TSMOM | Indicator; TSMOM is the strategy form |
| A-010 | ADX Trend Following | STRATEGY | CORE | OHLCV_DAILY | DMI/ADX | F-Regime Switching | ADX also reusable as a regime FILTER |
| A-011 | Parabolic SAR | STRATEGY | CORE | OHLCV_DAILY | PSAR stop-and-reverse | M-Trailing Stop |  |
| A-012 | Supertrend | STRATEGY | CORE | OHLCV_DAILY | ATR trailing band | H-ATR |  |
| A-013 | Momentum Rotation (Dual Momentum) | STRATEGY | CORE | OHLCV_DAILY | Dual momentum; ETF/asset rotation | A-TSMOM; A-XSMOM; G-Sector Rotation | Long-only by construction |
| A-014 | 52-Week High Momentum | STRATEGY | CORE | OHLCV_DAILY | Nearness to 52-week high | A-XSMOM | ADDED: discovered, not in input list |

## B. Mean Reversion

| ID | Name | Type | Scope | Min data | Aliases | Cross-refs | Notes |
|---|---|---|---|---|---|---|---|
| B-001 | RSI Overbought/Oversold | STRATEGY | CORE | OHLCV_DAILY | RSI(2) reversion; Connors RSI | A-RSI Momentum |  |
| B-002 | Bollinger Band Reversion | STRATEGY | CORE | OHLCV_DAILY | BB fade | H-Bollinger Squeeze | Squeeze (H) is the breakout use of the same bands |
| B-003 | Moving Average Reversion | STRATEGY | CORE | OHLCV_DAILY | Distance-from-MA fade | B-Z-Score |  |
| B-004 | VWAP Reversion | STRATEGY | CORE | OHLCV_INTRADAY | Fade deviation from session VWAP | E-VWAP; L-VWAP Execution | Distinct from VWAP feature (E) and VWAP execution (L) |
| B-005 | Z-Score Mean Reversion | STRATEGY | CORE | OHLCV_DAILY | Statistical mean reversion; Bollinger z | B-OU Model | 'Statistical mean reversion' merged here |
| B-006 | Pairs Trading (Distance Method) | STRATEGY | CORE | OHLCV_DAILY | Distance pairs | F-Statistical Arbitrage; I-Arbitrage | Canonical home for pairs (also listed in F, I) |
| B-007 | Cointegration Pairs Trading | STRATEGY | CORE | OHLCV_DAILY | Engle-Granger / Johansen pairs | B-Pairs; F-Kalman Filter | Canonical home for cointegration (also listed in F) |
| B-008 | Ornstein-Uhlenbeck Spread Model | MODEL | CORE | OHLCV_DAILY | OU process; half-life estimation | B-Cointegration Pairs | Model for spread dynamics, not a standalone strategy |
| B-009 | RSI Divergence | FILTER | CORE | OHLCV_DAILY | Bullish/bearish divergence | D-SMT Divergence; E-Delta Divergence | Depends on swing-point detection (look-ahead risk) |
| B-010 | CCI Reversion | STRATEGY | CORE | OHLCV_DAILY | Commodity Channel Index fade |  |  |
| B-011 | Keltner Channel Reversion | STRATEGY | CORE | OHLCV_DAILY | Keltner fade | H-ATR |  |
| B-012 | Adaptive Mean Reversion | STRATEGY | CORE | OHLCV_DAILY | Volatility-adjusted bands; regime-gated MR | F-Regime Switching | Needs precise definition in profile phase |
| B-013 | Short-Term Reversal | STRATEGY | CORE | OHLCV_DAILY | 1-week / 1-month cross-sectional reversal; contrarian | J-Contrarian | ADDED: discovered; canonical home for 'contrarian' as a strategy |

Listed here in the input but canonical elsewhere: **Statistical Arbitrage (B context)** → F

## C. Price Action / S&R / Supply & Demand

| ID | Name | Type | Scope | Min data | Aliases | Cross-refs | Notes |
|---|---|---|---|---|---|---|---|
| C-001 | Support & Resistance Levels | FEATURE | CORE | OHLCV_DAILY | Horizontal levels; key levels | C-Swing Points; C-Pivot Points | 'Horizontal levels' merged here. Many competing detection algorithms |
| C-002 | Supply & Demand Zones | FEATURE | CORE | OHLCV_DAILY | Base-rally/drop zones | D-Order Blocks | High ambiguity; overlaps order blocks |
| C-003 | Break and Retest | STRATEGY | CORE | OHLCV_DAILY | Breakout pullback | C-S&R; A-Donchian |  |
| C-004 | Trendlines | FEATURE | CORE | OHLCV_DAILY | Trendline trading | C-Channel Trading | Detection is subjective; needs algorithmic definition |
| C-005 | Channel Trading | STRATEGY | CORE | OHLCV_DAILY | Regression / parallel channel | C-Trendlines |  |
| C-006 | Candlestick Pattern Trading | STRATEGY | CORE | OHLCV_DAILY | Candlestick signals | C-Pin Bar; C-Engulfing; C-Inside Bar; C-Outside Bar | Umbrella strategy; individual patterns are FEATUREs |
| C-007 | Pin Bar | FEATURE | CORE | OHLCV_DAILY | Hammer; shooting star | C-Rejection Trading |  |
| C-008 | Engulfing Pattern | FEATURE | CORE | OHLCV_DAILY | Bullish/bearish engulfing |  |  |
| C-009 | Inside Bar | FEATURE | CORE | OHLCV_DAILY | Harami-like contraction bar | H-Volatility Contraction |  |
| C-010 | Outside Bar | FEATURE | CORE | OHLCV_DAILY | Expansion bar |  |  |
| C-011 | Rejection Trading | STRATEGY | CORE | OHLCV_DAILY | Level rejection; wick rejection | C-S&R; C-Pin Bar |  |
| C-012 | Failed Breakout Reversal | STRATEGY | CORE | OHLCV_DAILY | False breakout; fakeout fade; turtle soup | D-Liquidity Sweep | Operationally near-identical to D-Liquidity Sweep (see decisions) |
| C-013 | Swing Highs/Lows | FEATURE | CORE | OHLCV_DAILY | Swing points; zigzag | D-BOS; D-MSS | Confirmed only N bars later: major look-ahead risk |
| C-014 | Pivot Points | FEATURE | CORE | OHLCV_DAILY | Floor/Camarilla/Fibonacci pivots | C-S&R |  |
| C-015 | Fibonacci Retracement | FEATURE | CORE | OHLCV_DAILY | Fib levels | D-OTE | Canonical home; OTE (D) references it |
| C-016 | Fibonacci Extensions | FEATURE | CORE | OHLCV_DAILY | Fib targets |  |  |
| C-017 | Chart Pattern Trading | FRAMEWORK | CORE | OHLCV_DAILY | Classical chart patterns | C-H&S; C-Double Top/Bottom; C-Flags; C-Triangles; C-Wedges | Umbrella; must be operationalized per pattern |
| C-018 | Head and Shoulders | FEATURE | CORE | OHLCV_DAILY | H&S; inverse H&S | C-Chart Patterns |  |
| C-019 | Double Top / Double Bottom | FEATURE | CORE | OHLCV_DAILY | M/W patterns | D-Equal Highs/Lows |  |
| C-020 | Flags and Pennants | FEATURE | CORE | OHLCV_DAILY | Continuation patterns |  | Flags and pennants merged into one detector family |
| C-021 | Triangles | FEATURE | CORE | OHLCV_DAILY | Ascending/descending/symmetrical | H-Volatility Contraction |  |
| C-022 | Wedges | FEATURE | CORE | OHLCV_DAILY | Rising/falling wedges |  |  |

Listed here in the input but canonical elsewhere: **Opening Range Breakout** → K

## D. Smart Money Concepts & ICT

| ID | Name | Type | Scope | Min data | Aliases | Cross-refs | Notes |
|---|---|---|---|---|---|---|---|
| D-001 | ICT / Smart Money Concepts (umbrella) | FRAMEWORK | CORE | OHLCV_INTRADAY | SMC; ICT | all D entries | ADDED as umbrella. Institutional-manipulation narrative = Hypothesis (untested) |
| D-002 | Liquidity Sweep Reversal | STRATEGY | CORE | OHLCV_INTRADAY | Stop hunt; liquidity grab | C-Failed Breakout; D-Judas Swing | SMC variant of C-Failed Breakout using SMC level definitions |
| D-003 | Equal Highs / Equal Lows | FEATURE | CORE | OHLCV_INTRADAY | EQH/EQL | C-Double Top/Bottom | Needs tolerance parameter |
| D-004 | Buy-Side / Sell-Side Liquidity Pools | FEATURE | CORE | OHLCV_INTRADAY | BSL/SSL; liquidity pools | D-EQH/EQL; C-Swing Points | BSL, SSL and 'liquidity pools' merged: same concept (clustered highs/lows) |
| D-005 | Fair Value Gap | FEATURE | CORE | OHLCV_INTRADAY | FVG; imbalance | D-Inverse FVG; D-BPR | Clean 3-bar definition exists: most testable D concept |
| D-006 | Inverse Fair Value Gap | FEATURE | CORE | OHLCV_INTRADAY | IFVG | D-FVG |  |
| D-007 | Order Blocks | FEATURE | CORE | OHLCV_INTRADAY | OB | C-Supply & Demand | High ambiguity |
| D-008 | Breaker Blocks | FEATURE | CORE | OHLCV_INTRADAY | Breaker | D-Order Blocks |  |
| D-009 | Mitigation Blocks | FEATURE | CORE | OHLCV_INTRADAY | Mitigation | D-Order Blocks |  |
| D-010 | Break of Structure | FEATURE | CORE | OHLCV_INTRADAY | BOS | C-Swing Points |  |
| D-011 | Market Structure Shift / CHOCH | FEATURE | CORE | OHLCV_INTRADAY | MSS; Change of Character | D-BOS | MSS and CHOCH merged: practitioners use them near-interchangeably (see decisions) |
| D-012 | Displacement | FEATURE | CORE | OHLCV_INTRADAY | Impulsive move | D-FVG | Needs threshold (e.g. range > k*ATR) |
| D-013 | Premium / Discount | FILTER | CORE | OHLCV_INTRADAY | Equilibrium; 50% of range | C-Fib Retracement |  |
| D-014 | Optimal Trade Entry | FILTER | CORE | OHLCV_INTRADAY | OTE; 62-79% retracement | C-Fib Retracement |  |
| D-015 | SMT Divergence | FILTER | CORE | OHLCV_INTRADAY | Smart Money Technique divergence | B-RSI Divergence | Needs correlated pair: BTC/ETH, SPY/QQQ |
| D-016 | Judas Swing | STRATEGY | CORE | OHLCV_INTRADAY | Session-open false move | D-Liquidity Sweep; K-Session Filter | Session-anchored liquidity sweep |
| D-017 | Power of Three / AMD | FRAMEWORK | CORE | OHLCV_INTRADAY | Accumulation-Manipulation-Distribution | D-Judas Swing |  |
| D-018 | Kill Zones | FILTER | CORE | OHLCV_INTRADAY | ICT session windows | K-Session Filter | Overlaps K-Session Filter; kept separate because time windows differ |
| D-019 | Daily Bias | FILTER | CORE | OHLCV_DAILY | HTF directional bias | N-Multi-Timeframe |  |
| D-020 | IPDA Concepts | FRAMEWORK | CORE | OHLCV_DAILY | Interbank Price Delivery Algorithm; 20/40/60-day lookbacks |  | Claim of a delivery algorithm is Hypothesis (untested) |
| D-021 | Inducement | FEATURE | CORE | OHLCV_INTRADAY | IDM | D-Liquidity Pools | High ambiguity |
| D-022 | Balanced Price Range | FEATURE | CORE | OHLCV_INTRADAY | BPR; overlapping FVGs | D-FVG |  |

Listed here in the input but canonical elsewhere: **Optimal Trade Entry levels** → C (Fibonacci Retracement)

## E. Volume & Order Flow

| ID | Name | Type | Scope | Min data | Aliases | Cross-refs | Notes |
|---|---|---|---|---|---|---|---|
| E-001 | Volume Profile | FEATURE | CORE | OHLCV_INTRADAY | VP; fixed-range VP | E-POC; E-Value Area; N-Market Profile | Fixed-range VP merged. Bar-based approximation is CORE; exact needs trades |
| E-002 | Point of Control | FEATURE | CORE | OHLCV_INTRADAY | POC | E-Volume Profile |  |
| E-003 | Value Area High / Low | FEATURE | CORE | OHLCV_INTRADAY | VAH/VAL | E-Volume Profile |  |
| E-004 | VWAP | FEATURE | CORE | OHLCV_INTRADAY | Session VWAP | B-VWAP Reversion; L-VWAP Execution |  |
| E-005 | Anchored VWAP | FEATURE | CORE | OHLCV_INTRADAY | AVWAP | E-VWAP |  |
| E-006 | Volume Breakout | STRATEGY | CORE | OHLCV_DAILY | High-relative-volume breakout | A-Donchian |  |
| E-007 | On-Balance Volume | FEATURE | CORE | OHLCV_DAILY | OBV |  |  |
| E-008 | Cumulative Volume Delta | FEATURE | CORE-DATA | TICK | CVD | E-Delta Divergence | Needs aggressor side; free in crypto trade feeds, paid for US stocks |
| E-009 | Footprint Charts | FEATURE | CORE-DATA | TICK | Bid/ask footprint | E-CVD |  |
| E-010 | Order Book Imbalance | FEATURE | CORE-DATA | L2 | OBI; queue imbalance |  | L2 snapshots; crypto exchanges free via websocket |
| E-011 | Absorption | FEATURE | CORE-DATA | TICK | Passive absorption | E-Footprint |  |
| E-012 | Iceberg Order Detection | FEATURE | CORE-DATA | L2 | Hidden size detection | L-Iceberg Execution | Needs L2 + trades (ideally L3) |
| E-013 | Delta Divergence | FILTER | CORE-DATA | TICK | Price vs CVD divergence | E-CVD; B-RSI Divergence |  |
| E-014 | Time and Sales Analysis | FEATURE | CORE-DATA | TICK | Tape reading | E-CVD | Data source more than a method |
| E-015 | Volume Spread Analysis | FRAMEWORK | CORE | OHLCV_DAILY | VSA | N-Wyckoff |  |
| E-016 | Money Flow Index | FEATURE | CORE | OHLCV_DAILY | MFI |  |  |
| E-017 | Accumulation/Distribution Line | FEATURE | CORE | OHLCV_DAILY | A/D; Chaikin |  |  |

## F. Quantitative & Statistical

| ID | Name | Type | Scope | Min data | Aliases | Cross-refs | Notes |
|---|---|---|---|---|---|---|---|
| F-001 | Statistical Arbitrage | STRATEGY | CORE | OHLCV_DAILY | Stat arb; multi-asset residual reversion | B-Pairs; F-PCA | Canonical home for stat arb (also listed in I) |
| F-002 | Multi-Factor Model / Factor Investing | STRATEGY | CORE | FUNDAMENTAL | Factor investing; smart beta | A-XSMOM; F-Value; F-Quality; F-Low Vol | Factor investing and multi-factor models merged |
| F-003 | Value Factor | STRATEGY | CORE | FUNDAMENTAL | Value investing (G); B/M, E/P | G-Financial Statement Analysis | Absorbs G 'Value Investing' |
| F-004 | Quality Factor | STRATEGY | CORE | FUNDAMENTAL | Quality investing (G); profitability | G-Cash Flow Strategies | Absorbs G 'Quality Investing' |
| F-005 | Low Volatility Factor | STRATEGY | CORE | OHLCV_DAILY | Low-vol anomaly; min-variance | M-Risk Parity |  |
| F-006 | Residual Momentum | STRATEGY | CORE | OHLCV_DAILY | Idiosyncratic momentum | A-XSMOM |  |
| F-007 | Kalman Filter | MODEL | CORE | OHLCV_DAILY | Dynamic hedge ratio; state-space | B-Cointegration Pairs |  |
| F-008 | Hidden Markov Model | MODEL | CORE | OHLCV_DAILY | HMM regimes | F-Regime Switching |  |
| F-009 | Regime Switching Models | MODEL | CORE | OHLCV_DAILY | Markov-switching | H-Volatility Regime |  |
| F-010 | Bayesian Models | MODEL | CORE | OHLCV_DAILY | Bayesian inference; shrinkage |  |  |
| F-011 | Monte Carlo Simulation | RISK | CORE | OHLCV_DAILY | Bootstrap; resampling | M-Risk of Ruin | Validation/risk tool, not alpha |
| F-012 | Machine Learning Signals (umbrella) | MODEL | CORE | OHLCV_DAILY | ML alpha | all F models |  |
| F-013 | Reinforcement Learning | MODEL | CORE | OHLCV_DAILY | RL agents |  | Highest overfitting risk |
| F-014 | Classical Time-Series Forecasting | MODEL | CORE | OHLCV_DAILY | ARIMA; GARCH | H-Volatility Regime |  |
| F-015 | Linear Regression | MODEL | CORE | OHLCV_DAILY | OLS; ridge; lasso |  |  |
| F-016 | Logistic Regression | MODEL | CORE | OHLCV_DAILY | Direction classification |  |  |
| F-017 | Random Forest | MODEL | CORE | OHLCV_DAILY | RF |  |  |
| F-018 | Gradient Boosting / XGBoost | MODEL | CORE | OHLCV_DAILY | GBM; XGBoost; LightGBM |  | Gradient boosting and XGBoost merged |
| F-019 | Neural Networks (MLP) | MODEL | CORE | OHLCV_DAILY | Feed-forward nets |  |  |
| F-020 | LSTM | MODEL | CORE | OHLCV_DAILY | Recurrent nets |  |  |
| F-021 | Transformer Forecasting | MODEL | CORE | OHLCV_DAILY | Attention models |  |  |
| F-022 | PCA-Based Strategies | MODEL | CORE | OHLCV_DAILY | Eigenportfolios | F-Stat Arb |  |
| F-023 | Clustering Methods | MODEL | CORE | OHLCV_DAILY | k-means; hierarchical | M-Correlation Allocation |  |
| F-024 | Anomaly Detection | MODEL | CORE | OHLCV_DAILY | Outlier detection |  |  |

Listed here in the input but canonical elsewhere: **Pairs Trading** → B; **Cointegration** → B; **Momentum Factor** → A (Cross-Sectional Momentum)

## G. Fundamental & Macro

| ID | Name | Type | Scope | Min data | Aliases | Cross-refs | Notes |
|---|---|---|---|---|---|---|---|
| G-001 | Growth Investing | STRATEGY | CORE | FUNDAMENTAL | Growth screens | F-Multi-Factor |  |
| G-002 | Dividend Investing | STRATEGY | CORE | FUNDAMENTAL | Dividend yield / growth | F-Value | Dividend purification is a Sharia item |
| G-003 | Post-Earnings Announcement Drift | STRATEGY | CORE | FUNDAMENTAL | Earnings surprise; PEAD; SUE | G-Earnings Momentum | 'Earnings surprise' merged here |
| G-004 | Earnings Momentum | STRATEGY | CORE | FUNDAMENTAL | Estimate momentum | J-Analyst Revisions |  |
| G-005 | News Trading | STRATEGY | CORE-DATA | ALT | Headline trading | J-News Sentiment | Latency-sensitive |
| G-006 | Interest Rate Regime | FILTER | CORE | ALT | Rates trading | G-Yield Curve | Direct rate trading needs bonds/futures: only used here as a filter |
| G-007 | Inflation Regime | FILTER | CORE | ALT | CPI regime |  | Filter use only |
| G-008 | GDP / Growth Regime | FILTER | CORE | ALT | Macro growth regime |  | Filter use only |
| G-009 | Central Bank Events | FILTER | CORE | ALT | FOMC trading | K-Session Filter | Filter / event-window use |
| G-010 | Yield Curve Regime | FILTER | CORE | ALT | Curve slope |  | Filter use only |
| G-011 | Sector Rotation | STRATEGY | CORE | OHLCV_DAILY | Sector ETF rotation | A-Momentum Rotation |  |
| G-012 | Event-Driven Investing | FRAMEWORK | CORE | ALT | Corporate events | G-Merger Arb | Umbrella |
| G-013 | Merger Arbitrage | STRATEGY | CORE | ALT | Risk arbitrage | G-Event-Driven | Stock deals need shorting acquirer |
| G-014 | Financial Statement Analysis | FRAMEWORK | CORE | FUNDAMENTAL | F-Score; accounting signals | F-Quality; F-Value |  |
| G-015 | Cash-Flow Based Strategies | STRATEGY | CORE | FUNDAMENTAL | FCF yield; accruals anomaly | F-Quality |  |
| G-016 | Insider Activity | STRATEGY | CORE | ALT | Insider transactions; Form 4 | J-Insider (xref) | Canonical home (also listed in J) |

## H. Volatility

| ID | Name | Type | Scope | Min data | Aliases | Cross-refs | Notes |
|---|---|---|---|---|---|---|---|
| H-001 | Volatility Breakout | STRATEGY | CORE | OHLCV_DAILY | Range-expansion breakout | A-Donchian |  |
| H-002 | Bollinger Squeeze | STRATEGY | CORE | OHLCV_DAILY | BB/Keltner squeeze | B-Bollinger Reversion |  |
| H-003 | ATR & ATR Bands | FEATURE | CORE | OHLCV_DAILY | ATR-based trading | M-Volatility Targeting; A-Supertrend | ATR is the feature; trading uses live in stops/sizing |
| H-004 | Volatility Expansion / Contraction | FILTER | CORE | OHLCV_DAILY | Vol compression/expansion | H-Bollinger Squeeze; C-Inside Bar | Expansion and contraction merged into one regime filter |
| H-005 | Implied vs Realized Volatility | STRATEGY | OUT-OF-SCOPE | ALT | Variance risk premium |  | Requires options |
| H-006 | Volatility Skew Trading | STRATEGY | OUT-OF-SCOPE | ALT | Skew |  | Requires options |
| H-007 | Long Straddle | STRATEGY | OUT-OF-SCOPE | ALT |  |  | Requires options |
| H-008 | Long Strangle | STRATEGY | OUT-OF-SCOPE | ALT |  |  | Requires options |
| H-009 | Iron Condor | STRATEGY | OUT-OF-SCOPE | ALT |  |  | Requires options |
| H-010 | Volatility Regime Filter | FILTER | CORE | OHLCV_DAILY | Volatility regime trading | F-Regime Switching |  |

## I. Arbitrage

| ID | Name | Type | Scope | Min data | Aliases | Cross-refs | Notes |
|---|---|---|---|---|---|---|---|
| I-001 | Cross-Exchange (Spatial) Arbitrage | STRATEGY | OUT-OF-SCOPE | L2 | Spatial arb |  | Spatial and cross-exchange merged. Needs inventory on multiple venues, speed |
| I-002 | Triangular Arbitrage | STRATEGY | OUT-OF-SCOPE | L2 |  |  | Latency competition |
| I-003 | Index Arbitrage | STRATEGY | OUT-OF-SCOPE | TICK |  |  | Futures + basket |
| I-004 | ETF Arbitrage | STRATEGY | OUT-OF-SCOPE | TICK | Creation/redemption |  | Authorized-participant access |
| I-005 | Futures-Spot Basis Arbitrage | STRATEGY | OUT-OF-SCOPE | OHLCV_DAILY | Cash-and-carry; reverse cash-and-carry |  | Cash-and-carry and reverse merged into this entry |
| I-006 | Funding Rate Arbitrage | STRATEGY | OUT-OF-SCOPE | OHLCV_DAILY | Perp funding carry |  | Requires perpetual futures |

Listed here in the input but canonical elsewhere: **Statistical Arbitrage** → F

## J. Sentiment & Behavioral

| ID | Name | Type | Scope | Min data | Aliases | Cross-refs | Notes |
|---|---|---|---|---|---|---|---|
| J-001 | Fear & Greed Index | FEATURE | CORE | ALT | CNN / crypto F&G | J-Contrarian |  |
| J-002 | News Sentiment | FEATURE | CORE-DATA | ALT | NLP news scores | G-News Trading |  |
| J-003 | Social Media Sentiment | FEATURE | CORE-DATA | ALT | Reddit sentiment; X/Twitter; StockTwits |  | Reddit merged here |
| J-004 | Google Trends | FEATURE | CORE | ALT | Search volume |  |  |
| J-005 | Contrarian Trading | FRAMEWORK | CORE | OHLCV_DAILY | Fade the crowd | B-Short-Term Reversal; J-Fear & Greed | Strategy form lives in B |
| J-006 | Crowded Trade Detection | FILTER | CORE | ALT | Crowding | J-Short Interest; J-13F |  |
| J-007 | Short Interest | STRATEGY | CORE | ALT | Days-to-cover |  | FINRA bi-monthly data |
| J-008 | Analyst Revisions | STRATEGY | CORE-DATA | FUNDAMENTAL | Estimate revisions | G-Earnings Momentum | Consensus data usually paid |
| J-009 | Put/Call Ratio | FEATURE | CORE | ALT | Options sentiment |  | Uses published ratios only; no options trading |
| J-010 | Institutional Holdings (13F) | STRATEGY | CORE | ALT | 13F; hedge-fund cloning | J-Crowding | 45-day reporting lag |
| J-011 | Crypto On-Chain Metrics | FEATURE | CORE-DATA | ALT | MVRV; exchange flows |  | ADDED: discovered |

Listed here in the input but canonical elsewhere: **Insider Transactions** → G (Insider Activity)

## K. Seasonality & Time-Based

| ID | Name | Type | Scope | Min data | Aliases | Cross-refs | Notes |
|---|---|---|---|---|---|---|---|
| K-001 | Day-of-Week Effect | STRATEGY | CORE | OHLCV_DAILY | Weekday effects | K-Crypto Weekend |  |
| K-002 | Turn-of-the-Month | STRATEGY | CORE | OHLCV_DAILY | TOM; month-end effect |  | Month-end effect merged here |
| K-003 | January Effect | STRATEGY | CORE | OHLCV_DAILY | Small-cap January |  |  |
| K-004 | Session-Based Filter | FILTER | CORE | OHLCV_INTRADAY | Asia/London/NY sessions | D-Kill Zones |  |
| K-005 | London Open Breakout | STRATEGY | CORE | OHLCV_INTRADAY | London open | K-Session Filter | Applies to crypto, not US stocks |
| K-006 | Opening Range Breakout | STRATEGY | CORE | OHLCV_INTRADAY | ORB; NY open breakout | C (listed); K-Session Filter | Canonical home (also listed in C). 'New York Open' merged here |
| K-007 | Closing Auction Imbalance | STRATEGY | CORE-DATA | TICK | MOC imbalance |  | Needs imbalance feed |
| K-008 | Commodity Seasonality | STRATEGY | OUT-OF-SCOPE | OHLCV_DAILY | Seasonal spreads |  | Commodity futures |
| K-009 | Crypto Weekend Effect | STRATEGY | CORE | OHLCV_INTRADAY | Weekend returns/volatility | K-Day-of-Week |  |
| K-010 | Intraday Time-of-Day Momentum | STRATEGY | CORE | OHLCV_INTRADAY | Intraday patterns; last-half-hour momentum | K-ORB |  |
| K-011 | Overnight vs Intraday Returns | STRATEGY | CORE | OHLCV_DAILY | Night effect |  | ADDED: discovered |

## L. Algorithmic Execution

| ID | Name | Type | Scope | Min data | Aliases | Cross-refs | Notes |
|---|---|---|---|---|---|---|---|
| L-001 | Market Making | STRATEGY | OUT-OF-SCOPE | L2 | Liquidity provision |  | Inventory risk, low-latency infra |
| L-002 | High-Frequency Trading | STRATEGY | OUT-OF-SCOPE | L2 | HFT |  | Colocation |
| L-003 | Scalping Algorithms | STRATEGY | OUT-OF-SCOPE | TICK | Scalping |  | Cost sensitivity too high for small accounts |
| L-004 | VWAP Execution | EXECUTION | CORE | OHLCV_INTRADAY | VWAP algo | E-VWAP; B-VWAP Reversion |  |
| L-005 | TWAP Execution | EXECUTION | CORE | OHLCV_INTRADAY | TWAP |  |  |
| L-006 | POV Execution | EXECUTION | OUT-OF-SCOPE | TICK | Percent of volume |  | Irrelevant at small size |
| L-007 | Smart Order Routing | EXECUTION | OUT-OF-SCOPE | L2 | SOR |  | Broker-side |
| L-008 | Iceberg Execution | EXECUTION | OUT-OF-SCOPE | L2 | Reserve orders | E-Iceberg Detection |  |
| L-009 | Liquidity-Seeking Execution | EXECUTION | OUT-OF-SCOPE | L2 | Dark-pool seeking |  |  |
| L-010 | Arrival Price / Implementation Shortfall | EXECUTION | CORE | OHLCV_INTRADAY | IS; arrival price |  | Useful as a cost-measurement benchmark |

## M. Portfolio & Risk Management

| ID | Name | Type | Scope | Min data | Aliases | Cross-refs | Notes |
|---|---|---|---|---|---|---|---|
| M-001 | Risk Parity | RISK | CORE | OHLCV_DAILY | Equal risk contribution | F-Low Vol |  |
| M-002 | Equal Weighting | RISK | CORE | OHLCV_DAILY | 1/N | Phase 21 baseline | Mandatory baseline for the selection layer |
| M-003 | Volatility Targeting | RISK | CORE | OHLCV_DAILY | Vol scaling | H-ATR |  |
| M-004 | Kelly Criterion | RISK | CORE | OHLCV_DAILY | Fractional Kelly | M-Risk of Ruin |  |
| M-005 | Fixed Fractional Sizing | RISK | CORE | OHLCV_DAILY | Percent risk | M-Max Risk per Trade |  |
| M-006 | Dynamic Position Sizing | RISK | CORE | OHLCV_DAILY | Confidence-scaled sizing |  |  |
| M-007 | Trailing Stop | RISK | CORE | OHLCV_DAILY | Chandelier; ATR trail | A-PSAR |  |
| M-008 | Scale In (Pyramiding) | RISK | CORE | OHLCV_DAILY | Pyramiding | A-Turtle |  |
| M-009 | Scale Out | RISK | CORE | OHLCV_DAILY | Partial profits |  |  |
| M-010 | Portfolio Rebalancing | RISK | CORE | OHLCV_DAILY | Calendar / threshold |  |  |
| M-011 | Drawdown Control | RISK | CORE | OHLCV_DAILY | DD-based de-risking |  |  |
| M-012 | Correlation-Based Allocation | RISK | CORE | OHLCV_DAILY | HRP; correlation caps | F-Clustering |  |
| M-013 | Maximum Risk per Trade | RISK | CORE | OHLCV_DAILY | Per-trade risk cap | M-Fixed Fractional |  |
| M-014 | Portfolio Exposure Limits | RISK | CORE | OHLCV_DAILY | Gross/net/sector caps |  |  |
| M-015 | Risk of Ruin | RISK | CORE | OHLCV_DAILY | Ruin probability | F-Monte Carlo | Metric |

## N. Other Frameworks

| ID | Name | Type | Scope | Min data | Aliases | Cross-refs | Notes |
|---|---|---|---|---|---|---|---|
| N-001 | Auction Market Theory | FRAMEWORK | CORE | OHLCV_INTRADAY | AMT | N-Market Profile |  |
| N-002 | Market Profile (TPO) | FRAMEWORK | CORE | OHLCV_INTRADAY | TPO charts | E-Volume Profile | Time-based, distinct from volume profile |
| N-003 | Wyckoff Method | FRAMEWORK | CORE | OHLCV_DAILY | Wyckoff phases | E-VSA; D-Power of Three |  |
| N-004 | Elliott Wave Theory | FRAMEWORK | CORE | OHLCV_DAILY | EWT |  | Very high ambiguity |
| N-005 | Harmonic Patterns | FRAMEWORK | CORE | OHLCV_DAILY | Gartley; Bat; Butterfly | C-Fib |  |
| N-006 | Gann Methods | FRAMEWORK | CORE | OHLCV_DAILY | Gann angles/square of 9 |  |  |
| N-007 | Ichimoku Cloud | STRATEGY | CORE | OHLCV_DAILY | Ichimoku Kinko Hyo | A-MA Crossover | Deterministic rules exist |
| N-008 | Renko Charts | FEATURE | CORE | OHLCV_INTRADAY | Renko-based trading |  | Chart transform; strategies use brick reversals |
| N-009 | Heikin-Ashi | FEATURE | CORE | OHLCV_DAILY | HA candles |  | Not tradable prices: fills must use real OHLC |
| N-010 | Point and Figure | FEATURE | CORE | OHLCV_DAILY | P&F |  |  |
| N-011 | Fractals | FEATURE | CORE | OHLCV_DAILY | Williams fractals | C-Swing Points | 2-bar confirmation lag |
| N-012 | Adaptive Trading Systems | FRAMEWORK | CORE | OHLCV_DAILY | KAMA; adaptive parameters | B-Adaptive MR |  |
| N-013 | Multi-Timeframe Analysis | FILTER | CORE | OHLCV_INTRADAY | MTF | D-Daily Bias | Classic source of look-ahead bugs (unclosed HTF bars) |
| N-014 | Hybrid Multi-Strategy Systems | FRAMEWORK | CORE | OHLCV_DAILY | Strategy ensembles | Phase 21 | Design target of Phase 21 |

## Deduplication log

| Input item(s) | Listed in | Canonical entry |
|---|---|---|
| SMA 50/200 | A | A-MA Crossover |
| Breakout Trading | A | A-Donchian |
| Relative Strength | A | A-XSMOM |
| Statistical Mean Reversion | B | B-Z-Score |
| Horizontal Levels | C | C-S&R |
| Trendline Trading | C | C-Trendlines |
| Flags / Pennants (2 items) | C | C-Flags and Pennants |
| Buy-Side Liquidity, Sell-Side Liquidity, Liquidity Pools (3 items) | D | D-Liquidity Pools |
| Market Structure Shift + CHOCH (2 items) | D | D-MSS/CHOCH |
| Fixed Range Volume Profile | E | E-Volume Profile |
| Factor Investing + Multi-Factor Models (2 items) | F | F-Multi-Factor |
| Gradient Boosting + XGBoost (2 items) | F | F-GBM/XGBoost |
| Value Investing | G | F-Value Factor |
| Quality Investing | G | F-Quality Factor |
| Earnings Surprise | G | G-PEAD |
| Volatility Expansion + Contraction (2 items) | H | H-Vol Expansion/Contraction |
| Spatial + Cross-Exchange Arbitrage (2 items) | I | I-Cross-Exchange |
| Futures-Spot, Cash-and-Carry, Reverse Cash-and-Carry (3 items) | I | I-Basis Arbitrage |
| Reddit Sentiment | J | J-Social Sentiment |
| Month-End Effect | K | K-Turn-of-the-Month |
| New York Open | K | K-ORB |

## Cross-reference log

| Item | Listed in | Canonical home |
|---|---|---|
| Opening Range Breakout | C | K |
| Pairs Trading | F | B |
| Cointegration | F | B |
| Momentum Factor | F | A (Cross-Sectional Momentum) |
| Statistical Arbitrage | I | F |
| Statistical Arbitrage (B context) | B | F |
| Insider Transactions | J | G (Insider Activity) |
| Optimal Trade Entry levels | D | C (Fibonacci Retracement) |
