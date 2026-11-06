"""Experiment registry: every backtest run is counted (needed for deflated Sharpe, PBO).

Rows are only ever added. ``trial_number`` counts all runs of a strategy, kept or not.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sentinel_quant

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    trial_number INTEGER NOT NULL,
    code_hash TEXT NOT NULL,
    dataset_ids TEXT NOT NULL,
    config TEXT NOT NULL,
    seed INTEGER,
    metrics TEXT NOT NULL
)
"""


@dataclass(frozen=True)
class RunRecord:
    id: int
    created_at: str
    strategy_id: str
    trial_number: int
    code_hash: str
    dataset_ids: tuple[str, ...]
    config: dict[str, Any]
    seed: int | None
    metrics: dict[str, Any]


def code_hash() -> str:
    """Hash of the package source, so uncommitted changes are distinguishable."""
    root = Path(sentinel_quant.__file__).parent
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


class Registry:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def record(
        self,
        strategy_id: str,
        dataset_ids: Sequence[str],
        config: Mapping[str, Any],
        metrics: Mapping[str, Any],
        seed: int | None = None,
    ) -> RunRecord:
        created_at = datetime.now(tz=UTC).isoformat()
        with self._connect() as connection:
            trial = self.trials(strategy_id) + 1
            cursor = connection.execute(
                "INSERT INTO runs (created_at, strategy_id, trial_number, code_hash,"
                " dataset_ids, config, seed, metrics) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    created_at,
                    strategy_id,
                    trial,
                    code_hash(),
                    json.dumps(list(dataset_ids)),
                    json.dumps(config, sort_keys=True, default=str),
                    seed,
                    json.dumps(metrics, sort_keys=True, default=str),
                ),
            )
            run_id = cursor.lastrowid
        assert run_id is not None
        return next(r for r in self.runs(strategy_id) if r.id == run_id)

    def trials(self, strategy_id: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM runs WHERE strategy_id = ?", (strategy_id,)
            ).fetchone()
        return int(row[0])

    def runs(self, strategy_id: str | None = None) -> list[RunRecord]:
        query = "SELECT * FROM runs"
        params: tuple[str, ...] = ()
        if strategy_id is not None:
            query += " WHERE strategy_id = ?"
            params = (strategy_id,)
        with self._connect() as connection:
            rows = connection.execute(query + " ORDER BY id", params).fetchall()
        return [
            RunRecord(
                id=r[0],
                created_at=r[1],
                strategy_id=r[2],
                trial_number=r[3],
                code_hash=r[4],
                dataset_ids=tuple(json.loads(r[5])),
                config=json.loads(r[6]),
                seed=r[7],
                metrics=json.loads(r[8]),
            )
            for r in rows
        ]
