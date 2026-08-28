"""Small SQLite read model for VegaGuard's durable paper-trading audit trail."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from hashlib import sha256
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
                CREATE TABLE IF NOT EXISTS iv_observation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    underlying TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    implied_volatility REAL NOT NULL,
                    source TEXT NOT NULL,
                    freshness_seconds REAL
                );
                CREATE INDEX IF NOT EXISTS iv_observation_history_lookup_idx
                    ON iv_observation_history(underlying, observed_at DESC);
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
                    opportunity_id TEXT,
                    plan_id TEXT,
                    production_threshold INTEGER NOT NULL DEFAULT 70,
                    exploration_threshold INTEGER,
                    data_timestamp TEXT,
                    reasons_json TEXT NOT NULL,
                    quote_timestamps_json TEXT NOT NULL,
                    spread_json TEXT,
                    evidence_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS shadow_candidates_observed_idx
                    ON shadow_candidates(observed_at);
                CREATE TABLE IF NOT EXISTS shadow_reprices (
                    candidate_id INTEGER NOT NULL,
                    horizon_minutes INTEGER NOT NULL,
                    repriced_at TEXT NOT NULL,
                    outcome_bucket TEXT NOT NULL,
                    outcome_json TEXT NOT NULL,
                    PRIMARY KEY(candidate_id, horizon_minutes),
                    FOREIGN KEY(candidate_id) REFERENCES shadow_candidates(id)
                );
                CREATE INDEX IF NOT EXISTS shadow_reprices_candidate_idx
                    ON shadow_reprices(candidate_id);
                CREATE TABLE IF NOT EXISTS risk_budget_rejections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    observed_at TEXT NOT NULL,
                    candidate_id INTEGER,
                    underlying TEXT NOT NULL,
                    score INTEGER,
                    trade_mode TEXT NOT NULL,
                    diagnostic_json TEXT NOT NULL,
                    FOREIGN KEY(candidate_id) REFERENCES shadow_candidates(id)
                );
                CREATE INDEX IF NOT EXISTS risk_budget_rejections_observed_idx
                    ON risk_budget_rejections(observed_at);
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
            if "evidence_json" not in candidate_columns:
                connection.execute(
                    "ALTER TABLE shadow_candidates ADD COLUMN evidence_json TEXT NOT NULL DEFAULT '{}'"
                )
            if "opportunity_id" not in candidate_columns:
                connection.execute("ALTER TABLE shadow_candidates ADD COLUMN opportunity_id TEXT")
            if "plan_id" not in candidate_columns:
                connection.execute("ALTER TABLE shadow_candidates ADD COLUMN plan_id TEXT")
            if "production_threshold" not in candidate_columns:
                connection.execute(
                    "ALTER TABLE shadow_candidates ADD COLUMN production_threshold INTEGER NOT NULL DEFAULT 70"
                )
            if "exploration_threshold" not in candidate_columns:
                connection.execute(
                    "ALTER TABLE shadow_candidates ADD COLUMN exploration_threshold INTEGER"
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS shadow_candidates_opportunity_idx "
                "ON shadow_candidates(opportunity_id, id)"
            )
            self._backfill_opportunity_ids(connection)

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

    def latest_event(self, event: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM events WHERE event = ? ORDER BY id DESC LIMIT 1", (event,)
            ).fetchone()
        return json.loads(row["payload_json"]) if row is not None else None

    @staticmethod
    def _backfill_opportunity_ids(connection: sqlite3.Connection) -> None:
        """Attach legacy observations to the same stable keys used by new scans."""
        rows = connection.execute(
            """
            SELECT id, underlying, trade_mode, regime, spread_json
              FROM shadow_candidates
             WHERE opportunity_id IS NULL
            """
        ).fetchall()
        for row in rows:
            spread = json.loads(row["spread_json"]) if row["spread_json"] else None
            legs = (
                f"{spread['long_symbol']}:{spread['short_symbol']}" if spread else "no_valid_spread"
            )
            key = f"{row['underlying']}|{row['trade_mode']}|{row['regime']}|{legs}"
            opportunity_id = f"opp-{sha256(key.encode()).hexdigest()[:20]}"
            connection.execute(
                "UPDATE shadow_candidates SET opportunity_id = ? WHERE id = ?",
                (opportunity_id, int(row["id"])),
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
        opportunity_id: str | None,
        data_timestamp: str | None,
        reasons: list[str],
        quote_timestamps: list[str],
        spread: dict[str, Any] | None,
        evidence: dict[str, Any] | None = None,
        plan_id: str | None = None,
        production_threshold: int = 70,
        exploration_threshold: int | None = None,
    ) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO shadow_candidates(
                    observed_at, underlying, classification, score, regime, baseline_regime,
                    score_threshold, trade_mode, opportunity_id,
                    plan_id, production_threshold, exploration_threshold, data_timestamp,
                    reasons_json, quote_timestamps_json, spread_json, evidence_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    opportunity_id,
                    plan_id,
                    production_threshold,
                    exploration_threshold,
                    data_timestamp,
                    json.dumps(reasons, separators=(",", ":")),
                    json.dumps(quote_timestamps, separators=(",", ":")),
                    json.dumps(spread, separators=(",", ":")) if spread is not None else None,
                    json.dumps(evidence or {}, separators=(",", ":")),
                ),
            )
            observation_id = int(cursor.lastrowid)
        # A grouped opportunity is a reporting concept.  Each observation
        # still needs its own point-in-time exit quotes, otherwise a later
        # scan inheriting an old opportunity could never be repriced.
        return observation_id

    def link_candidate_plan(self, candidate_id: int, plan_id: str) -> bool:
        """Bind a selected observation to one immutable plan exactly once."""
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE shadow_candidates SET plan_id = ?
                 WHERE id = ? AND plan_id IS NULL
                """,
                (plan_id, candidate_id),
            )
        return cursor.rowcount == 1

    def shadow_candidates(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM shadow_candidates ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            opportunities = self._opportunity_details(connection, rows)
            reprices = self._reprices_by_candidate_id(connection, [int(row["id"]) for row in rows])
        return [
            self._candidate_row(
                row,
                reprices.get(int(row["id"]), []),
                opportunities.get(str(row["opportunity_id"])) if row["opportunity_id"] else None,
            )
            for row in rows
        ]

    def record_risk_budget_rejection(
        self,
        *,
        observed_at: datetime,
        candidate_id: int | None,
        underlying: str,
        score: int | None,
        trade_mode: str,
        diagnostic: dict[str, Any],
    ) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO risk_budget_rejections(
                    observed_at, candidate_id, underlying, score, trade_mode, diagnostic_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    observed_at.astimezone(UTC).isoformat(),
                    candidate_id,
                    underlying,
                    score,
                    trade_mode,
                    json.dumps(diagnostic, separators=(",", ":")),
                ),
            )
        return int(cursor.lastrowid)

    def risk_budget_rejections(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM risk_budget_rejections ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            {
                **{key: value for key, value in dict(row).items() if key != "diagnostic_json"},
                "diagnostic": json.loads(row["diagnostic_json"]),
            }
            for row in rows
        ]

    def due_shadow_reprices(self, now: datetime) -> list[dict[str, Any]]:
        """Return each candidate/horizon pair that has reached 15, 30, or 60 minutes."""
        with self._connect() as connection:
            candidates = connection.execute(
                """
                SELECT * FROM shadow_candidates
                 WHERE spread_json IS NOT NULL
                 ORDER BY id ASC
                """
            ).fetchall()
            existing = {
                (int(row["candidate_id"]), int(row["horizon_minutes"]))
                for row in connection.execute(
                    "SELECT candidate_id, horizon_minutes FROM shadow_reprices"
                ).fetchall()
            }
        due: list[dict[str, Any]] = []
        grace_period = timedelta(minutes=10)
        for row in candidates:
            observed = datetime.fromisoformat(str(row["observed_at"])).astimezone(UTC)
            for horizon in (15, 30, 60):
                due_at = observed + timedelta(minutes=horizon)
                if (int(row["id"]), horizon) in existing or now < due_at:
                    continue
                due.append(
                    {
                        **dict(row),
                        "candidate_id": int(row["id"]),
                        "horizon_minutes": horizon,
                        "due_at": due_at.isoformat(),
                        "deadline_status": "overdue" if now > due_at + grace_period else "due",
                        "spread": json.loads(row["spread_json"]),
                        "evidence": json.loads(row["evidence_json"]),
                    }
                )
        return due

    def record_shadow_reprice(
        self,
        candidate_id: int,
        horizon_minutes: int,
        *,
        repriced_at: datetime,
        outcome_bucket: str,
        outcome: dict[str, Any],
    ) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO shadow_reprices(
                    candidate_id, horizon_minutes, repriced_at, outcome_bucket, outcome_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    candidate_id,
                    horizon_minutes,
                    repriced_at.astimezone(UTC).isoformat(),
                    outcome_bucket,
                    json.dumps(outcome, separators=(",", ":")),
                ),
            )
        return cursor.rowcount == 1

    def shadow_reprices(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT r.*, c.underlying, c.score, c.score_threshold, c.trade_mode, c.classification
                  FROM shadow_reprices r
                  JOIN shadow_candidates c ON c.id = r.candidate_id
                 ORDER BY r.repriced_at DESC, r.candidate_id DESC
                 LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [{**dict(row), "outcome": json.loads(row["outcome_json"])} for row in rows]

    def session_shadow_candidates(
        self, session_date: str, limit: int = 10_000
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM shadow_candidates
                 WHERE observed_at >= ? AND observed_at < ?
                 ORDER BY id DESC LIMIT ?
                """,
                (f"{session_date}T00:00:00", f"{session_date}T23:59:59.999999", limit),
            ).fetchall()
            opportunities = self._opportunity_details(connection, rows)
            reprices = self._reprices_by_candidate_id(connection, [int(row["id"]) for row in rows])
        return [
            self._candidate_row(
                row,
                reprices.get(int(row["id"]), []),
                opportunities.get(str(row["opportunity_id"])) if row["opportunity_id"] else None,
            )
            for row in rows
        ]

    def session_shadow_reprices(
        self, session_date: str, limit: int = 30_000
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT r.*, c.underlying, c.score, c.score_threshold, c.trade_mode, c.classification
                  FROM shadow_reprices r
                  JOIN shadow_candidates c ON c.id = r.candidate_id
                 WHERE c.observed_at >= ? AND c.observed_at < ?
                 ORDER BY r.repriced_at DESC, r.candidate_id DESC
                 LIMIT ?
                """,
                (f"{session_date}T00:00:00", f"{session_date}T23:59:59.999999", limit),
            ).fetchall()
        return [{**dict(row), "outcome": json.loads(row["outcome_json"])} for row in rows]

    @staticmethod
    def _candidate_row(
        row: sqlite3.Row,
        reprices: list[dict[str, Any]] | None = None,
        opportunity: tuple[int, int, str] | None = None,
    ) -> dict[str, Any]:
        candidate = {
            **{
                key: value
                for key, value in dict(row).items()
                if key
                not in {"reasons_json", "quote_timestamps_json", "spread_json", "evidence_json"}
            },
            "reasons": json.loads(row["reasons_json"]),
            "quote_timestamps": json.loads(row["quote_timestamps_json"]),
            "spread": json.loads(row["spread_json"]) if row["spread_json"] else None,
            "evidence": json.loads(row["evidence_json"]),
        }
        candidate_reprices = reprices or []
        candidate["reprices"] = candidate_reprices
        candidate["origin_candidate_id"] = opportunity[1] if opportunity else int(row["id"])
        candidate["observation_count"] = opportunity[0] if opportunity else 1
        candidate["reprice_status"] = PaperLedger._reprice_status(
            str(row["observed_at"]), candidate_reprices, datetime.now(UTC)
        )
        if candidate_reprices:
            candidate["latest_reprice"] = max(
                candidate_reprices, key=lambda item: item["repriced_at"]
            )
            outcome = candidate["latest_reprice"]["outcome"]
            if candidate["spread"] is not None and outcome.get("status") == "priced":
                candidate["spread"] = {
                    **candidate["spread"],
                    "exit_quote": outcome.get("exit_credit"),
                    "exit_quote_timestamps": [
                        outcome.get("long_quote_timestamp"),
                        outcome.get("short_quote_timestamp"),
                    ],
                    "costs_usd": outcome.get("total_costs_usd"),
                    "pnl_usd": outcome.get("net_hypothetical_pnl"),
                    "pnl_label": "hypothetical",
                }
        return candidate

    @staticmethod
    def _opportunity_details(
        connection: sqlite3.Connection, rows: list[sqlite3.Row]
    ) -> dict[str, tuple[int, int, str]]:
        opportunity_ids = sorted(
            {str(row["opportunity_id"]) for row in rows if row["opportunity_id"]}
        )
        if not opportunity_ids:
            return {}
        placeholders = ",".join("?" for _ in opportunity_ids)
        details = connection.execute(
            f"""
            SELECT grouped.opportunity_id, grouped.observation_count, grouped.origin_candidate_id,
                   origin.observed_at AS origin_observed_at
              FROM (
                  SELECT opportunity_id, COUNT(*) AS observation_count, MIN(id) AS origin_candidate_id
                    FROM shadow_candidates
                   WHERE opportunity_id IN ({placeholders})
                   GROUP BY opportunity_id
              ) AS grouped
              JOIN shadow_candidates AS origin ON origin.id = grouped.origin_candidate_id
            """,
            opportunity_ids,
        ).fetchall()
        return {
            str(row["opportunity_id"]): (
                int(row["observation_count"]),
                int(row["origin_candidate_id"]),
                str(row["origin_observed_at"]),
            )
            for row in details
        }

    @staticmethod
    def _reprice_status(
        observed_at: str, reprices: list[dict[str, Any]], now: datetime
    ) -> dict[str, Any]:
        observed = datetime.fromisoformat(observed_at).astimezone(UTC)
        by_horizon = {int(reprice["horizon_minutes"]): reprice for reprice in reprices}
        horizons: list[dict[str, Any]] = []
        for minutes in (15, 30, 60):
            due_at = observed + timedelta(minutes=minutes)
            reprice = by_horizon.get(minutes)
            if reprice is not None:
                outcome_status = str((reprice.get("outcome") or {}).get("status"))
                status = "completed" if outcome_status == "priced" else "quote_unavailable"
            elif now < due_at:
                status = f"pending_{minutes}m"
            else:
                status = f"overdue_{minutes}m"
            horizons.append(
                {
                    "horizon_minutes": minutes,
                    "due_at": due_at.isoformat(),
                    "status": status,
                }
            )
        if all(item["status"] == "completed" for item in horizons):
            overall = "completed"
        elif any(item["status"] == "quote_unavailable" for item in horizons):
            overall = "quote_unavailable"
        else:
            next_pending = next(
                (item["status"] for item in horizons if "pending" in item["status"]), None
            )
            next_overdue = next(
                (item["status"] for item in horizons if "overdue" in item["status"]), None
            )
            overall = next_pending or next_overdue or "completed"
        return {"status": overall, "horizons": horizons}

    @staticmethod
    def _reprices_by_candidate_id(
        connection: sqlite3.Connection, candidate_ids: list[int]
    ) -> dict[int, list[dict[str, Any]]]:
        if not candidate_ids:
            return {}
        placeholders = ",".join("?" for _ in candidate_ids)
        rows = connection.execute(
            f"""
            SELECT candidate_id, horizon_minutes, repriced_at, outcome_bucket, outcome_json
              FROM shadow_reprices
             WHERE candidate_id IN ({placeholders})
             ORDER BY repriced_at ASC, horizon_minutes ASC
            """,
            candidate_ids,
        ).fetchall()
        grouped: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            candidate_id = int(row["candidate_id"])
            grouped.setdefault(candidate_id, []).append(
                {
                    "horizon_minutes": int(row["horizon_minutes"]),
                    "repriced_at": row["repriced_at"],
                    "outcome_bucket": row["outcome_bucket"],
                    "outcome": json.loads(row["outcome_json"]),
                }
            )
        return grouped

    def event_count(self) -> int:
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM events").fetchone()[0])

    def latest_iv_observation(
        self, underlying: str, *, as_of: datetime | None = None
    ) -> tuple[datetime, float] | None:
        as_of_timestamp = _utc_timestamp(as_of) if as_of is not None else None
        with self._connect() as connection:
            if as_of_timestamp is None:
                row = connection.execute(
                    """
                    SELECT observed_at, implied_volatility
                      FROM iv_observations
                     WHERE underlying = ?
                    """,
                    (underlying,),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT observed_at, implied_volatility
                      FROM iv_observation_history
                     WHERE underlying = ? AND observed_at <= ?
                     ORDER BY observed_at DESC, id DESC
                     LIMIT 1
                    """,
                    (underlying, as_of_timestamp),
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
            connection.execute(
                """
                INSERT INTO iv_observation_history(
                    underlying, observed_at, implied_volatility, source, freshness_seconds
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (underlying, timestamp, implied_volatility, source, freshness_seconds),
            )

    def iv_observation_history(
        self, underlying: str, *, as_of: datetime | None = None, limit: int = 252
    ) -> list[float]:
        as_of_timestamp = _utc_timestamp(as_of) if as_of is not None else None
        with self._connect() as connection:
            if as_of_timestamp is None:
                rows = connection.execute(
                    """
                    SELECT implied_volatility FROM iv_observation_history
                     WHERE underlying = ?
                     ORDER BY observed_at DESC, id DESC
                     LIMIT ?
                    """,
                    (underlying, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT implied_volatility FROM iv_observation_history
                     WHERE underlying = ? AND observed_at <= ?
                     ORDER BY observed_at DESC, id DESC
                     LIMIT ?
                    """,
                    (underlying, as_of_timestamp, limit),
                ).fetchall()
        return [float(row["implied_volatility"]) for row in reversed(rows)]


def _utc_timestamp(value: datetime) -> str:
    """Normalize a caller-supplied as-of value before lexical SQLite comparison."""
    return (
        value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    ).isoformat()
