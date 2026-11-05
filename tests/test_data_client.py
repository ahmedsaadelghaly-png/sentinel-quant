from typing import Any

import ccxt
import pytest
from conftest import T0, FakeExchange, hourly, make_client, replay_exchange

from sentinel_quant.config import AppConfig
from sentinel_quant.data.client import MarketDataClient, MarketDataError, build_public_exchange


def test_public_client_is_keyless_spot_mainnet() -> None:
    client = MarketDataClient.from_config(AppConfig())  # default config has testnet: true
    exchange = client._exchange
    assert not exchange.apiKey
    assert not exchange.secret
    assert exchange.enableRateLimit is True
    assert exchange.options["defaultType"] == "spot"
    assert exchange.urls["api"]["public"].startswith("https://api.binance.com")


def test_unknown_exchange_is_rejected() -> None:
    with pytest.raises(MarketDataError, match="unknown exchange"):
        build_public_exchange("Exchange")


def test_validate_against_recorded_markets(recorded: dict[str, Any]) -> None:
    client = make_client(replay_exchange(recorded))
    client.validate(["BTC/USDT", "ETH/USDT"], "1h")
    with pytest.raises(MarketDataError, match="unknown symbol"):
        client.validate(["DOGE/NOPE"], "1h")
    with pytest.raises(MarketDataError, match="timeframe"):
        client.validate(["BTC/USDT"], "7h")


def test_market_load_requests_spot_only(recorded: dict[str, Any]) -> None:
    exchange = replay_exchange(recorded)
    make_client(exchange).validate(["BTC/USDT"], "1h")
    assert all("api.binance.com/api/v3" in url for url in exchange.requested_urls)


def test_transient_errors_back_off_then_succeed(sleeps: list[float]) -> None:
    exchange = FakeExchange(T0 + 7_200_000, hourly(T0, 2))
    exchange.errors = [ccxt.RequestTimeout("slow"), ccxt.ExchangeNotAvailable("502")]
    rows = make_client(exchange, sleeps).fetch_ohlcv("BTC/USDT", "1h", T0, 10)
    assert len(rows) == 3
    assert sleeps == [1.0, 2.0]


def test_backoff_is_capped(sleeps: list[float]) -> None:
    exchange = FakeExchange(T0)
    exchange.errors = [ccxt.NetworkError("x") for _ in range(10)]
    with pytest.raises(MarketDataError, match="after 3 retries"):
        make_client(exchange, sleeps).fetch_ohlcv("BTC/USDT", "1h", T0, 10)
    assert sleeps == [1.0, 2.0, 4.0]
    assert len(exchange.calls) == 4


def test_rate_limit_honours_retry_after(sleeps: list[float]) -> None:
    exchange = FakeExchange(T0)
    exchange.errors = [ccxt.RateLimitExceeded("429")]
    exchange.last_response_headers = {"Retry-After": "7"}
    make_client(exchange, sleeps).fetch_ohlcv("BTC/USDT", "1h", T0, 10)
    assert sleeps == [7.0]


def test_stale_retry_after_is_ignored_for_network_errors(sleeps: list[float]) -> None:
    exchange = FakeExchange(T0)
    exchange.errors = [ccxt.RequestTimeout("slow")]
    exchange.last_response_headers = {"Retry-After": "7"}
    make_client(exchange, sleeps).fetch_ohlcv("BTC/USDT", "1h", T0, 10)
    assert sleeps == [1.0]


def test_ip_ban_stops_instead_of_hammering(sleeps: list[float]) -> None:
    exchange = FakeExchange(T0)
    exchange.errors = [ccxt.DDoSProtection("418")]
    exchange.last_response_headers = {"retry-after": "3600"}
    with pytest.raises(MarketDataError, match="3600s wait"):
        make_client(exchange, sleeps).fetch_ohlcv("BTC/USDT", "1h", T0, 10)
    assert sleeps == []
    assert len(exchange.calls) == 1


def test_permanent_errors_are_not_retried(sleeps: list[float]) -> None:
    exchange = FakeExchange(T0)
    exchange.errors = [ccxt.BadSymbol("nope")]
    with pytest.raises(MarketDataError, match="nope"):
        make_client(exchange, sleeps).fetch_ohlcv("BTC/USDT", "1h", T0, 10)
    assert sleeps == []
