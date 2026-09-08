from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import gui_app_v2 as base
import gui_app_v6 as v6


_original_module_state = base.module_state


def _latest_module_event(run_dir: Path, key: str) -> dict[str, Any] | None:
    trace = run_dir / "decisions" / "module_results.jsonl"
    if not trace.exists():
        return None
    latest: dict[str, Any] | None = None
    for line in trace.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("module") == key:
            latest = event
    return latest


def module_state(run_dir: Path, key: str) -> dict[str, Any]:
    state = _original_module_state(run_dir, key)
    if state.get("file") is not None:
        return state

    event = _latest_module_event(run_dir, key)
    if not event:
        return state

    status = str(event.get("status") or "")
    mode = str(event.get("mode") or "information")
    if status == "ERROR" and mode == "information":
        trace = run_dir / "decisions" / "module_results.jsonl"
        timestamp = str(event.get("timestamp") or "")
        try:
            updated = datetime.fromisoformat(timestamp).strftime("%d.%m.%Y %H:%M")
        except ValueError:
            updated = "—"
        return {
            "status": "Источник недоступен",
            "updated": updated,
            "file": trace,
            "degraded": True,
            "reason": event.get("reason") or "Внешний источник данных недоступен",
        }
    return state


def main() -> None:
    base.module_state = module_state
    v6.main()


if __name__ == "__main__":
    main()
