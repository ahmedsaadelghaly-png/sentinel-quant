"""Paginated, idempotent historical OHLCV download."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import polars as pl

from sentinel_quant.data.client import MarketDataClient, MarketDataError, OhlcvRow
from sentinel_quant.data.quality import check_ohlcv
from sentinel_quant.data.store import DatasetKey, DatasetStore, Manifest, frame_from_rows
from sentinel_quant.data.timeframes import closed_cutoff_ms, timeframe_ms
from sentinel_quant.ops.logging import get_logger

SOURCE = "public-mainnet"


@dataclass(frozen=True)
class DownloadResult:
    key: DatasetKey
    status: Literal["created", "unchanged", "empty"]
    bars_fetched: int
    manifest: Manifest | None


def fetch_range(
    client: MarketDataClient,
    symbol: str,
    timeframe: str,
    start_ms: int,
    end_ms: int,
    page_limit: int,
) -> list[OhlcvRow]:
    """Fetch bars with ``start_ms <= open time < end_ms``, keeping them as received.

    A short page does not end the loop, since exchanges may cap pages below
    ``limit``. Only an empty page or reaching ``end_ms`` does.
    """
    tf_ms = timeframe_ms(timeframe)
    rows: list[OhlcvRow] = []
    cursor = start_ms
    while cursor < end_ms:
        page = client.fetch_ohlcv(symbol, timeframe, cursor, page_limit)
        if not page:
            break
        newest = max(int(row[0]) for row in page)
        if newest < cursor:
            raise MarketDataError(f"pagination stalled for {symbol} at {cursor}: {newest}")
        rows.extend(row for row in page if start_ms <= int(row[0]) < end_ms)
        cursor = newest + tf_ms
    return rows


def _epoch_ms(value: Any) -> int:
    if not isinstance(value, datetime):
        raise TypeError(f"expected datetime, got {type(value).__name__}")
    return int(value.timestamp() * 1000)


def download_symbol(
    client: MarketDataClient,
    store: DatasetStore,
    key: DatasetKey,
    *,
    start_ms: int,
    end_ms: int | None,
    page_limit: int,
    grace_ms: int,
    full: bool = False,
) -> DownloadResult:
    """Bring the stored dataset up to the requested range.

    By default only missing bars before and after the stored range are fetched, so
    the dataset stays contiguous and an up-to-date re-run writes nothing. ``full``
    fetches the whole range again, which is how exchange restatements surface.
    """
    log = get_logger()
    tf_ms = timeframe_ms(key.timeframe)
    now_ms = client.server_time_ms()
    cutoff = closed_cutoff_ms(now_ms, tf_ms, grace_ms)
    end = cutoff if end_ms is None else min(end_ms // tf_ms * tf_ms, cutoff)
    start = -(-start_ms // tf_ms) * tf_ms  # first bar at or after start_ms

    previous = store.latest(key)
    if previous is None or full:
        rows = fetch_range(client, key.symbol, key.timeframe, start, end, page_limit)
        if not rows:
            return DownloadResult(key, "empty", 0, previous)
        frame = frame_from_rows(rows)
        fetched = len(rows)
    else:
        existing = store.read_verified(previous.dataset_id)[1]
        first = _epoch_ms(existing["timestamp"].min())
        last = _epoch_ms(existing["timestamp"].max())
        head = fetch_range(client, key.symbol, key.timeframe, start, first, page_limit)
        tail = fetch_range(client, key.symbol, key.timeframe, last + tf_ms, end, page_limit)
        fetched = len(head) + len(tail)
        if fetched == 0:
            return DownloadResult(key, "unchanged", 0, previous)
        frame = pl.concat([frame_from_rows(head), existing, frame_from_rows(tail)])

    report = check_ohlcv(frame, key.timeframe, now_ms)
    manifest, created = store.save(
        key,
        frame,
        report,
        source=SOURCE,
        library_version=f"ccxt-{client.library_version}",
        parent_dataset_id=previous.dataset_id if previous else None,
        fetched_at=datetime.fromtimestamp(now_ms / 1000, tz=UTC),
    )
    log.info(
        "dataset_saved" if created else "dataset_unchanged",
        dataset_id=manifest.dataset_id,
        rows=manifest.row_count,
        bars_fetched=fetched,
        quality=manifest.quality_status,
    )
    return DownloadResult(key, "created" if created else "unchanged", fetched, manifest)
