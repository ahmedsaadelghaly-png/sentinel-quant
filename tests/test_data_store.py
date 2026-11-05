from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from conftest import T0, bar, hourly

from sentinel_quant.data.quality import check_ohlcv
from sentinel_quant.data.store import (
    MANIFEST_NAME,
    OHLCV_SCHEMA,
    PARQUET_NAME,
    QUALITY_NAME,
    DatasetError,
    DatasetKey,
    DatasetStore,
    Manifest,
    content_sha256,
    frame_from_rows,
)

KEY = DatasetKey("binance", "BTC/USDT", "1h")
AS_OF = T0 + 10_000 * 3_600_000


def save(
    store: DatasetStore, rows: list[list[Any]], parent: str | None = None
) -> tuple[Manifest, bool]:
    frame = frame_from_rows(rows)
    return store.save(
        KEY,
        frame,
        check_ohlcv(frame, "1h", AS_OF),
        source="public-mainnet",
        library_version="ccxt-test",
        parent_dataset_id=parent,
        fetched_at=datetime.fromtimestamp(AS_OF / 1000, tz=UTC),
    )


def test_layout_and_manifest(tmp_path: Path) -> None:
    store = DatasetStore(tmp_path)
    manifest, created = save(store, hourly(T0, 5))
    assert created
    directory = tmp_path / "ohlcv/binance/spot/BTC-USDT/1h" / manifest.dataset_id
    assert {p.name for p in directory.iterdir()} == {PARQUET_NAME, MANIFEST_NAME, QUALITY_NAME}
    assert manifest.dataset_id.startswith("binance_spot_BTC-USDT_1h_")
    assert manifest.dataset_id.endswith(manifest.content_sha256[:12])
    assert manifest.row_count == 5
    assert manifest.source == "public-mainnet"
    assert store.latest(KEY) == manifest


def test_round_trip_preserves_utc_schema_and_values(tmp_path: Path) -> None:
    store = DatasetStore(tmp_path)
    original = frame_from_rows(hourly(T0, 5))
    manifest, _ = save(store, hourly(T0, 5))
    loaded = store.load(manifest.dataset_id)
    assert dict(loaded.schema) == OHLCV_SCHEMA
    assert loaded.equals(original)


def test_same_content_same_id_and_no_rewrite(tmp_path: Path) -> None:
    store = DatasetStore(tmp_path)
    first, _ = save(store, hourly(T0, 5))
    parquet = store.root / "binance/spot/BTC-USDT/1h" / first.dataset_id / PARQUET_NAME
    stamp = parquet.stat().st_mtime_ns
    second, created = save(store, hourly(T0, 5))
    assert not created
    assert second == first
    assert parquet.stat().st_mtime_ns == stamp


def test_changed_content_is_a_new_version_and_old_one_survives(tmp_path: Path) -> None:
    store = DatasetStore(tmp_path)
    first, _ = save(store, hourly(T0, 5))
    second, created = save(store, hourly(T0, 6), parent=first.dataset_id)
    assert created
    assert second.dataset_id != first.dataset_id
    assert second.parent_dataset_id == first.dataset_id
    assert store.latest(KEY) == second
    assert store.load(first.dataset_id).height == 5


def test_content_hash_ignores_parquet_encoding(tmp_path: Path) -> None:
    frame = frame_from_rows(hourly(T0, 50))
    path = tmp_path / "other.parquet"
    frame.write_parquet(path, compression="uncompressed")
    assert content_sha256(pl.read_parquet(path)) == content_sha256(frame)


def test_content_hash_sees_row_order() -> None:
    a, b = hourly(T0, 2)
    assert content_sha256(frame_from_rows([a, b])) != content_sha256(frame_from_rows([b, a]))


def test_tampered_file_is_refused(tmp_path: Path) -> None:
    store = DatasetStore(tmp_path)
    manifest, _ = save(store, hourly(T0, 5))
    parquet = store.root / "binance/spot/BTC-USDT/1h" / manifest.dataset_id / PARQUET_NAME
    frame_from_rows(hourly(T0, 4)).write_parquet(parquet)
    with pytest.raises(DatasetError, match="file checksum"):
        store.load(manifest.dataset_id)


def test_failed_dataset_is_refused_for_research_but_readable_for_diagnosis(tmp_path: Path) -> None:
    store = DatasetStore(tmp_path)
    manifest, _ = save(store, [bar(T0, price=-5.0)])
    assert manifest.quality_status == "fail"
    with pytest.raises(DatasetError, match="failed quality"):
        store.load(manifest.dataset_id)
    assert store.read_verified(manifest.dataset_id)[1].height == 1


@pytest.mark.parametrize("bad", ["../../etc/passwd", "binance_spot_BTC-USDT_1h_XYZ", ""])
def test_malformed_ids_are_rejected(tmp_path: Path, bad: str) -> None:
    with pytest.raises(DatasetError, match="malformed"):
        DatasetStore(tmp_path).load(bad)


def test_missing_dataset(tmp_path: Path) -> None:
    with pytest.raises(DatasetError, match="not found"):
        DatasetStore(tmp_path).load(KEY.dataset_id("0" * 64))


def test_crash_while_writing_leaves_no_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = DatasetStore(tmp_path)

    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(pl.DataFrame, "write_parquet", boom)
    with pytest.raises(OSError, match="disk full"):
        save(store, hourly(T0, 5))
    assert store.latest(KEY) is None
    assert list((store.root / "binance/spot/BTC-USDT/1h").iterdir()) == []
