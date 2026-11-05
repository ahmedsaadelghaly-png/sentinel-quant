"""Versioned, immutable Parquet storage for OHLCV datasets.

Layout::

    <data_dir>/ohlcv/<exchange>/spot/<BASE-QUOTE>/<timeframe>/
        latest.json                     pointer to the newest version
        <dataset_id>/ohlcv.parquet      bars, exactly as received
        <dataset_id>/manifest.json      lineage and checksums
        <dataset_id>/quality.json       quality report for this version

A dataset id is derived from the bar values, so identical content always gets the
same id and a version directory never changes once written.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import polars as pl
import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict

from sentinel_quant.data.quality import QualityReport

SCHEMA_VERSION = 1
MARKET_TYPE = "spot"
PARQUET_NAME = "ohlcv.parquet"
MANIFEST_NAME = "manifest.json"
QUALITY_NAME = "quality.json"
LATEST_NAME = "latest.json"

OHLCV_SCHEMA: dict[str, Any] = {
    "timestamp": pl.Datetime("ms", "UTC"),
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Float64,
}
_VALUE_COLUMNS = ("open", "high", "low", "close", "volume")
_DATASET_ID = re.compile(r"^[a-z0-9]+_spot_[A-Z0-9]+-[A-Z0-9]+_[0-9]+[mhd]_[0-9a-f]{12}$")
_HASH_CHUNK = 1 << 20


class DatasetError(RuntimeError):
    """A dataset is missing, corrupt, or refused by the quality gate."""


@dataclass(frozen=True)
class DatasetKey:
    exchange: str
    symbol: str
    timeframe: str

    @property
    def symbol_slug(self) -> str:
        return self.symbol.replace("/", "-")

    def directory(self, root: Path) -> Path:
        return root / self.exchange / MARKET_TYPE / self.symbol_slug / self.timeframe

    def dataset_id(self, content_sha256: str) -> str:
        return (
            f"{self.exchange}_{MARKET_TYPE}_{self.symbol_slug}_{self.timeframe}_"
            f"{content_sha256[:12]}"
        )


class Manifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_id: str
    schema_version: int
    exchange: str
    market_type: str
    symbol: str
    timeframe: str
    source: str
    library_version: str
    parent_dataset_id: str | None
    fetched_at: datetime  # exchange time when the newest bars were fetched
    row_count: int
    first_bar: datetime
    last_bar: datetime
    content_sha256: str  # bar values: independent of Parquet encoding
    file_sha256: str  # the Parquet file: detects corruption or tampering
    quality_status: str


def frame_from_rows(rows: Sequence[Sequence[Any]]) -> pl.DataFrame:
    """Build a typed UTC frame, keeping row order, duplicates and bad values as received."""
    columns = list(zip(*rows, strict=True)) if rows else [()] * 6
    data: dict[str, pl.Series] = {
        "timestamp": pl.Series("timestamp", columns[0], dtype=pl.Int64, strict=False)
    }
    for index, name in enumerate(_VALUE_COLUMNS, start=1):
        data[name] = pl.Series(name, columns[index], dtype=pl.Float64, strict=False)
    return pl.DataFrame(data).with_columns(
        pl.col("timestamp").cast(pl.Datetime("ms")).dt.replace_time_zone("UTC")
    )


def content_sha256(df: pl.DataFrame) -> str:
    """Hash bar values in stored order, as little-endian int64/float64 columns."""
    digest = hashlib.sha256(f"sentinel-quant-ohlcv-v{SCHEMA_VERSION}\n".encode())
    stamps = df["timestamp"].dt.epoch("ms").to_list()
    digest.update(struct.pack(f"<{len(stamps)}q", *stamps))
    for name in _VALUE_COLUMNS:
        values = df[name].fill_null(float("nan")).to_list()
        digest.update(struct.pack(f"<{len(values)}d", *values))
    return digest.hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _bar_time(df: pl.DataFrame, reducer: Literal["min", "max"]) -> datetime:
    value = df["timestamp"].min() if reducer == "min" else df["timestamp"].max()
    if not isinstance(value, datetime):
        raise DatasetError("cannot store an empty dataset")
    return value.astimezone(UTC)


class DatasetStore:
    def __init__(self, data_dir: str | Path) -> None:
        self.root = Path(data_dir) / "ohlcv"

    def latest(self, key: DatasetKey) -> Manifest | None:
        pointer = key.directory(self.root) / LATEST_NAME
        if not pointer.is_file():
            return None
        dataset_id = json.loads(pointer.read_text(encoding="utf-8"))["dataset_id"]
        return self._read_manifest(key.directory(self.root) / dataset_id)

    def manifest(self, dataset_id: str) -> Manifest:
        return self._read_manifest(self._find(dataset_id))

    def save(
        self,
        key: DatasetKey,
        df: pl.DataFrame,
        report: QualityReport,
        *,
        source: str,
        library_version: str,
        parent_dataset_id: str | None,
        fetched_at: datetime,
    ) -> tuple[Manifest, bool]:
        """Persist a version and point ``latest`` at it. Returns (manifest, created)."""
        content = content_sha256(df)
        dataset_id = key.dataset_id(content)
        base = key.directory(self.root)
        target = base / dataset_id
        if target.is_dir():
            manifest = self._read_manifest(target)
            self._set_latest(base, dataset_id)
            return manifest, False

        base.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=base))
        try:
            parquet = staging / PARQUET_NAME
            df.write_parquet(parquet, compression="zstd", statistics=True)
            manifest = Manifest(
                dataset_id=dataset_id,
                schema_version=SCHEMA_VERSION,
                exchange=key.exchange,
                market_type=MARKET_TYPE,
                symbol=key.symbol,
                timeframe=key.timeframe,
                source=source,
                library_version=library_version,
                parent_dataset_id=parent_dataset_id,
                fetched_at=fetched_at,
                row_count=df.height,
                first_bar=_bar_time(df, "min"),
                last_bar=_bar_time(df, "max"),
                content_sha256=content,
                file_sha256=_file_sha256(parquet),
                quality_status=report.status,
            )
            (staging / MANIFEST_NAME).write_text(
                manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
            )
            (staging / QUALITY_NAME).write_text(
                report.model_dump_json(indent=2) + "\n", encoding="utf-8"
            )
            staging.chmod(0o755)
            staging.rename(target)  # atomic: a crash never leaves a half-written version
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        self._set_latest(base, dataset_id)
        return manifest, True

    def read_verified(self, dataset_id: str) -> tuple[Manifest, pl.DataFrame]:
        """Read any version after checking its checksums, whatever its quality status."""
        directory = self._find(dataset_id)
        manifest = self._read_manifest(directory)
        parquet = directory / PARQUET_NAME
        if _file_sha256(parquet) != manifest.file_sha256:
            raise DatasetError(f"file checksum mismatch: {dataset_id}")
        if pq.read_metadata(parquet).num_rows != manifest.row_count:
            raise DatasetError(f"row count mismatch: {dataset_id}")
        df = pl.read_parquet(parquet)
        if content_sha256(df) != manifest.content_sha256:
            raise DatasetError(f"content checksum mismatch: {dataset_id}")
        return manifest, df

    def load(self, dataset_id: str) -> pl.DataFrame:
        """Read a version for research use. Datasets that failed quality are refused."""
        manifest, df = self.read_verified(dataset_id)
        if manifest.quality_status == "fail":
            raise DatasetError(f"dataset failed quality checks: {dataset_id}")
        return df

    def _find(self, dataset_id: str) -> Path:
        if not _DATASET_ID.fullmatch(dataset_id):
            raise DatasetError(f"malformed dataset id: {dataset_id!r}")
        exchange, market_type, symbol_slug, timeframe, _ = dataset_id.split("_")
        directory = self.root / exchange / market_type / symbol_slug / timeframe / dataset_id
        if not directory.is_dir():
            raise DatasetError(f"dataset not found: {dataset_id}")
        return directory

    @staticmethod
    def _read_manifest(directory: Path) -> Manifest:
        path = directory / MANIFEST_NAME
        if not path.is_file():
            raise DatasetError(f"manifest not found: {path}")
        return Manifest.model_validate_json(path.read_text(encoding="utf-8"))

    @staticmethod
    def _set_latest(base: Path, dataset_id: str) -> None:
        temporary = base / f".{LATEST_NAME}.tmp"
        temporary.write_text(json.dumps({"dataset_id": dataset_id}) + "\n", encoding="utf-8")
        os.replace(temporary, base / LATEST_NAME)
