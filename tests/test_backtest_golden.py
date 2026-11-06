"""Golden tests: results that are known independently of the engine."""

import math
import random
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean, stdev
from typing import Any

import pytest
from conftest import HOUR_MS, T0, make_client, replay_exchange
from test_backtest_engine import COSTS, FREE, SYMBOL, ApproveAll, Scripted, buy, candle, run, sell

from sentinel_quant.backtest.engine import run_backtest
from sentinel_quant.backtest.feed import load_candles
from sentinel_quant.backtest.models import BacktestResult, CostModel
from sentinel_quant.data.download import download_symbol
from sentinel_quant.data.live import Candle
from sentinel_quant.data.quality import check_ohlcv
from sentinel_quant.data.store import DatasetError, DatasetKey, DatasetStore, frame_from_rows
from sentinel_quant.evaluation.metrics import summarize
from sentinel_quant.execution.orders import OrderRequest, PortfolioSnapshot, Side


def test_hand_computed_round_trip() -> None:
    """Worked by hand at 10 bps fee and 5 bps slippage, buying 10 at 100, selling at 130.

    Buy:  price 100.05, notional 1000.50, fee 1.0005, cash 10000 - 1001.5005 = 8998.4995
    Sell: price 129.935, notional 1299.35, fee 1.29935, proceeds 1298.05065
    End:  cash 10296.55015, net P&L 296.55015
    Paid: fees 1.0005 + 1.29935 = 2.29985, slippage 10 x 0.05 + 10 x 0.065 = 1.15, gross P&L 300.00
    """
    bars = [candle(0), candle(1, 100), candle(2, 130), candle(3, 130)]
    result = run(bars, {0: [buy(10.0)], 1: [sell(10.0)]}, COSTS)
    summary = summarize(result)
    assert result.final_equity == pytest.approx(10_296.55015)
    assert summary.net_pnl == pytest.approx(296.55015)
    assert summary.fees_paid == pytest.approx(2.29985)
    assert summary.slippage_paid == pytest.approx(1.15)
    assert summary.gross_pnl == pytest.approx(300.0)
    (trade,) = result.trades
    assert trade.cost == pytest.approx(1001.5005)
    assert trade.proceeds == pytest.approx(1298.05065)
    assert trade.net_pnl == pytest.approx(296.55015)


def test_buy_and_hold_tracks_the_price_exactly_without_costs() -> None:
    prices = [100.0, 110.0, 90.0, 120.0, 150.0]
    bars = [candle(i, p) for i, p in enumerate(prices)]
    result = run(bars, {0: [buy(10.0)]}, cash=1000.0)
    # All cash goes in at 110, the second bar's open, so 10 units cost 1100: refused.
    assert result.rejections[0].reason == "insufficient_cash"
    result = run(bars, {0: [buy(9.0)]}, cash=1000.0)
    assert result.final_equity == pytest.approx(1000 - 9 * 110 + 9 * 150)
    assert [round(p.equity, 6) for p in result.equity_curve] == [1000, 1000, 820, 1090, 1360]


def test_buy_and_hold_pays_the_entry_cost_once() -> None:
    bars = [candle(0), candle(1, 100), candle(2, 100)]
    summary = summarize(run(bars, {0: [buy(10.0)]}, COSTS))
    assert summary.net_pnl == pytest.approx(-(10 * 0.05 + 1.0005))


def test_doing_nothing_changes_nothing() -> None:
    result = run([candle(i, 100 + i) for i in range(50)], {}, COSTS)
    summary = summarize(result)
    assert summary.net_pnl == 0
    assert summary.max_drawdown_pct == 0
    assert summary.sharpe is None
    assert summary.trades == 0


def test_flat_market_loses_exactly_the_round_trip_cost() -> None:
    bars = [candle(i) for i in range(4)]
    summary = summarize(run(bars, {0: [buy(10.0)], 1: [sell(10.0)]}, COSTS))
    assert summary.gross_pnl == pytest.approx(0.0, abs=1e-9)
    # Round trip costs about 2 x (10 + 5) = 30 bps of the 1000 traded.
    assert summary.net_pnl == pytest.approx(-3.0, rel=1e-3)


class RandomEntry:
    """Enters at random and exits after a fixed hold. Has no information by design."""

    def __init__(self, seed: int, quantity: float, hold: int) -> None:
        self.rng = random.Random(seed)  # noqa: S311
        self.quantity = quantity
        self.hold = hold
        self.bars_held: int | None = None

    def on_bar(self, bar: Candle, portfolio: PortfolioSnapshot) -> Sequence[OrderRequest]:
        if self.bars_held is None:
            if self.rng.random() < 0.1:
                self.bars_held = 0
                return [OrderRequest(bar.symbol, Side.BUY, self.quantity)]
            return []
        self.bars_held += 1
        if self.bars_held >= self.hold:
            self.bars_held = None
            return [OrderRequest(bar.symbol, Side.SELL, self.quantity)]
        return []


def random_walk(seed: int, count: int) -> list[Candle]:
    """Driftless in price, not log price, so a fair bet has zero expected P&L."""
    rng = random.Random(seed)  # noqa: S311
    bars = []
    price = 1000.0
    for index in range(count):
        step = rng.gauss(0.0, 2.0)
        close = max(price + step, 500.0)
        bars.append(candle(index, price, close=close))
        price = close
    return bars


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_random_entry_has_no_edge_and_loses_its_costs(seed: int) -> None:
    bars = random_walk(seed, 20_000)
    strategy = RandomEntry(seed + 100, quantity=1.0, hold=5)
    result = run_backtest({SYMBOL: bars}, strategy, ApproveAll(), COSTS, 1_000_000.0)
    summary = summarize(result)
    trades = result.trades
    assert len(trades) > 1000

    per_trade_gross = [
        t.net_pnl + 2 * t.cost * (COSTS.fee_bps + COSTS.slippage_bps) / 10_000 for t in trades
    ]
    standard_error = stdev(per_trade_gross) / math.sqrt(len(trades))
    assert abs(fmean(per_trade_gross)) < 3.5 * standard_error, "random entries showed an edge"

    # Costs are the whole story: about 30 bps of notional per round trip.
    expected_cost = sum(2 * t.cost * 15 / 10_000 for t in trades)
    assert summary.fees_paid + summary.slippage_paid == pytest.approx(expected_cost, rel=0.01)
    assert summary.net_pnl < 0


def test_doubling_costs_doubles_the_drag() -> None:
    bars = random_walk(7, 5_000)
    results = [
        run_backtest({SYMBOL: bars}, RandomEntry(7, 1.0, 5), ApproveAll(), costs, 1_000_000.0)
        for costs in (COSTS, COSTS.stressed(2.0))
    ]
    base, stressed = (r.fees_paid + r.slippage_paid for r in results)
    assert stressed == pytest.approx(2 * base, rel=0.01)
    assert results[1].final_equity < results[0].final_equity


def test_accounting_identities_hold_on_a_long_random_run() -> None:
    bars = random_walk(11, 5_000)
    result = run_backtest({SYMBOL: bars}, RandomEntry(11, 1.0, 5), ApproveAll(), COSTS, 1e6)
    last = bars[-1].close
    held = result.open_positions.get(SYMBOL, 0.0)
    assert result.final_equity == pytest.approx(result.equity_curve[-1].cash + held * last)

    cash = 1e6
    for fill in result.fills:
        notional = fill.quantity * fill.price
        cash += -notional - fill.fee if fill.side is Side.BUY else notional - fill.fee
    assert cash == pytest.approx(result.equity_curve[-1].cash)


def test_same_inputs_give_identical_results() -> None:
    bars = random_walk(13, 2_000)

    def once() -> BacktestResult:
        return run_backtest({SYMBOL: bars}, RandomEntry(13, 1.0, 5), ApproveAll(), COSTS, 1e6)

    assert once() == once()


class Momentum:
    """Uses only what it has been shown, like any honest strategy."""

    def __init__(self) -> None:
        self.closes: list[float] = []
        self.long = False

    def on_bar(self, bar: Candle, portfolio: PortfolioSnapshot) -> Sequence[OrderRequest]:
        self.closes.append(bar.close)
        if len(self.closes) < 10:
            return []
        rising = self.closes[-1] > self.closes[-10]
        if rising and not self.long:
            self.long = True
            return [OrderRequest(bar.symbol, Side.BUY, 1.0)]
        if not rising and self.long:
            self.long = False
            return [OrderRequest(bar.symbol, Side.SELL, 1.0)]
        return []


@pytest.mark.parametrize("cut", [50, 500, 1500])
def test_truncation_future_bars_cannot_change_the_past(cut: int) -> None:
    bars = random_walk(17, 2_000)
    full = run_backtest({SYMBOL: bars}, Momentum(), ApproveAll(), COSTS, 1e6)
    part = run_backtest({SYMBOL: bars[:cut]}, Momentum(), ApproveAll(), COSTS, 1e6)
    assert full.equity_curve[:cut] == part.equity_curve
    assert full.fills[: len(part.fills)] == part.fills


def test_rewriting_the_future_cannot_change_the_past() -> None:
    bars = random_walk(19, 1_000)
    altered = [*bars[:600], *(candle(i, 5000.0) for i in range(600, 1000))]
    a = run_backtest({SYMBOL: bars}, Momentum(), ApproveAll(), COSTS, 1e6)
    b = run_backtest({SYMBOL: altered}, Momentum(), ApproveAll(), COSTS, 1e6)
    assert a.equity_curve[:600] == b.equity_curve[:600]


def test_every_fill_happens_strictly_after_its_signal() -> None:
    result = run_backtest(
        {SYMBOL: random_walk(23, 3_000)}, RandomEntry(23, 1.0, 5), ApproveAll(), COSTS, 1e6
    )
    assert result.fills
    assert all(f.time_ms > f.submitted_ms for f in result.fills)


def _download_outage(store: DatasetStore, recorded: dict[str, Any]) -> str:
    history = recorded["history"]
    result = download_symbol(
        make_client(replay_exchange(recorded)),
        store,
        DatasetKey("binance", SYMBOL, "1h"),
        start_ms=history["start_ms"],
        end_ms=history["end_ms"],
        page_limit=history["page_limit"],
        grace_ms=2000,
    )
    assert result.manifest is not None
    return result.manifest.dataset_id


def test_real_outage_defers_the_fill_past_zero_volume_and_gap(
    tmp_path: Path, recorded: dict[str, Any]
) -> None:
    """2023-03-24: the 12:00 bar has no volume and the 13:00 bar does not exist."""
    store = DatasetStore(tmp_path)
    dataset_id = _download_outage(store, recorded)
    symbol, bars = load_candles(store, dataset_id)
    assert symbol == SYMBOL
    signal = next(i for i, b in enumerate(bars) if b.volume == 0) - 1  # the 11:00 bar

    result = run_backtest(
        {symbol: bars},
        Scripted({signal: [buy(0.01)]}),
        ApproveAll(),
        CostModel(0.0, 0.0),
        1000.0,
        dataset_ids=[dataset_id],
    )
    (fill,) = result.fills
    assert fill.submitted_ms == int(datetime(2023, 3, 24, 11, tzinfo=UTC).timestamp() * 1000)
    assert fill.time_ms == int(datetime(2023, 3, 24, 14, tzinfo=UTC).timestamp() * 1000)
    after_outage = next(b for b in bars if b.open_time_ms == fill.time_ms)
    assert fill.price == after_outage.open
    assert result.dataset_ids == (dataset_id,)


def test_failed_dataset_cannot_enter_a_backtest(tmp_path: Path) -> None:
    store = DatasetStore(tmp_path)
    frame = frame_from_rows([[T0, -1.0, 1.0, -2.0, 0.5, 1.0]])
    manifest, _ = store.save(
        DatasetKey("binance", SYMBOL, "1h"),
        frame,
        check_ohlcv(frame, "1h", T0 + 10 * HOUR_MS),
        source="test",
        library_version="test",
        parent_dataset_id=None,
        fetched_at=datetime.fromtimestamp((T0 + 10 * HOUR_MS) / 1000, tz=UTC),
    )
    with pytest.raises(DatasetError, match="failed quality"):
        load_candles(store, manifest.dataset_id)


def test_free_and_costed_runs_differ_only_by_costs() -> None:
    bars = [candle(0), candle(1, 100), candle(2, 110), candle(3, 110)]
    script = {0: [buy(1.0)], 1: [sell(1.0)]}
    free = summarize(run(bars, script, FREE))
    costed = summarize(run(bars, script, COSTS))
    assert free.gross_pnl == pytest.approx(costed.gross_pnl)
