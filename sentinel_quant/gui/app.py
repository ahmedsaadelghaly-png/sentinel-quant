"""Local control panel. Serves real ledger state only; it holds no trading logic.

Every action reaches the bot through a path that has its own safeguards: the kill switch
file, the stop file, and a limit request the risk engine applies by its own rules. Nothing
here can place an order or enable live trading.

The server binds to 127.0.0.1. Browsers will still send requests there on behalf of any
website, so the Host and Origin checks and the required header below are what stop a
malicious page from pressing these buttons.
"""

from __future__ import annotations

import subprocess
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError

from sentinel_quant.config.schema import AppConfig, DailyControls, TradingMode
from sentinel_quant.execution.service import ledger_path, pid_path, stop_path
from sentinel_quant.ledger.store import Ledger
from sentinel_quant.ops.pidfile import running_pid
from sentinel_quant.risk.kill_switch import KillSwitch

_LOCAL_HOSTS = {"127.0.0.1", "localhost"}
_CONTROL_HEADER = "x-sentinel-control"
_PAGE = Path(__file__).parent / "static" / "index.html"
_MAX_CURVE_POINTS = 2000


class KillSwitchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["engage", "release"]
    confirm: str = ""


def _hostname(value: str) -> str | None:
    return urlsplit(f"//{value}").hostname


def _require_control(request: Request) -> None:
    if request.headers.get(_CONTROL_HEADER) != "1":
        raise HTTPException(403, "missing control header")
    origin = request.headers.get("origin")
    if origin is not None and urlsplit(origin).hostname not in _LOCAL_HOSTS:
        raise HTTPException(403, "foreign origin")


def _read_kill_reason(switch: KillSwitch) -> str:
    try:
        return switch.path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _status(cfg: AppConfig) -> dict[str, Any]:
    switch = KillSwitch(cfg.kill_switch_path)
    engaged = switch.engaged()
    pid = running_pid(pid_path(cfg))
    status: dict[str, Any] = {
        "mode": cfg.mode.value,
        "exchange": cfg.exchange.name,
        "symbols": list(cfg.exchange.symbols),
        "timeframe": cfg.exchange.timeframe,
        "strategy": cfg.strategy.name,
        "running": pid is not None,
        "kill_switch": {
            "engaged": engaged,
            "reason": _read_kill_reason(switch) if engaged else "",
        },
        "limits": cfg.daily_controls.model_dump(mode="json"),
        "has_ledger": ledger_path(cfg).is_file(),
        "positions": [],
        "risk": None,
    }
    if not status["has_ledger"]:
        return status

    ledger = Ledger(ledger_path(cfg), cfg.backtest.initial_cash)
    try:
        marks: dict[str, float] = ledger.get_state("marks") or {}
        risk = ledger.get_state("risk")
        heartbeat = ledger.get_state("heartbeat_ms")
        positions: list[dict[str, Any]] = []
        stops = {s.symbol: s.stop_price for s in ledger.stops()}
        for symbol, holding in ledger.holdings.items():
            mark = marks.get(symbol)
            value = holding.quantity * mark if mark is not None else None
            positions.append(
                {
                    "symbol": symbol,
                    "quantity": holding.quantity,
                    "cost": holding.cost,
                    "mark": mark,
                    "value": value,
                    "unrealised": value - holding.cost if value is not None else None,
                    "stop": stops.get(symbol),
                }
            )
        values = [p["value"] for p in positions]
        marked = None not in values
        held = sum(v for v in values if v is not None)
        equity = ledger.cash + held if marked else None
        day_start = risk["day_start_equity"] if risk else None
        status.update(
            cash=ledger.cash,
            equity=equity,
            exposure=held,
            day_start_equity=day_start,
            day_pnl=equity - day_start if equity is not None and day_start else None,
            positions=positions,
            risk=risk,
            heartbeat_age_seconds=(time.time() * 1000 - heartbeat) / 1000 if heartbeat else None,
        )
        if risk:
            status["limits"] = risk["limits"]
    finally:
        ledger.close()
    return status


def create_app(cfg: AppConfig, config_path: str) -> FastAPI:
    if cfg.mode is TradingMode.LIVE:
        raise ValueError("the control panel does not support live mode")
    app = FastAPI(title="Sentinel Quant", docs_url=None, redoc_url=None, openapi_url=None)
    switch = KillSwitch(cfg.kill_switch_path)
    control = [Depends(_require_control)]

    @app.middleware("http")
    async def local_only(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Blocks DNS rebinding: a foreign name pointed at 127.0.0.1 keeps its own Host.
        if _hostname(request.headers.get("host", "")) not in _LOCAL_HOSTS:
            return JSONResponse({"detail": "local access only"}, status_code=403)
        return await call_next(request)

    def read_ledger() -> Ledger | None:
        path = ledger_path(cfg)
        return Ledger(path, cfg.backtest.initial_cash) if path.is_file() else None

    @app.get("/")
    def page() -> FileResponse:
        return FileResponse(_PAGE, headers={"Cache-Control": "no-store"})

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        return _status(cfg)

    @app.get("/api/decisions")
    def decisions(limit: int = 200) -> list[dict[str, Any]]:
        ledger = read_ledger()
        if ledger is None:
            return []
        try:
            rows = ledger.decisions(0, min(limit, 1000))
        finally:
            ledger.close()
        return [
            {"time_ms": d.time_ms, "symbol": d.symbol, "kind": d.kind, "detail": d.detail}
            for d in rows
        ]

    @app.get("/api/equity")
    def equity() -> list[dict[str, float]]:
        ledger = read_ledger()
        if ledger is None:
            return []
        try:
            curve = ledger.equity_curve()[-_MAX_CURVE_POINTS:]
        finally:
            ledger.close()
        return [{"time_ms": t, "equity": e} for t, e in curve]

    @app.post("/api/kill-switch", dependencies=control)
    def kill_switch(body: KillSwitchRequest) -> dict[str, bool]:
        if body.action == "engage":
            switch.engage("control panel")
        else:
            if body.confirm != "RELEASE":
                raise HTTPException(400, "type RELEASE to confirm")
            switch.release()
        return {"engaged": switch.engaged()}

    @app.post("/api/service/start", dependencies=control)
    def start() -> dict[str, str]:
        if running_pid(pid_path(cfg)) is not None:
            raise HTTPException(409, "already running")
        logs = Path(cfg.runs_dir) / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        with (logs / f"service-{cfg.mode.value}.log").open("a", encoding="utf-8") as log_file:
            subprocess.Popen(  # noqa: S603
                [sys.executable, "-m", "sentinel_quant.cli", "run", "--config", config_path],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        return {"status": "starting"}

    @app.post("/api/service/stop", dependencies=control)
    def stop() -> dict[str, str]:
        if running_pid(pid_path(cfg)) is None:
            raise HTTPException(409, "not running")
        stop_path(cfg).touch()
        return {"status": "stopping"}

    @app.post("/api/limits", dependencies=control)
    def limits(body: dict[str, Any]) -> dict[str, Any]:
        try:
            requested = DailyControls.model_validate(body)
        except ValidationError as exc:
            detail = "; ".join(str(e["msg"]) for e in exc.errors())
            raise HTTPException(400, detail) from exc
        value = requested.model_dump(mode="json")
        ledger = Ledger(ledger_path(cfg), cfg.backtest.initial_cash)
        try:
            ledger.set_state({"requested_limits": value, "desired_limits": value})
        finally:
            ledger.close()
        return {"status": "requested", "rule": "stricter values now, looser at next reset"}

    return app
