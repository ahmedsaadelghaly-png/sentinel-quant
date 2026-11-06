import urllib.error
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from sentinel_quant.cli import main
from sentinel_quant.config import DailyControls
from sentinel_quant.config.secrets import Secrets
from sentinel_quant.execution.adapter import FillReport
from sentinel_quant.execution.orders import OrderRequest, Side
from sentinel_quant.ledger.store import Ledger
from sentinel_quant.ops import alerts
from sentinel_quant.ops.alerts import LogNotifier, TelegramNotifier, build_notifier
from sentinel_quant.ops.report import build_daily_report, day_to_report, write_report

DAY = date(2024, 3, 5)
START = int(datetime(2024, 3, 5, tzinfo=UTC).timestamp() * 1000)
H = 3_600_000
BTC = "BTC/USDT"


def fill(fill_id: str, client: str, side: Side, price: float, time_ms: int) -> FillReport:
    return FillReport(fill_id, client, BTC, side, 1.0, price, 0.5, time_ms, "market")


@pytest.fixture
def ledger(tmp_path: Path) -> Ledger:
    book = Ledger(tmp_path / "l.sqlite", 1000.0)
    book.record_equity(START, 1000.0)
    book.record_intent("a", OrderRequest(BTC, Side.BUY, 1.0, stop_price=90.0), START)
    book.apply_fill(fill("1", "a", Side.BUY, 100.0, START + H))
    book.apply_fill(fill("2", "b", Side.SELL, 110.0, START + 2 * H))
    book.record_equity(START + 3 * H, 1009.0)
    book.decide(START + H, BTC, "signal", "enter: close 100 above 55-bar high 99")
    book.decide(START + 2 * H, BTC, "rejected", "buy refused: max_daily_trades")
    book.decide(START + 2 * H, "*", "limit_hit", "daily_profit_lock")
    return book


def test_ledger_books_cash_positions_and_pnl_once(ledger: Ledger) -> None:
    assert ledger.cash == pytest.approx(1009.0)
    assert ledger.positions() == {}
    assert ledger.fills()[1]["net_pnl"] == pytest.approx(9.0)
    assert ledger.apply_fill(fill("2", "b", Side.SELL, 110.0, START + 2 * H)) is False
    assert ledger.cash == pytest.approx(1009.0)


def test_ledger_rebuilds_the_same_book_from_disk(tmp_path: Path) -> None:
    path = tmp_path / "x.sqlite"
    first = Ledger(path, 1000.0)
    first.record_intent("a", OrderRequest(BTC, Side.BUY, 1.0, stop_price=90.0), START)
    first.apply_fill(fill("1", "a", Side.BUY, 100.0, START))
    first.close()
    second = Ledger(path, 1000.0)
    assert second.cash == pytest.approx(899.5)
    assert second.positions() == {BTC: 1.0}
    assert second.stops()[0].stop_price == 90.0


def test_intent_is_visible_as_pending_until_filled(tmp_path: Path) -> None:
    book = Ledger(tmp_path / "x.sqlite", 1000.0)
    book.record_intent("a", OrderRequest(BTC, Side.BUY, 1.0, stop_price=90.0), START)
    assert len(book.pending()) == 1
    book.apply_fill(fill("1", "a", Side.BUY, 100.0, START))
    assert book.pending() == ()


def test_daily_report_explains_the_day(ledger: Ledger) -> None:
    report = build_daily_report(ledger, DAY, DailyControls())
    assert report.start_equity == 1000.0
    assert report.end_equity == 1009.0
    assert report.trades == 1
    assert report.realised_pnl == pytest.approx(9.0)
    assert report.rejected == {"max_daily_trades": 1}
    assert report.limits_hit == ("daily_profit_lock",)
    assert "above 55-bar high" in report.text
    assert "buy refused: max_daily_trades" in report.text
    assert "+0.90%" in report.text


def test_report_excludes_other_days(ledger: Ledger) -> None:
    report = build_daily_report(ledger, date(2024, 3, 6), DailyControls())
    assert report.trades == 0
    assert report.decisions == ()
    assert "quiet day is a normal day" in report.text


def test_day_with_no_data_says_so(tmp_path: Path) -> None:
    report = build_daily_report(Ledger(tmp_path / "e.sqlite", 1.0), DAY, DailyControls())
    assert "No equity recorded" in report.text


def test_report_is_written_by_date(ledger: Ledger, tmp_path: Path) -> None:
    path = write_report(build_daily_report(ledger, DAY, DailyControls()), tmp_path)
    assert path.name == "2024-03-05.md"


def test_report_due_only_after_its_time() -> None:
    five_past = 5 * 60_000
    assert day_to_report(START + 60_000, five_past) is None
    assert day_to_report(START + five_past, five_past) == date(2024, 3, 4)


def test_telegram_posts_to_the_official_api(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Any] = []

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: Any) -> None:
            pass

    def fake_open(request: Any, timeout: float) -> Response:
        calls.append(request)
        return Response()

    monkeypatch.setattr(alerts.urllib.request, "urlopen", fake_open)
    TelegramNotifier("TOKEN123", "42").send("warning", "hello")
    assert calls[0].full_url == "https://api.telegram.org/botTOKEN123/sendMessage"
    assert b'"chat_id": "42"' in calls[0].data
    assert b"[WARNING] hello" in calls[0].data


def test_alert_failure_never_raises_or_leaks_the_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from sentinel_quant.ops.logging import configure_logging

    configure_logging()

    def down(*_args: Any, **_kwargs: Any) -> None:
        raise urllib.error.URLError("failed https://api.telegram.org/botTOKEN123/sendMessage")

    monkeypatch.setattr(alerts.urllib.request, "urlopen", down)
    TelegramNotifier("TOKEN123", "42").send("error", "hello")
    assert "TOKEN123" not in capsys.readouterr().out


def test_long_messages_are_cut_to_telegrams_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    sizes: list[int] = []

    def fake_open(request: Any, timeout: float) -> Any:
        sizes.append(len(request.data))
        raise TimeoutError

    monkeypatch.setattr(alerts.urllib.request, "urlopen", fake_open)
    TelegramNotifier("T", "1").send("info", "x" * 9000)
    assert sizes[0] < 4100


def test_notifier_selection() -> None:
    empty = Secrets(_env_file=None)
    assert isinstance(build_notifier(False, empty), LogNotifier)
    with pytest.raises(ValueError, match="SQ_TELEGRAM_BOT_TOKEN"):
        build_notifier(True, empty)
    ready = Secrets(telegram_bot_token=SecretStr("t"), telegram_chat_id=SecretStr("1"))
    assert isinstance(build_notifier(True, ready), TelegramNotifier)


def write_config(tmp_path: Path, **extra: Any) -> str:
    path = tmp_path / "c.yaml"
    lines = [f"runs_dir: {tmp_path / 'runs'}", f"kill_switch_path: {tmp_path / 'KILL'}"]
    lines += [f"{k}: {v}" for k, v in extra.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def test_cli_kill_switch_round_trip(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = write_config(tmp_path)
    assert main(["kill-switch", "on", "--config", config, "--reason", "test"]) == 0
    assert "ENGAGED" in capsys.readouterr().out
    assert (tmp_path / "KILL").exists()
    assert main(["kill-switch", "status", "--config", config]) == 0
    assert "ENGAGED" in capsys.readouterr().out
    assert main(["kill-switch", "off", "--config", config]) == 0
    assert "released" in capsys.readouterr().out


def test_cli_report_needs_a_ledger(tmp_path: Path) -> None:
    assert main(["report", "2024-03-05", "--config", write_config(tmp_path)]) == 1


def test_cli_run_refuses_paper_without_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from conftest import FakeExchange

    import sentinel_quant.cli as cli
    import sentinel_quant.data.client as client_module

    monkeypatch.setattr(client_module, "build_public_exchange", lambda _n: FakeExchange(0, []))
    monkeypatch.setattr(cli, "Secrets", lambda: Secrets(_env_file=None))
    assert main(["run", "--config", write_config(tmp_path, mode="paper")]) == 1
