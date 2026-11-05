"""Record real public Binance responses for offline tests (the only network path in tests).

Run manually: python scripts/record_fixtures.py
Uses public endpoints only, no credentials. Output: tests/fixtures/binance_spot.json
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sentinel_quant.data.client import build_public_exchange

OUTPUT = Path(__file__).resolve().parents[1] / "tests/fixtures/binance_spot.json"
KEEP_MARKETS = {"BTCUSDT", "ETHUSDT"}
HOUR_MS = 3_600_000
PAGE = 5
# 2023-03-24: Binance halted spot trading for a matching engine fault.
HISTORY_START = datetime(2023, 3, 24, 8, tzinfo=UTC)
HISTORY_END = datetime(2023, 3, 24, 20, tzinfo=UTC)


def main() -> None:
    exchange = build_public_exchange("binance")
    recorded: dict[str, Any] = {}
    real_fetch = exchange.fetch

    def recording_fetch(
        url: str, method: str = "GET", headers: Any = None, body: Any = None
    ) -> Any:
        response = real_fetch(url, method, headers, body)
        if url.endswith("/exchangeInfo"):
            response = {
                **response,
                "symbols": [s for s in response["symbols"] if s["symbol"] in KEEP_MARKETS],
                "rateLimits": [],
                "exchangeFilters": [],
            }
        recorded[url] = response
        return response

    exchange.fetch = recording_fetch
    exchange.load_markets()

    start = int(HISTORY_START.timestamp() * 1000)
    end = int(HISTORY_END.timestamp() * 1000)
    cursor = start
    while cursor < end:
        page = exchange.fetch_ohlcv("BTC/USDT", "1h", since=cursor, limit=PAGE)
        cursor = int(page[-1][0]) + HOUR_MS

    # A live snapshot: the last row is the bar still forming when recorded.
    server_time = exchange.fetch_time()
    live_since = server_time // HOUR_MS * HOUR_MS - 2 * HOUR_MS
    live = exchange.fetch_ohlcv("BTC/USDT", "1h", since=live_since, limit=PAGE)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(
            {
                "history": {"start_ms": start, "end_ms": end, "page_limit": PAGE},
                "live": {"server_time_ms": server_time, "since_ms": live_since, "rows": live},
                "responses": recorded,
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUTPUT} ({OUTPUT.stat().st_size} bytes, {len(recorded)} responses)")


if __name__ == "__main__":
    main()
