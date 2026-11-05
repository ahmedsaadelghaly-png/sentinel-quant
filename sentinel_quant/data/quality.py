"""Data quality checks for an OHLCV frame.

Checks never repair data. They report, and the store refuses to hand a failed
dataset to research code unless the caller explicitly asks for it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

import polars as pl
from pydantic import BaseModel, ConfigDict

from sentinel_quant.data.timeframes import timeframe_ms

MAX_SAMPLES = 20
PRICE_COLUMNS = ("open", "high", "low", "close")

# Any non-zero count fails the dataset.
ERROR_CHECKS = (
    "timezone_not_utc",
    "duplicate_bars",
    "out_of_order_bars",
    "misaligned_bars",
    "unclosed_bars",
    "null_prices",
    "nonpositive_prices",
    "inconsistent_ohlc",
    "negative_volume",
)
# Real markets produce these (exchange outages, quiet periods): reported, not fatal.
WARNING_CHECKS = ("gaps", "zero_volume_bars")


class Gap(BaseModel):
    model_config = ConfigDict(frozen=True)

    after: datetime  # last bar before the gap
    before: datetime  # first bar after the gap
    missing_bars: int


class QualityReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    timeframe: str
    rows: int
    first_bar: datetime | None
    last_bar: datetime | None
    as_of: datetime
    expected_bars: int
    missing_bars: int
    coverage_pct: float
    status: Literal["pass", "warn", "fail"]
    checks: dict[str, int]
    gaps: list[Gap]  # first MAX_SAMPLES; the full count is checks["gaps"]
    samples: dict[str, list[datetime]]  # first MAX_SAMPLES offending bars per check


def _utc(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def _is_utc(dtype: pl.DataType) -> bool:
    return isinstance(dtype, pl.Datetime) and dtype.time_zone == "UTC"


def _bad_rows(df: pl.DataFrame, as_of_ms: int, tf_ms: int) -> dict[str, pl.Expr]:
    prices = [pl.col(c) for c in PRICE_COLUMNS]
    ms = pl.col("_ms")
    return {
        "misaligned_bars": ms % tf_ms != 0,
        "unclosed_bars": ms + tf_ms > as_of_ms,
        "null_prices": pl.any_horizontal([p.is_null() | p.is_nan() for p in prices]),
        "nonpositive_prices": pl.any_horizontal([p <= 0 for p in prices]),
        "inconsistent_ohlc": (pl.col("high") < pl.max_horizontal(prices))
        | (pl.col("low") > pl.min_horizontal(prices)),
        "negative_volume": pl.col("volume") < 0,
        "zero_volume_bars": pl.col("volume") == 0,
    }


def check_ohlcv(df: pl.DataFrame, timeframe: str, as_of_ms: int) -> QualityReport:
    """Run every check. ``as_of_ms`` is the exchange time when the data was fetched."""
    tf_ms = timeframe_ms(timeframe)
    ms_frame = df.with_columns(pl.col("timestamp").dt.epoch("ms").alias("_ms"))
    checks = dict.fromkeys((*ERROR_CHECKS, *WARNING_CHECKS), 0)
    samples: dict[str, list[datetime]] = {}

    checks["timezone_not_utc"] = 0 if _is_utc(df.schema["timestamp"]) else 1

    for name, expr in _bad_rows(df, as_of_ms, tf_ms).items():
        bad = ms_frame.filter(expr.fill_null(False))["_ms"]
        checks[name] = bad.len()
        if bad.len():
            samples[name] = [_utc(v) for v in bad.head(MAX_SAMPLES).to_list()]

    received = ms_frame["_ms"]
    repeated = received.filter(received.is_duplicated()).unique(maintain_order=True)
    checks["duplicate_bars"] = received.len() - received.n_unique()
    if repeated.len():
        samples["duplicate_bars"] = [_utc(v) for v in repeated.head(MAX_SAMPLES).to_list()]

    backwards = received.filter(received.diff().fill_null(0) < 0)
    checks["out_of_order_bars"] = backwards.len()
    if backwards.len():
        samples["out_of_order_bars"] = [_utc(v) for v in backwards.head(MAX_SAMPLES).to_list()]

    # Gaps are measured on the distinct sorted bars, so disorder is not double counted.
    ordered = received.unique().sort()
    steps = pl.DataFrame({"before": ordered, "step": ordered.diff()}).filter(pl.col("step") > tf_ms)
    gaps = [
        Gap(after=_utc(before - step), before=_utc(before), missing_bars=(step - 1) // tf_ms)
        for before, step in steps.select("before", "step").iter_rows()
    ]
    checks["gaps"] = len(gaps)
    missing = sum(g.missing_bars for g in gaps)

    first = int(ordered[0]) if ordered.len() else None
    last = int(ordered[-1]) if ordered.len() else None
    expected = (last - first) // tf_ms + 1 if first is not None and last is not None else 0
    present = expected - missing

    failed = any(checks[name] for name in ERROR_CHECKS)
    warned = any(checks[name] for name in WARNING_CHECKS)
    return QualityReport(
        timeframe=timeframe,
        rows=df.height,
        first_bar=_utc(first) if first is not None else None,
        last_bar=_utc(last) if last is not None else None,
        as_of=_utc(as_of_ms),
        expected_bars=expected,
        missing_bars=missing,
        coverage_pct=round(100 * present / expected, 4) if expected else 0.0,
        status="fail" if failed or df.is_empty() else "warn" if warned else "pass",
        checks=checks,
        gaps=gaps[:MAX_SAMPLES],
        samples=samples,
    )


def render_text(report: QualityReport, title: str) -> str:
    lines = [
        title,
        f"  status:   {report.status.upper()}",
        f"  range:    {report.first_bar} -> {report.last_bar} ({report.timeframe}, UTC)",
        f"  rows:     {report.rows} of {report.expected_bars} expected "
        f"({report.coverage_pct}% coverage, {report.missing_bars} missing)",
        "  checks:",
    ]
    for name in (*ERROR_CHECKS, *WARNING_CHECKS):
        level = "error" if name in ERROR_CHECKS else "warn"
        count = report.checks[name]
        lines.append(f"    {name:<20} {count:>8}  {level if count else 'ok'}")
    for gap in report.gaps:
        lines.append(f"  gap: {gap.after} -> {gap.before} ({gap.missing_bars} bars missing)")
    if report.checks["gaps"] > len(report.gaps):
        lines.append(f"  ... {report.checks['gaps'] - len(report.gaps)} more gaps")
    for name, values in report.samples.items():
        shown = ", ".join(str(v) for v in values[:3])
        lines.append(f"  {name}: {shown}")
    return "\n".join(lines)
