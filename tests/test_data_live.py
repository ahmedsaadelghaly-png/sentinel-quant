import threading
from typing import Any

import ccxt
from conftest import HOUR_MS, T0, FakeExchange, bar, hourly, make_client, replay_exchange

from sentinel_quant.data.live import ClosedCandlePoller

GRACE_MS = 2000


def poller(
    exchange: Any, symbols: tuple[str, ...] = ("BTC/USDT",), **kwargs: Any
) -> ClosedCandlePoller:
    return ClosedCandlePoller(
        make_client(exchange),
        symbols,
        "1h",
        grace_ms=GRACE_MS,
        page_limit=100,
        retry_seconds=10.0,
        **kwargs,
    )


def test_recorded_forming_bar_is_dropped(recorded: dict[str, Any]) -> None:
    live = recorded["live"]
    rows = live["rows"]
    last_closed = rows[-2][0]
    now = live["server_time_ms"]
    assert rows[-1][0] + HOUR_MS > now, "fixture must end with a forming bar"

    class Snapshot(FakeExchange):
        def fetch_ohlcv(self, symbol: str, timeframe: str, since: int, limit: int) -> Any:
            return [r for r in rows if r[0] >= since]

    candles = poller(Snapshot(now), start_after={"BTC/USDT": rows[0][0]}).poll_once()
    assert [c.open_time_ms for c in candles] == [last_closed]
    assert candles[0].close == rows[-2][4]


def test_replayed_ccxt_rows_convert(recorded: dict[str, Any]) -> None:
    exchange = replay_exchange(recorded)
    exchange.load_markets()
    live = recorded["live"]
    rows = make_client(exchange).fetch_ohlcv("BTC/USDT", "1h", live["since_ms"], 5)
    assert rows == live["rows"]


def test_first_poll_starts_at_latest_closed_bar() -> None:
    exchange = FakeExchange(T0 + 5 * HOUR_MS + 60_000, hourly(T0, 5))
    candles = poller(exchange).poll_once()
    assert [c.open_time_ms for c in candles] == [T0 + 4 * HOUR_MS]


def test_each_bar_is_emitted_exactly_once() -> None:
    exchange = FakeExchange(T0 + 5 * HOUR_MS + 60_000, hourly(T0, 5))
    p = poller(exchange)
    assert len(p.poll_once()) == 1
    assert p.poll_once() == []
    exchange.bars = hourly(T0, 6)
    exchange.now_ms = T0 + 6 * HOUR_MS + 60_000
    assert [c.open_time_ms for c in p.poll_once()] == [T0 + 5 * HOUR_MS]
    assert p.poll_once() == []


def test_no_request_is_made_while_no_new_bar_can_be_closed() -> None:
    exchange = FakeExchange(T0 + 5 * HOUR_MS + 60_000, hourly(T0, 5))
    p = poller(exchange)
    p.poll_once()
    exchange.calls.clear()
    exchange.now_ms += 30 * 60_000
    p.poll_once()
    assert exchange.calls == []


def test_bar_is_withheld_until_grace_has_passed() -> None:
    close = T0 + 2 * HOUR_MS
    exchange = FakeExchange(close + GRACE_MS - 1, hourly(T0, 2))
    p = poller(exchange, start_after={"BTC/USDT": T0})
    assert p.poll_once() == []
    exchange.now_ms = close + GRACE_MS
    assert [c.open_time_ms for c in p.poll_once()] == [T0 + HOUR_MS]


def test_closure_uses_exchange_time_not_local_clock() -> None:
    # Exchange time says the hour is unfinished. The test's wall clock is years later.
    exchange = FakeExchange(T0 + HOUR_MS + 1_800_000, hourly(T0, 2))
    p = poller(exchange, start_after={"BTC/USDT": T0})
    assert p.poll_once() == []


def test_downtime_is_caught_up_in_order() -> None:
    exchange = FakeExchange(T0 + 6 * HOUR_MS + 60_000, hourly(T0, 6))
    p = poller(exchange, start_after={"BTC/USDT": T0 + HOUR_MS})
    assert [c.open_time_ms for c in p.poll_once()] == [T0 + i * HOUR_MS for i in range(2, 6)]


def test_exchange_gap_skips_ahead_without_blocking() -> None:
    bars = hourly(T0, 2) + hourly(T0 + 4 * HOUR_MS, 2)
    exchange = FakeExchange(T0 + 6 * HOUR_MS + 60_000, bars)
    candles = poller(exchange, start_after={"BTC/USDT": T0}).poll_once()
    assert [c.open_time_ms for c in candles] == [
        T0 + HOUR_MS,
        T0 + 4 * HOUR_MS,
        T0 + 5 * HOUR_MS,
    ]


def test_invalid_bar_is_withheld_and_not_retried() -> None:
    bars = [*hourly(T0, 2), bar(T0 + 2 * HOUR_MS, price=-1.0), *hourly(T0 + 3 * HOUR_MS, 1)]
    exchange = FakeExchange(T0 + 4 * HOUR_MS + 60_000, bars)
    p = poller(exchange, start_after={"BTC/USDT": T0 + HOUR_MS})
    assert [c.open_time_ms for c in p.poll_once()] == [T0 + 3 * HOUR_MS]
    assert p.poll_once() == []


def test_failing_symbol_does_not_lose_bars_of_the_other() -> None:
    exchange = FakeExchange(T0 + 3 * HOUR_MS + 60_000, hourly(T0, 3))
    exchange.fail_symbols["ETH/USDT"] = ccxt.BadSymbol("down")
    start = {"BTC/USDT": T0, "ETH/USDT": T0}
    p = poller(exchange, ("BTC/USDT", "ETH/USDT"), start_after=start)
    assert {c.symbol for c in p.poll_once()} == {"BTC/USDT"}
    exchange.fail_symbols.clear()
    recovered = p.poll_once()
    assert [(c.symbol, c.open_time_ms) for c in recovered] == [
        ("ETH/USDT", T0 + HOUR_MS),
        ("ETH/USDT", T0 + 2 * HOUR_MS),
    ]


class ScriptedStop(threading.Event):
    """Runs a callback for each wait, instead of really sleeping."""

    def __init__(self, exchange: FakeExchange, rounds: int) -> None:
        super().__init__()
        self.exchange = exchange
        self.rounds = rounds
        self.waits: list[float] = []

    def wait(self, timeout: float | None = None) -> bool:
        assert timeout is not None
        self.waits.append(timeout)
        self.exchange.now_ms += int(timeout * 1000)
        self.exchange.bars = hourly(T0, self.exchange.now_ms // HOUR_MS - T0 // HOUR_MS)
        self.rounds -= 1
        if self.rounds <= 0:
            self.set()
        return self.is_set()


def test_stream_sleeps_until_next_close_and_emits_in_sequence() -> None:
    exchange = FakeExchange(T0 + 2 * HOUR_MS + 60_000, hourly(T0, 2))
    stop = ScriptedStop(exchange, rounds=3)
    p = poller(exchange, start_after={"BTC/USDT": T0})
    candles = list(p.stream(stop))
    assert [c.open_time_ms for c in candles] == [T0 + i * HOUR_MS for i in range(1, 4)]
    assert stop.waits[0] == (HOUR_MS - 60_000 + GRACE_MS) / 1000
    assert stop.waits[1] == HOUR_MS / 1000


def test_stream_survives_a_server_time_outage() -> None:
    class Down(FakeExchange):
        outages = 1

        def fetch_time(self) -> int:
            if self.outages:
                self.outages -= 1
                raise ccxt.BadResponse("bad gateway body")
            return super().fetch_time()

    exchange = Down(T0 + 2 * HOUR_MS + 60_000, hourly(T0, 2))
    stop = ScriptedStop(exchange, rounds=2)
    candles = list(poller(exchange, start_after={"BTC/USDT": T0}).stream(stop))
    assert [c.open_time_ms for c in candles] == [T0 + HOUR_MS]
    assert stop.waits[0] == 10.0
