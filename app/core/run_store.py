from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class RunStore:
    path: Path

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS pipeline_runs (
                run_id TEXT PRIMARY KEY,
                run_dir TEXT NOT NULL,
                strategy TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                schema_version INTEGER NOT NULL
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS stage_results (
                run_id TEXT NOT NULL,
                module TEXT NOT NULL,
                secid TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                stored_at TEXT NOT NULL,
                PRIMARY KEY (run_id, module, secid, ordinal),
                FOREIGN KEY (run_id) REFERENCES pipeline_runs(run_id) ON DELETE CASCADE
            )"""
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_stage_results_run_module ON stage_results(run_id, module)"
        )
        return connection

    def ensure_run(self, run_id: str, run_dir: Path, *, strategy: str | None = None) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as db:
            db.execute(
                """INSERT INTO pipeline_runs(run_id, run_dir, strategy, created_at, updated_at, schema_version)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(run_id) DO UPDATE SET
                     run_dir=excluded.run_dir,
                     strategy=COALESCE(excluded.strategy, pipeline_runs.strategy),
                     updated_at=excluded.updated_at,
                     schema_version=excluded.schema_version""",
                (run_id, str(run_dir), strategy, now, now, SCHEMA_VERSION),
            )

    def write_frame(self, run_id: str, module: str, frame: pd.DataFrame) -> None:
        rows: list[tuple[str, str, str, int, str, str]] = []
        stored_at = datetime.now().isoformat(timespec="seconds")
        for ordinal, (_, row) in enumerate(frame.iterrows()):
            payload = {str(key): _json_value(value) for key, value in row.items()}
            secid = str(
                payload.get("Код ценной бумаги")
                or payload.get("SECID")
                or payload.get("secid")
                or ""
            ).strip().upper()
            rows.append((run_id, module, secid, ordinal, json.dumps(payload, ensure_ascii=False), stored_at))
        with self._connect() as db:
            db.execute("DELETE FROM stage_results WHERE run_id=? AND module=?", (run_id, module))
            db.executemany(
                """INSERT INTO stage_results(run_id, module, secid, ordinal, payload_json, stored_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                rows,
            )
            db.execute(
                "UPDATE pipeline_runs SET updated_at=? WHERE run_id=?",
                (stored_at, run_id),
            )

    def read_frame(self, run_id: str, module: str) -> pd.DataFrame | None:
        with self._connect() as db:
            rows = db.execute(
                """SELECT payload_json FROM stage_results
                   WHERE run_id=? AND module=? ORDER BY ordinal""",
                (run_id, module),
            ).fetchall()
        if not rows:
            return None
        return pd.DataFrame([json.loads(row[0]) for row in rows])

    def modules(self, run_id: str) -> tuple[str, ...]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT DISTINCT module FROM stage_results WHERE run_id=? ORDER BY module",
                (run_id,),
            ).fetchall()
        return tuple(row[0] for row in rows)


def run_id_for(run_dir: Path) -> str:
    return run_dir.expanduser().resolve().name


def default_store_path(project_root: Path) -> Path:
    return project_root / "data" / "bondlab.db"


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            return _json_value(value.item())
        except Exception:
            pass
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
