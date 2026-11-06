"""SQLite ledger: the source of truth for orders, fills, cash, positions and decisions.

Intent is written before an order is sent, so a crash leaves evidence rather than an
unknown order. Fills are keyed by ``fill_id``, so replaying a report changes nothing.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sentinel_quant.execution.adapter import FillReport
from sentinel_quant.execution.orders import OrderRequest, OrderType, Side

_DUST = 1e-12
_SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    client_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, side TEXT NOT NULL,
    order_type TEXT NOT NULL, quantity REAL NOT NULL, stop_price REAL,
    status TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '', created_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS fills (
    fill_id TEXT PRIMARY KEY, client_id TEXT NOT NULL, symbol TEXT NOT NULL,
    side TEXT NOT NULL, quantity REAL NOT NULL, price REAL NOT NULL, fee REAL NOT NULL,
    time_ms INTEGER NOT NULL, reason TEXT NOT NULL, net_pnl REAL, seq INTEGER
);
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, time_ms INTEGER NOT NULL, symbol TEXT NOT NULL,
    kind TEXT NOT NULL, detail TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS equity (
    time_ms INTEGER PRIMARY KEY, equity REAL NOT NULL, cash REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS state (name TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


@dataclass
class Holding:
    quantity: float
    cost: float
    stops: list[OrderRequest] = field(default_factory=list)


@dataclass(frozen=True)
class Decision:
    time_ms: int
    symbol: str
    kind: str
    detail: str


class Ledger:
    def __init__(self, path: str | Path, initial_cash: float) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA)
        self.cash = initial_cash
        self.holdings: dict[str, Holding] = {}
        self.fees_paid = 0.0
        for row in self._db.execute(
            "SELECT fill_id, client_id, symbol, side, quantity, price, fee, time_ms, reason"
            " FROM fills ORDER BY seq"
        ).fetchall():
            self._apply(
                FillReport(
                    fill_id=row[0],
                    client_id=row[1],
                    symbol=row[2],
                    side=Side(row[3]),
                    quantity=row[4],
                    price=row[5],
                    fee=row[6],
                    time_ms=row[7],
                    reason=row[8],
                )
            )

    def close(self) -> None:
        self._db.close()

    def has_order(self, client_id: str) -> bool:
        query = "SELECT 1 FROM orders WHERE client_id = ?"
        return self._db.execute(query, (client_id,)).fetchone() is not None

    def record_intent(self, client_id: str, order: OrderRequest, time_ms: int) -> None:
        self._db.execute(
            "INSERT OR IGNORE INTO orders (client_id, symbol, side, order_type, quantity,"
            " stop_price, status, created_ms) VALUES (?, ?, ?, ?, ?, ?, 'new', ?)",
            (
                client_id,
                order.symbol,
                order.side.value,
                order.order_type.value,
                order.quantity,
                order.stop_price,
                time_ms,
            ),
        )

    def set_status(self, client_id: str, status: str, detail: str = "") -> None:
        self._db.execute(
            "UPDATE orders SET status = ?, detail = ? WHERE client_id = ?",
            (status, detail, client_id),
        )

    def open_orders(self) -> list[tuple[str, OrderRequest, int]]:
        """(client id, order, signal time) of orders not known to be finished.

        A crash may have lost these at the venue.
        """
        return [(c, o, t) for c, o, _, t in self._orders()]

    def pending(self) -> tuple[OrderRequest, ...]:
        return tuple(o for _, o, _, _ in self._orders())

    def _orders(self) -> list[tuple[str, OrderRequest, str, int]]:
        rows = self._db.execute(
            "SELECT client_id, symbol, side, quantity, order_type, stop_price, status,"
            " created_ms FROM orders WHERE status IN ('new', 'open')"
        ).fetchall()
        return [
            (r[0], OrderRequest(r[1], Side(r[2]), r[3], OrderType(r[4]), r[5]), r[6], r[7])
            for r in rows
        ]

    def apply_fill(
        self,
        fill: FillReport,
        on_booked: Callable[[float | None], dict[str, Any]] | None = None,
    ) -> bool:
        """Book a fill once. Returns False if it was already booked.

        ``on_booked`` receives the net P&L of a sale (None for a buy) and returns state
        to save in the same transaction. A crash can therefore never book a fill while
        losing its effect on the risk limits.
        """
        exists = self._db.execute("SELECT 1 FROM fills WHERE fill_id = ?", (fill.fill_id,))
        if exists.fetchone() is not None:
            return False
        pnl = self._apply(fill)
        state = on_booked(pnl) if on_booked is not None else {}
        self._db.execute("BEGIN")
        self._db.execute(
            "INSERT INTO fills (fill_id, client_id, symbol, side, quantity, price, fee, time_ms,"
            " reason, net_pnl, seq) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,"
            " (SELECT COALESCE(MAX(seq), 0) + 1 FROM fills))",
            (
                fill.fill_id,
                fill.client_id,
                fill.symbol,
                fill.side.value,
                fill.quantity,
                fill.price,
                fill.fee,
                fill.time_ms,
                fill.reason,
                pnl,
            ),
        )
        self._db.execute(
            "UPDATE orders SET status = 'filled' WHERE client_id = ?", (fill.client_id,)
        )
        for name, value in state.items():
            self._db.execute(
                "INSERT OR REPLACE INTO state (name, value) VALUES (?, ?)",
                (name, json.dumps(value)),
            )
        self._db.execute("COMMIT")
        return True

    def _apply(self, fill: FillReport) -> float | None:
        notional = fill.quantity * fill.price
        self.fees_paid += fill.fee
        if fill.side is Side.BUY:
            self.cash -= notional + fill.fee
            holding = self.holdings.setdefault(fill.symbol, Holding(0.0, 0.0))
            holding.quantity += fill.quantity
            holding.cost += notional + fill.fee
            stop_price = self._stop_of(fill.client_id)
            if stop_price is not None:
                holding.stops.append(
                    OrderRequest(fill.symbol, Side.SELL, fill.quantity, OrderType.STOP, stop_price)
                )
            return None
        self.cash += notional - fill.fee
        holding = self.holdings[fill.symbol]
        cost = holding.cost * fill.quantity / holding.quantity
        holding.quantity -= fill.quantity
        holding.cost -= cost
        if holding.quantity <= _DUST:
            del self.holdings[fill.symbol]
        return notional - fill.fee - cost

    def _stop_of(self, client_id: str) -> float | None:
        row = self._db.execute(
            "SELECT stop_price FROM orders WHERE client_id = ?", (client_id,)
        ).fetchone()
        return row[0] if row else None

    def positions(self) -> dict[str, float]:
        return {s: h.quantity for s, h in self.holdings.items()}

    def stops(self) -> tuple[OrderRequest, ...]:
        return tuple(stop for h in self.holdings.values() for stop in h.stops)

    def decide(self, time_ms: int, symbol: str, kind: str, detail: str) -> None:
        self._db.execute(
            "INSERT INTO decisions (time_ms, symbol, kind, detail) VALUES (?, ?, ?, ?)",
            (time_ms, symbol, kind, detail),
        )

    def decisions(self, since_ms: int = 0, limit: int = 1000) -> list[Decision]:
        rows = self._db.execute(
            "SELECT time_ms, symbol, kind, detail FROM decisions WHERE time_ms >= ?"
            " ORDER BY id DESC LIMIT ?",
            (since_ms, limit),
        ).fetchall()
        return [Decision(*r) for r in rows]

    def record_equity(self, time_ms: int, equity: float) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO equity (time_ms, equity, cash) VALUES (?, ?, ?)",
            (time_ms, equity, self.cash),
        )

    def equity_curve(self, since_ms: int = 0) -> list[tuple[int, float]]:
        query = "SELECT time_ms, equity FROM equity WHERE time_ms >= ? ORDER BY time_ms"
        return [(r[0], r[1]) for r in self._db.execute(query, (since_ms,)).fetchall()]

    def fills(self, since_ms: int = 0) -> list[dict[str, Any]]:
        columns = ("symbol", "side", "quantity", "price", "fee", "time_ms", "reason", "net_pnl")
        rows = self._db.execute(
            f"SELECT {', '.join(columns)} FROM fills WHERE time_ms >= ? ORDER BY seq",  # noqa: S608
            (since_ms,),
        ).fetchall()
        return [dict(zip(columns, r, strict=True)) for r in rows]

    def get_state(self, name: str) -> Any:
        row = self._db.execute("SELECT value FROM state WHERE name = ?", (name,)).fetchone()
        return json.loads(row[0]) if row else None

    def set_state(self, values: dict[str, Any]) -> None:
        """Write several values atomically, so a crash cannot store half a checkpoint."""
        self._db.execute("BEGIN")
        for name, value in values.items():
            self._db.execute(
                "INSERT OR REPLACE INTO state (name, value) VALUES (?, ?)",
                (name, json.dumps(value)),
            )
        self._db.execute("COMMIT")
