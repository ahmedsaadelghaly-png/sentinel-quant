# ADR 0004 — Daily risk controller and kill switch

- Status: accepted
- Date: 2026-11-06

## Decision
- **Entries are judged on projected worst-case loss:** equity, minus the stop loss of every open and pending position, minus this order's. A position with no stop counts as losing its full value. Entries without a stop are refused.
- **A breach of the daily loss limit always wins,** even during a softer halt, because only it forces positions closed.
- **Exits are always allowed, except by the kill switch.** M4 requires that it blocks everything. Resting stops at the exchange are not cancelled by it.
- **The kill switch is a file:** it survives restarts, works if the bot misbehaves, and an unreadable flag counts as engaged.
- **Risk state is persisted.** Otherwise a restart would reset the day's limits.
- **Sizing depends only on equity and stop distance,** never on progress towards a target (rule 7).

## Consequences
A gap can jump a stop and lose more than the daily limit: the limit caps planned risk, and `flatten_required` handles realised breaches. Approved entries count against the daily limit even if the fill is later refused, which errs on the safe side.
