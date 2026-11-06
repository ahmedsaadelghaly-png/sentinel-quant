# ADR 0003 — Event-driven backtester

- Status: accepted
- Date: 2026-11-06

## Decision
- **Order of events is the look-ahead guard.** Per timestamp: fill earlier orders, mark at close, then show the strategy the bar. A strategy cannot reach a same-bar fill.
- **Market orders fill at the next bar's open.** Zero-volume bars fill nothing, because nothing traded. After a data gap, orders fill at the first price after it.
- **Stops:** fill at the stop price if traded through, at the open if a gap jumped them, always with slippage. A protective stop is live on its entry bar, since entry is at the open.
- **Costs:** 10 bps taker fee and 5 bps slippage per side by default. The fee is Binance's standard spot rate. The slippage figure is an assumption, to be replaced by paper-trading measurements. Config refuses zero costs.
- **Risk gate is a required argument** and the package ships no approve-all gate, so no backtest can bypass risk.
- Long-only, no leverage. An unaffordable order is rejected, never shrunk.

## Not modelled yet
Partial fills, volume limits, lot sizes, limit orders, fees charged in the base asset. A position open at the end is marked at the close with no exit cost, which flatters results slightly.
