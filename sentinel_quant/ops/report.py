"""Daily report: P&L, risk usage, trades, and why each trade was taken or refused."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from sentinel_quant.config.schema import DailyControls
from sentinel_quant.ledger.store import Ledger

_DAY_MS = 86_400_000
_LOG_KINDS = ("signal", "approved", "rejected", "skipped", "limit_hit", "send_failed")


@dataclass(frozen=True)
class DailyReport:
    day: date
    start_equity: float | None
    end_equity: float | None
    trades: int
    realised_pnl: float
    fees: float
    entries: int
    rejected: Counter[str]
    limits_hit: tuple[str, ...]
    decisions: tuple[str, ...]
    text: str


def _day_bounds(day: date) -> tuple[int, int]:
    start = int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp() * 1000)
    return start, start + _DAY_MS


def _time(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%H:%M")


def _usage(used: float, limit: float) -> str:
    return f"{used:.2f} of {limit:g}"


def build_daily_report(ledger: Ledger, day: date, limits: DailyControls) -> DailyReport:
    start_ms, end_ms = _day_bounds(day)
    curve = [(t, e) for t, e in ledger.equity_curve(0) if t < end_ms]
    before = [e for t, e in curve if t <= start_ms]
    during = [e for t, e in curve if t > start_ms]
    start_equity = before[-1] if before else (during[0] if during else None)
    end_equity = during[-1] if during else start_equity

    fills: list[dict[str, Any]] = [f for f in ledger.fills(start_ms) if f["time_ms"] < end_ms]
    closed = [f["net_pnl"] for f in fills if f["net_pnl"] is not None]
    decisions = [
        d
        for d in reversed(ledger.decisions(start_ms, limit=100_000))
        if d.time_ms < end_ms and d.kind in _LOG_KINDS
    ]
    entries = sum(1 for f in fills if f["side"] == "buy")
    rejected = Counter(d.detail.rsplit(": ", 1)[-1] for d in decisions if d.kind == "rejected")
    limits_hit = tuple(d.detail for d in decisions if d.kind == "limit_hit")
    fees = sum(f["fee"] for f in fills)
    log_lines = tuple(f"{_time(d.time_ms)} {d.symbol} {d.kind}: {d.detail}" for d in decisions)

    change = None
    if start_equity and end_equity is not None:
        change = 100 * (end_equity / start_equity - 1)
    lines = [f"# Sentinel Quant daily report, {day.isoformat()} (UTC)", ""]
    if change is None or start_equity is None or end_equity is None:
        lines.append("No equity recorded for this day.")
    else:
        lines.append(f"Equity: {start_equity:.2f} -> {end_equity:.2f} ({change:+.2f}%)")
    lines += [
        f"Realised P&L: {sum(closed):+.2f} from {len(closed)} closed trades, fees {fees:.2f}",
        "",
        "## Risk usage",
        f"- Daily loss: {_usage(max(-(change or 0.0), 0.0), limits.max_daily_loss_pct)}%",
        f"- Entries: {entries} of {limits.max_daily_trades}",
        f"- Limits hit: {', '.join(limits_hit) if limits_hit else 'none'}",
        f"- Refused orders: {sum(rejected.values())}"
        + (f" ({', '.join(f'{k} x{v}' for k, v in rejected.most_common())})" if rejected else ""),
        "",
        "## Decisions",
    ]
    lines += [f"- {line}" for line in log_lines] or ["- No signals. A quiet day is a normal day."]
    return DailyReport(
        day=day,
        start_equity=start_equity,
        end_equity=end_equity,
        trades=len(closed),
        realised_pnl=sum(closed),
        fees=fees,
        entries=entries,
        rejected=rejected,
        limits_hit=limits_hit,
        decisions=log_lines,
        text="\n".join(lines) + "\n",
    )


def write_report(report: DailyReport, runs_dir: str | Path) -> Path:
    path = Path(runs_dir) / "reports" / f"{report.day.isoformat()}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.text, encoding="utf-8")
    return path


def day_to_report(now_ms: int, report_time_ms_of_day: int) -> date | None:
    """The finished day whose report is due at this moment, if any."""
    now = datetime.fromtimestamp(now_ms / 1000, tz=UTC)
    if now_ms % _DAY_MS < report_time_ms_of_day:
        return None
    return (now - timedelta(days=1)).date()
