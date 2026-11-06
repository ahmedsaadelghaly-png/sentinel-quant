# ADR 0006 — Local control panel

- Status: accepted
- Date: 2026-11-06

## Decision
- **FastAPI, one static page, no build step.** Enough for an internal panel, and it keeps the frontend free of a toolchain.
- **Holds no trading logic.** It acts through existing safeguards: the kill switch file, a stop file, and limit requests the risk engine applies by its own rules.
- **Binds to 127.0.0.1.** That alone is not enough, since any website can make a browser send requests to localhost. Host checks block DNS rebinding, and actions need a custom header and a local Origin.
- **Real data only.** Empty states say so, and a position with no price shows no equity rather than a wrong one.
- **Log text is rendered with `textContent`,** never as HTML.
- **A PID lock** stops two services sharing one ledger.

## Consequences
No login: anyone with a local account on this machine can use it. It must not be exposed over a network or a tunnel. The reference design was unavailable, so the layout follows the written plan.
