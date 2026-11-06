# ADR 0005 — Trading daemon, ledger and execution

- Status: accepted
- Date: 2026-11-06

## Decision
- **No live adapter exists.** `mode: live` refuses to start even when approved, and the testnet adapter refuses a non-testnet URL. Adding live is a deliberate future change, after gates G1 to G8.
- **SQLite ledger is the source of truth,** with sim and paper in separate files. Order intent is written before sending.
- **Deterministic client order ids,** so replaying a bar after a crash cannot duplicate an order.
- **Booking a fill and saving its effect on risk state are one transaction.** A replayed fill books nothing, so separate writes could lose a loss for good.
- **Orders carry their signal time.** The simulator fills only on strictly later bars. Without this, recovery let an order fill on its own signal bar.
- **Reconciliation runs before any new order** each bar. A difference engages the kill switch and needs a person.
- **Bars older than two bars are never traded,** so catching up after downtime cannot act on stale signals.
- **Fill rules exist twice** (backtest and simulator), guarded by a parity test requiring identical fills.

## Known risk
Signals use mainnet candles but testnet has its own prices, so paper fills will differ. A protective stop keeps its distance from the real fill. Equity in paper mode mixes testnet fills with mainnet marks, so paper P&L is only indicative until measured.
