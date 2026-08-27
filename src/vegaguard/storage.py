"""Small SQLite read model for VegaGuard's durable paper-trading audit trail."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class PaperLedger:
    """Append-only event store plus immutable selected-vs-shadow trade records.

    JSONL remains the human-readable audit artifact. This store makes the same
    information queryable for the dashboard without allowing a later process to
    rewrite a past decision.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event TEXT NOT NULL,
                    client_order_id TEXT,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_client_order_id_idx
                    ON events(client_order_id);
                CREATE TABLE IF NOT EXISTS shadow_trades (
                    client_order_id TEXT PRIMARY KEY,
                    underlying TEXT NOT NULL,
                    regime TEXT NOT NULL,
                    trade_mode TEXT NOT NULL DEFAULT 'production',
                    created_at TEXT NOT NULL,
                    selected_plan_json TEXT NOT NULL,
                    shadow_kind TEXT NOT NULL,
                    shadow_plan_json TEXT NOT NULL,
                    closed_at TEXT,
                    selected_net_pnl REAL,
                    shadow_net_pnl REAL,
                    close_reason TEXT
                );
                CREATE TABLE IF NOT EXISTS iv_observations (
                    underlying TEXT PRIMARY KEY,
                    observed_at TEXT NOT NULL,
                    implied_volatility REAL NOT NULL,
                    source TEXT NOT NULL DEFAULT 'official',
                    freshness_seconds REAL
                );
                CREATE TABLE IF NOT EXISTS shadow_candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    observed_at TEXT NOT NULL,
                    underlying TEXT NOT NULL,
                    classification TEXT NOT NULL,
                    score INTEGER,
                    regime TEXT NOT NULL,
                    baseline_regime TEXT NOT NULL DEFAULT 'no_trade',
                    score_threshold INTEGER NOT NULL DEFAULT 70,
                    trade_mode TEXT NOT NULL DEFAULT 'production',
                    data_timestamp TEXT,
                    reasons_json TEXT NOT NULL,
                    quote_timestamps_json TEXT NOT NULL,
                    spread_json TEXT
                );
                CREATE INDEX IF NOT EXISTS shadow_candidates_observed_idx
                    ON shadow_candidates(observed_at);
                """
            )
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(iv_observations)").fetchall()
            }
            if "source" not in columns:
                connection.execute(
                    "ALTER TABLE iv_observations ADD COLUMN source TEXT NOT NULL DEFAULT 'official'"
                )
            if "freshness_seconds" not in columns:
                connection.execute("ALTER TABLE iv_observations ADD COLUMN freshness_seconds REAL")
            shadow_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(shadow_trades)").fetchall()
            }
            if "trade_mode" not in shadow_columns:
                connection.execute(
                    "ALTER TABLE shadow_trades ADD COLUMN trade_mode TEXT NOT NULL DEFAULT 'production'"
                )
            candidate_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(shadow_candidates)").fetchall()
            }
            if "score_threshold" not in candidate_columns:
                connection.execute(
                    "ALTER TABLE shadow_candidates ADD COLUMN score_threshold INTEGER NOT NULL DEFAULT 70"
                )
            if "trade_mode" not in candidate_columns:
                connection.execute(
                    "ALTER TABLE shadow_candidates ADD COLUMN trade_mode TEXT NOT NULL DEFAULT 'production'"
                )
            if "baseline_regime" not in candidate_columns:
                connection.execute(
                    "ALTER TABLE shadow_candidates ADD COLUMN baseline_regime TEXT NOT NULL DEFAULT 'no_trade'"
                )

    def append_event(self, entry: Any) -> None:
        payload = entry.model_dump(mode="json")
        plan = payload.get("plan") or {}
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO events(timestamp, event, client_order_id, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    payload["timestamp"],
                    payload["event"],
                    plan.get("client_order_id")
                    or payload.get("payload", {}).get("client_order_id"),
                    json.dumps(payload, separators=(",", ":")),
                ),
            )

    def register_shadow(
        self,
        plan: Any,
        *,
        regime: str,
        shadow_kind: str = "no_trade",
        shadow_plan: dict[str, Any] | None = None,
    ) -> bool:
        """Persist the alternative at decision time; never overwrite it later."""
        selected = plan.model_dump(mode="json")
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO shadow_trades(
                    client_order_id, underlying, regime, trade_mode, created_at, selected_plan_json,
                    shadow_kind, shadow_plan_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan.client_order_id,
                    plan.underlying,
                    regime,
                    plan.trade_mode,
                    datetime.now(UTC).isoformat(),
                    json.dumps(selected, separators=(",", ":")),
                    shadow_kind,
                    json.dumps(shadow_plan or {"kind": shadow_kind}, separators=(",", ":")),
                ),
            )
        return cursor.rowcount == 1

    def record_shadow_outcome(
        self,
        client_order_id: str,
        *,
        selected_net_pnl: float,
        shadow_net_pnl: float,
        close_reason: str,
    ) -> bool:
        """Close a shadow record once. Historical outcomes are immutable."""
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE shadow_trades
                   SET closed_at = ?, selected_net_pnl = ?, shadow_net_pnl = ?, close_reason = ?
                 WHERE client_order_id = ? AND closed_at IS NULL
                """,
                (
                    datetime.now(UTC).isoformat(),
                    selected_net_pnl,
                    shadow_net_pnl,
                    close_reason,
                    client_order_id,
                ),
            )
        return cursor.rowcount == 1

    def shadows(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM shadow_trades ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            {
                **dict(row),
                "selected_plan": json.loads(row["selected_plan_json"]),
                "shadow_plan": json.loads(row["shadow_plan_json"]),
            }
            for row in rows
        ]

    def record_shadow_candidate(
        self,
        *,
        observed_at: datetime,
        underlying: str,
        classification: str,
        score: int | None,
        regime: str,
        baseline_regime: str,
        score_threshold: int,
        trade_mode: str,
        data_timestamp: str | None,
        reasons: list[str],
        quote_timestamps: list[str],
        spread: dict[str, Any] | None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO shadow_candidates(
                    observed_at, underlying, classification, score, regime, baseline_regime,
                    score_threshold, trade_mode,
                    data_timestamp,
                    reasons_json, quote_timestamps_json, spread_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observed_at.astimezone(UTC).isoformat(),
                    underlying,
                    classification,
                    score,
                    regime,
                    baseline_regime,
                    score_threshold,
                    trade_mode,
                    data_timestamp,
                    json.dumps(reasons, separators=(",", ":")),
                    json.dumps(quote_timestamps, separators=(",", ":")),
                    json.dumps(spread, separators=(",", ":")) if spread is not None else None,
                ),
            )

    def shadow_candidates(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM shadow_candidates ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            {
                **{
                    key: value
                    for key, value in dict(row).items()
                    if key not in {"reasons_json", "quote_timestamps_json", "spread_json"}
                },
                "reasons": json.loads(row["reasons_json"]),
                "quote_timestamps": json.loads(row["quote_timestamps_json"]),
                "spread": json.loads(row["spread_json"]) if row["spread_json"] else None,
            }
            for row in rows
        ]

    def event_count(self) -> int:
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM events").fetchone()[0])

    def latest_iv_observation(self, underlying: str) -> tuple[datetime, float] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT observed_at, implied_volatility
                  FROM iv_observations
                 WHERE underlying = ?
                """,
                (underlying,),
            ).fetchone()
        if row is None:
            return None
        observed_at = datetime.fromisoformat(str(row["observed_at"]))
        observed_at = (
            observed_at.replace(tzinfo=UTC)
            if observed_at.tzinfo is None
            else observed_at.astimezone(UTC)
        )
        return observed_at, float(row["implied_volatility"])

    def record_iv_observation(
        self,
        underlying: str,
        observed_at: datetime,
        implied_volatility: float,
        *,
        source: str,
        freshness_seconds: float | None,
    ) -> None:
        timestamp = observed_at.astimezone(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO iv_observations(
                    underlying, observed_at, implied_volatility, source, freshness_seconds
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(underlying) DO UPDATE SET
                    observed_at = excluded.observed_at,
                    implied_volatility = excluded.implied_volatility,
                    source = excluded.source,
                    freshness_seconds = excluded.freshness_seconds
                WHERE excluded.observed_at >= iv_observations.observed_at
                """,
                (underlying, timestamp, implied_volatility, source, freshness_seconds),
            )
