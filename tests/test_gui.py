from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from sentinel_quant.config import AppConfig, DailyControls, ExchangeConfig
from sentinel_quant.config.schema import TradingMode
from sentinel_quant.execution.adapter import FillReport
from sentinel_quant.execution.orders import OrderRequest, Side
from sentinel_quant.execution.service import ledger_path, pid_path, stop_path
from sentinel_quant.gui import app as gui
from sentinel_quant.gui.app import create_app
from sentinel_quant.ledger.store import Ledger
from sentinel_quant.ops.pidfile import acquire_pid, release_pid, running_pid
from sentinel_quant.risk.engine import RiskEngine
from sentinel_quant.risk.kill_switch import KillSwitch

BTC = "BTC/USDT"
CONTROL = {"X-Sentinel-Control": "1"}
T = 1_700_000_000_000


@pytest.fixture
def cfg(tmp_path: Path) -> AppConfig:
    return AppConfig(
        runs_dir=str(tmp_path / "runs"),
        kill_switch_path=str(tmp_path / "KILL"),
        exchange=ExchangeConfig(symbols=(BTC,)),
    )


@pytest.fixture
def client(cfg: AppConfig) -> TestClient:
    return TestClient(create_app(cfg, "c.yaml"), base_url="http://127.0.0.1:8765")


def seed(cfg: AppConfig) -> None:
    ledger = Ledger(ledger_path(cfg), 10_000.0)
    ledger.record_intent("a", OrderRequest(BTC, Side.BUY, 2.0, stop_price=90.0), T)
    ledger.apply_fill(FillReport("1", "a", BTC, Side.BUY, 2.0, 100.0, 1.0, T, "market"))
    risk = RiskEngine(DailyControls(), KillSwitch(cfg.kill_switch_path))
    risk.state.day_start_equity = 10_000.0
    risk.state.entries_today = 1
    ledger.record_equity(T, 10_000.0)
    ledger.record_equity(T + 1, 10_019.0)
    ledger.decide(T, BTC, "rejected", "buy refused: <b>max_daily_trades</b>")
    ledger.set_state({"risk": risk.state.model_dump(mode="json"), "marks": {BTC: 110.0}})
    ledger.close()


def test_page_is_served_and_has_no_sample_numbers(client: TestClient) -> None:
    page = client.get("/")
    assert page.status_code == 200
    assert "Sentinel Quant" in page.text
    assert "innerHTML" not in page.text


def test_empty_state_is_honest_and_creates_nothing(client: TestClient, cfg: AppConfig) -> None:
    status = client.get("/api/status").json()
    assert status["has_ledger"] is False
    assert status["running"] is False
    assert status["positions"] == []
    assert "equity" not in status
    assert client.get("/api/decisions").json() == []
    assert client.get("/api/equity").json() == []
    assert not ledger_path(cfg).exists()


def test_status_reports_the_ledger_exactly(client: TestClient, cfg: AppConfig) -> None:
    seed(cfg)
    status = client.get("/api/status").json()
    assert status["cash"] == pytest.approx(9_799.0)
    assert status["equity"] == pytest.approx(10_019.0)
    assert status["day_pnl"] == pytest.approx(19.0)
    (position,) = status["positions"]
    assert position["stop"] == 90.0
    assert position["unrealised"] == pytest.approx(19.0)
    assert status["risk"]["entries_today"] == 1
    assert len(client.get("/api/equity").json()) == 2


def test_position_without_a_price_gives_no_equity_rather_than_a_wrong_one(
    client: TestClient, cfg: AppConfig
) -> None:
    seed(cfg)
    ledger = Ledger(ledger_path(cfg), 10_000.0)
    ledger.set_state({"marks": {}})
    ledger.close()
    status = client.get("/api/status").json()
    assert status["equity"] is None
    assert status["day_pnl"] is None


def test_log_text_reaches_the_page_as_data(client: TestClient, cfg: AppConfig) -> None:
    seed(cfg)
    assert "<b>" in client.get("/api/decisions").json()[0]["detail"]


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/kill-switch", {"action": "engage"}),
        ("/api/service/start", {}),
        ("/api/service/stop", {}),
        ("/api/limits", {}),
    ],
)
def test_actions_need_the_control_header(client: TestClient, path: str, body: Any) -> None:
    assert client.post(path, json=body).status_code == 403


def test_foreign_origin_is_refused(client: TestClient, cfg: AppConfig) -> None:
    headers = {**CONTROL, "Origin": "https://evil.example"}
    response = client.post("/api/kill-switch", json={"action": "engage"}, headers=headers)
    assert response.status_code == 403
    assert not KillSwitch(cfg.kill_switch_path).engaged()


def test_foreign_host_is_refused_even_for_reads(client: TestClient) -> None:
    assert client.get("/api/status", headers={"Host": "evil.example"}).status_code == 403


def test_kill_switch_engage_and_guarded_release(client: TestClient, cfg: AppConfig) -> None:
    switch = KillSwitch(cfg.kill_switch_path)
    assert client.post("/api/kill-switch", json={"action": "engage"}, headers=CONTROL).json() == {
        "engaged": True
    }
    assert switch.engaged()
    assert client.get("/api/status").json()["kill_switch"]["engaged"] is True
    refused = client.post(
        "/api/kill-switch", json={"action": "release", "confirm": "yes"}, headers=CONTROL
    )
    assert refused.status_code == 400
    assert switch.engaged()
    client.post(
        "/api/kill-switch", json={"action": "release", "confirm": "RELEASE"}, headers=CONTROL
    )
    assert not switch.engaged()


def test_limits_are_validated_and_only_requested(client: TestClient, cfg: AppConfig) -> None:
    good = DailyControls(max_daily_trades=2).model_dump(mode="json")
    assert client.post("/api/limits", json=good, headers=CONTROL).status_code == 200
    ledger = Ledger(ledger_path(cfg), 10_000.0)
    assert ledger.get_state("requested_limits")["max_daily_trades"] == 2
    assert ledger.get_state("desired_limits")["max_daily_trades"] == 2
    ledger.close()


@pytest.mark.parametrize(
    "change",
    [
        {"risk_per_trade_pct": 50},  # above the hard cap
        {"risk_per_trade_pct": 1.9, "max_daily_loss_pct": 1.0},  # per-trade above daily
        {"max_daily_trades": 0},
        {"mode": "live"},  # no such limit, and no way to reach the mode from here
        {"live_trading_approved": True},
    ],
)
def test_unsafe_limits_are_refused(client: TestClient, cfg: AppConfig, change: Any) -> None:
    body = {**DailyControls().model_dump(mode="json"), **change}
    assert client.post("/api/limits", json=body, headers=CONTROL).status_code == 400
    assert not ledger_path(cfg).exists()


def test_panel_cannot_run_in_live_mode(tmp_path: Path) -> None:
    cfg = AppConfig(
        mode=TradingMode.LIVE,
        live_trading_approved=True,
        exchange=ExchangeConfig(testnet=False),
        runs_dir=str(tmp_path),
    )
    with pytest.raises(ValueError, match="live"):
        create_app(cfg, "c.yaml")


def test_start_spawns_once(
    client: TestClient, cfg: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Any] = []
    monkeypatch.setattr(gui.subprocess, "Popen", lambda *a, **k: calls.append(a[0]))
    assert client.post("/api/service/start", json={}, headers=CONTROL).status_code == 200
    assert calls[0][1:] == ["-m", "sentinel_quant.cli", "run", "--config", "c.yaml"]
    acquire_pid(pid_path(cfg))
    assert client.post("/api/service/start", json={}, headers=CONTROL).status_code == 409
    assert len(calls) == 1


def test_stop_uses_the_stop_file(client: TestClient, cfg: AppConfig) -> None:
    assert client.post("/api/service/stop", json={}, headers=CONTROL).status_code == 409
    acquire_pid(pid_path(cfg))
    assert client.post("/api/service/stop", json={}, headers=CONTROL).status_code == 200
    assert stop_path(cfg).exists()


def test_pid_lock(tmp_path: Path) -> None:
    path = tmp_path / "p/s.pid"
    assert running_pid(path) is None
    assert acquire_pid(path)
    assert running_pid(path) is not None
    assert not acquire_pid(path)
    release_pid(path)
    assert running_pid(path) is None


def test_stale_pid_does_not_block_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "s.pid"
    path.write_text("999999999", encoding="utf-8")
    assert acquire_pid(path)


def test_garbage_pid_file_counts_as_not_running(tmp_path: Path) -> None:
    path = tmp_path / "s.pid"
    path.write_text("nope", encoding="utf-8")
    assert running_pid(path) is None
