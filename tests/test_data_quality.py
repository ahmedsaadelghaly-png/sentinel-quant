from datetime import UTC, datetime
from typing import Any

import polars as pl
import pytest
from conftest import HOUR_MS, T0, bar, hourly

from sentinel_quant.data.quality import ERROR_CHECKS, QualityReport, check_ohlcv, render_text
from sentinel_quant.data.store import frame_from_rows

AS_OF = T0 + 1000 * HOUR_MS


def run(rows: list[list[Any]]) -> QualityReport:
    return check_ohlcv(frame_from_rows(rows), "1h", AS_OF)


def test_clean_data_passes() -> None:
    report = run(hourly(T0, 24))
    assert report.status == "pass"
    assert not any(report.checks.values())
    assert report.coverage_pct == 100.0
    assert report.first_bar == datetime.fromtimestamp(T0 / 1000, tz=UTC)


def test_gap_is_located_and_counted() -> None:
    rows = hourly(T0, 3) + hourly(T0 + 6 * HOUR_MS, 2)
    report = run(rows)
    assert report.status == "warn"
    assert report.checks["gaps"] == 1
    assert report.missing_bars == 3
    assert report.expected_bars == 8
    assert report.coverage_pct == 62.5
    gap = report.gaps[0]
    assert gap.after == datetime.fromtimestamp((T0 + 2 * HOUR_MS) / 1000, tz=UTC)
    assert gap.before == datetime.fromtimestamp((T0 + 6 * HOUR_MS) / 1000, tz=UTC)


def test_duplicates_fail_without_being_repaired() -> None:
    rows = hourly(T0, 3)
    report = run([*rows, rows[-1]])
    assert report.status == "fail"
    assert report.checks["duplicate_bars"] == 1
    assert report.checks["out_of_order_bars"] == 0
    assert report.rows == 4


def test_out_of_order_fails_and_is_not_reported_as_a_gap() -> None:
    a, b, c = hourly(T0, 3)
    report = run([a, c, b])
    assert report.status == "fail"
    assert report.checks["out_of_order_bars"] == 1
    assert report.checks["gaps"] == 0


@pytest.mark.parametrize("value", [0.0, -1.0])
@pytest.mark.parametrize("column", [1, 2, 3, 4])
def test_zero_and_negative_prices_fail(column: int, value: float) -> None:
    rows = hourly(T0, 3)
    rows[1][column] = value
    report = run(rows)
    assert report.status == "fail"
    assert report.checks["nonpositive_prices"] == 1


@pytest.mark.parametrize("value", [None, float("nan")])
def test_missing_prices_fail(value: float | None) -> None:
    rows = hourly(T0, 3)
    rows[1][4] = value
    assert run(rows).checks["null_prices"] == 1


def test_inconsistent_ohlc_fails() -> None:
    assert run([[T0, 100.0, 99.0, 98.0, 100.0, 1.0]]).checks["inconsistent_ohlc"] == 1
    assert run([[T0, 100.0, 102.0, 101.0, 100.0, 1.0]]).checks["inconsistent_ohlc"] == 1


def test_negative_volume_fails_zero_volume_warns() -> None:
    assert run([bar(T0, volume=-1.0)]).status == "fail"
    report = run([bar(T0, volume=0.0)])
    assert report.status == "warn"
    assert report.checks["zero_volume_bars"] == 1


def test_non_utc_timestamps_fail() -> None:
    utc = frame_from_rows(hourly(T0, 3))
    for frame in (
        utc.with_columns(pl.col("timestamp").dt.replace_time_zone(None)),
        utc.with_columns(pl.col("timestamp").dt.convert_time_zone("Africa/Cairo")),
    ):
        report = check_ohlcv(frame, "1h", AS_OF)
        assert report.status == "fail"
        assert report.checks["timezone_not_utc"] == 1


def test_bar_off_the_timeframe_grid_fails() -> None:
    # What a local-time or half-hour-offset feed looks like.
    assert run([bar(T0 + 30 * 60_000)]).checks["misaligned_bars"] == 1


def test_unclosed_bar_fails() -> None:
    rows = hourly(T0, 2)
    last_close = T0 + 2 * HOUR_MS
    frame = frame_from_rows(rows)
    assert check_ohlcv(frame, "1h", last_close).checks["unclosed_bars"] == 0
    assert check_ohlcv(frame, "1h", last_close - 1).checks["unclosed_bars"] == 1


def test_empty_frame_fails() -> None:
    assert run([]).status == "fail"


def test_samples_are_capped() -> None:
    rows = [bar(T0 + i * HOUR_MS, volume=-1.0) for i in range(50)]
    report = run(rows)
    assert report.checks["negative_volume"] == 50
    assert len(report.samples["negative_volume"]) == 20


def test_text_rendering_lists_every_check() -> None:
    text = render_text(run(hourly(T0, 3) + hourly(T0 + 5 * HOUR_MS, 1)), "BTC/USDT")
    assert "WARN" in text
    assert "gap:" in text
    assert all(name in text for name in ERROR_CHECKS)
