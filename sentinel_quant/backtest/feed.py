"""Load versioned datasets for a backtest. Only the store's quality gate lets data in."""

from __future__ import annotations

from sentinel_quant.data.live import Candle
from sentinel_quant.data.store import DatasetStore


def load_candles(store: DatasetStore, dataset_id: str) -> tuple[str, list[Candle]]:
    """Return (symbol, bars) for a dataset that passed verification and quality checks."""
    frame = store.load(dataset_id)
    manifest = store.manifest(dataset_id)
    stamps = frame["timestamp"].dt.epoch("ms").to_list()
    columns = (frame[name].to_list() for name in ("open", "high", "low", "close", "volume"))
    bars = [
        Candle(manifest.symbol, manifest.timeframe, stamp, *values)
        for stamp, *values in zip(stamps, *columns, strict=True)
    ]
    return manifest.symbol, bars
