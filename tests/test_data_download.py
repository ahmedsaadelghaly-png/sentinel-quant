from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import ccxt
import pytest
from conftest import HOUR_MS, T0, FakeExchange, bar, hourly, make_client, replay_exchange

from sentinel_quant.data.client import MarketDataError
from sentinel_quant.data.download import DownloadResult, download_symbol, fetch_range
from sentinel_quant.data.quality import check_ohlcv
from sentinel_quant.data.store import DatasetKey, DatasetStore

KEY = DatasetKey("binance", "BTC/USDT", "1h")
GRACE_MS = 2000


def run(
    exchange: Any,
    store: DatasetStore,
    start_ms: int = T0,
    end_ms: int | None = None,
    page_limit: int = 4,
    full: bool = False,
) -> DownloadResult:
    return download_symbol(
        make_client(exchange),
        store,
        KEY,
        start_ms=start_ms,
        end_ms=end_ms,
        page_limit=page_limit,
        grace_ms=GRACE_MS,
        full=full,
    )


def run_recorded(exchange: Any, store: DatasetStore, recorded: dict[str, Any]) -> DownloadResult:
    history = recorded["history"]
    return run(exchange, store, history["start_ms"], history["end_ms"], history["page_limit"])


def stored_times(store: DatasetStore, result: DownloadResult) -> list[int]:
    assert result.manifest is not None
    frame = store.load(result.manifest.dataset_id)
    return frame["timestamp"].dt.epoch("ms").to_list()


def test_recorded_mainnet_pages_are_stitched(tmp_path: Path, recorded: dict[str, Any]) -> None:
    store = DatasetStore(tmp_path)
    exchange = replay_exchange(recorded)
    result = run_recorded(exchange, store, recorded)
    assert result.status == "created"
    assert result.manifest is not None
    # 08:00-19:00 on 2023-03-24, minus the 13:00 bar lost to Binance's real outage.
    assert result.manifest.row_count == 11
    assert result.manifest.first_bar == datetime(2023, 3, 24, 8, tzinfo=UTC)
    assert result.manifest.last_bar == datetime(2023, 3, 24, 19, tzinfo=UTC)
    assert sum("klines" in url for url in exchange.requested_urls) == 3


def test_real_outage_is_reported_as_gap_and_zero_volume(
    tmp_path: Path, recorded: dict[str, Any]
) -> None:
    store = DatasetStore(tmp_path)
    result = run_recorded(replay_exchange(recorded), store, recorded)
    assert result.manifest is not None
    assert result.manifest.quality_status == "warn"
    manifest, frame = store.read_verified(result.manifest.dataset_id)
    report = check_ohlcv(frame, "1h", int(manifest.fetched_at.timestamp() * 1000))
    assert report.checks["gaps"] == 1
    assert report.gaps[0].after == datetime(2023, 3, 24, 12, tzinfo=UTC)
    assert report.checks["zero_volume_bars"] == 1


def test_rerun_with_recorded_data_is_a_noop(tmp_path: Path, recorded: dict[str, Any]) -> None:
    store = DatasetStore(tmp_path)
    first = run_recorded(replay_exchange(recorded), store, recorded)
    exchange = replay_exchange(recorded)
    second = run_recorded(exchange, store, recorded)
    assert second.status == "unchanged"
    assert second.manifest == first.manifest
    assert not any("klines" in url for url in exchange.requested_urls)
    versions = [p for p in (store.root / "binance/spot/BTC-USDT/1h").iterdir() if p.is_dir()]
    assert len(versions) == 1


def test_forming_bar_is_never_stored(tmp_path: Path) -> None:
    store = DatasetStore(tmp_path)
    now = T0 + 5 * HOUR_MS + 1_800_000
    result = run(FakeExchange(now, hourly(T0, 5)), store)
    assert stored_times(store, result) == [T0 + i * HOUR_MS for i in range(5)]


@pytest.mark.parametrize(
    ("offset_ms", "bars"),
    [(GRACE_MS - 1, 4), (GRACE_MS, 5)],
    ids=["inside-grace", "grace-elapsed"],
)
def test_bar_counts_as_closed_only_after_grace(tmp_path: Path, offset_ms: int, bars: int) -> None:
    store = DatasetStore(tmp_path)
    exchange = FakeExchange(T0 + 5 * HOUR_MS + offset_ms, hourly(T0, 5))
    assert len(stored_times(store, run(exchange, store))) == bars


def test_incremental_run_fetches_only_new_bars(tmp_path: Path) -> None:
    store = DatasetStore(tmp_path)
    bars = hourly(T0, 10)
    first = run(FakeExchange(T0 + 6 * HOUR_MS + 5000, bars[:6]), store)
    exchange = FakeExchange(T0 + 10 * HOUR_MS + 5000, bars)
    second = run(exchange, store)
    assert second.status == "created"
    assert second.bars_fetched == 4
    assert exchange.calls[0] == ("BTC/USDT", T0 + 6 * HOUR_MS)
    assert stored_times(store, second) == [T0 + i * HOUR_MS for i in range(10)]
    assert first.manifest is not None and second.manifest is not None
    assert second.manifest.parent_dataset_id == first.manifest.dataset_id


def test_incremental_equals_single_shot_download(tmp_path: Path) -> None:
    bars = hourly(T0, 10)
    now = T0 + 10 * HOUR_MS + 5000
    stepped = DatasetStore(tmp_path / "stepped")
    run(FakeExchange(T0 + 6 * HOUR_MS + 5000, bars[:6]), stepped)
    a = run(FakeExchange(now, bars), stepped)
    b = run(FakeExchange(now, bars), DatasetStore(tmp_path / "single"))
    assert a.manifest is not None and b.manifest is not None
    assert a.manifest.dataset_id == b.manifest.dataset_id


def test_earlier_start_extends_the_head(tmp_path: Path) -> None:
    store = DatasetStore(tmp_path)
    bars = hourly(T0, 8)
    now = T0 + 8 * HOUR_MS + 5000
    run(FakeExchange(now, bars), store, start_ms=T0 + 4 * HOUR_MS)
    result = run(FakeExchange(now, bars), store, start_ms=T0)
    assert result.bars_fetched == 4
    assert stored_times(store, result) == [T0 + i * HOUR_MS for i in range(8)]


def test_later_since_cannot_punch_a_hole(tmp_path: Path) -> None:
    store = DatasetStore(tmp_path)
    bars = hourly(T0, 10)
    run(FakeExchange(T0 + 3 * HOUR_MS + 5000, bars[:3]), store)
    result = run(FakeExchange(T0 + 10 * HOUR_MS + 5000, bars), store, start_ms=T0 + 8 * HOUR_MS)
    assert stored_times(store, result) == [T0 + i * HOUR_MS for i in range(10)]


def test_full_refresh_surfaces_restated_history(tmp_path: Path) -> None:
    store = DatasetStore(tmp_path)
    bars = hourly(T0, 5)
    now = T0 + 5 * HOUR_MS + 5000
    first = run(FakeExchange(now, bars), store)
    assert run(FakeExchange(now, bars), store, full=True).status == "unchanged"
    restated = [*bars[:2], bar(T0 + 2 * HOUR_MS, price=500.0), *bars[3:]]
    second = run(FakeExchange(now, restated), store, full=True)
    assert second.status == "created"
    assert first.manifest is not None and second.manifest is not None
    assert second.manifest.parent_dataset_id == first.manifest.dataset_id
    assert store.load(first.manifest.dataset_id).height == 5


def test_no_data_writes_nothing(tmp_path: Path) -> None:
    store = DatasetStore(tmp_path)
    result = run(FakeExchange(T0 + 3 * HOUR_MS + 5000, []), store, end_ms=T0 + 2 * HOUR_MS)
    assert result.status == "empty"
    assert store.latest(KEY) is None


def test_retry_mid_pagination_loses_and_repeats_nothing(tmp_path: Path) -> None:
    class FlakyOnce(FakeExchange):
        def fetch_ohlcv(self, symbol: str, timeframe: str, since: int, limit: int) -> Any:
            if len(self.calls) == 1:
                self.errors.append(ccxt.RequestTimeout("slow"))
            return super().fetch_ohlcv(symbol, timeframe, since, limit)

    store = DatasetStore(tmp_path)
    result = run(FlakyOnce(T0 + 10 * HOUR_MS + 5000, hourly(T0, 10)), store, page_limit=3)
    assert stored_times(store, result) == [T0 + i * HOUR_MS for i in range(10)]


def test_page_shorter_than_limit_does_not_end_the_download() -> None:
    class CappedPages(FakeExchange):
        def fetch_ohlcv(self, symbol: str, timeframe: str, since: int, limit: int) -> Any:
            return super().fetch_ohlcv(symbol, timeframe, since, 2)

    exchange = CappedPages(T0 + 9 * HOUR_MS, hourly(T0, 9))
    rows = fetch_range(make_client(exchange), "BTC/USDT", "1h", T0, T0 + 9 * HOUR_MS, 100)
    assert len(rows) == 9


def test_stalled_pagination_raises_instead_of_looping() -> None:
    class Stuck(FakeExchange):
        def fetch_ohlcv(self, symbol: str, timeframe: str, since: int, limit: int) -> Any:
            return [bar(T0)]

    with pytest.raises(MarketDataError, match="stalled"):
        fetch_range(make_client(Stuck(T0)), "BTC/USDT", "1h", T0 + HOUR_MS, T0 + 5 * HOUR_MS, 10)


def test_disorder_from_the_exchange_is_kept_and_fails_quality(tmp_path: Path) -> None:
    class Shuffled(FakeExchange):
        def fetch_ohlcv(self, symbol: str, timeframe: str, since: int, limit: int) -> Any:
            return list(reversed(super().fetch_ohlcv(symbol, timeframe, since, limit)))

    store = DatasetStore(tmp_path)
    result = run(Shuffled(T0 + 3 * HOUR_MS + 5000, hourly(T0, 3)), store, page_limit=10)
    assert result.manifest is not None
    assert result.manifest.quality_status == "fail"
