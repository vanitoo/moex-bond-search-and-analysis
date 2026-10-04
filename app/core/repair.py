from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.data_quality import load_quality_report, repair_start_stage, repairable_sources
from app.core.process_runner import entrypoint_command, run_command
from app.core.project_paths import PROJECT_ROOT


def run_repair(
    run_dir: Path,
    *,
    config: Path,
    module: str | None = None,
    attempts: int = 1,
    project_root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    from app.core.data_quality import REPAIR_STAGE

    run_dir = run_dir.expanduser().resolve()
    if attempts < 1:
        raise ValueError("attempts должен быть >= 1")
    report = load_quality_report(run_dir)
    if report is None:
        raise FileNotFoundError(f"Нет Data Quality report: {run_dir / 'decisions' / 'data_quality.json'}")

    if module:
        if module not in REPAIR_STAGE:
            raise ValueError(f"Неизвестный repair module: {module}. Доступны: {', '.join(sorted(REPAIR_STAGE))}")
        requested_start = REPAIR_STAGE[module]
    else:
        requested_start = repair_start_stage(report)
        if requested_start is None:
            return {"repaired": False, "attempts": 0, "report": report, "sources": []}

    used = 0
    sources: list[str] = []
    for attempt in range(1, attempts + 1):
        report = load_quality_report(run_dir) or report
        sources = [module] if module else repairable_sources(report)
        start_stage = requested_start if module else repair_start_stage(report)
        if start_stage is None:
            break
        print(f"\n↻ AUTO REPAIR {attempt}/{attempts}: {', '.join(sources)}")
        print(f"Повторяем stage {start_stage} → 10 в том же run: {run_dir.name}")
        command = entrypoint_command(project_root / "bondlab.py", [
            "pipeline", "--from-stage", str(start_stage), "--to-stage", "10",
            "--run-dir", str(run_dir), "--config", str(config.expanduser().resolve()),
        ])
        run_command(command, cwd=project_root, project_root=project_root)
        used += 1
        if module:
            break
        report = load_quality_report(run_dir) or report
        if repair_start_stage(report) is None:
            break

    return {"repaired": used > 0, "attempts": used, "report": load_quality_report(run_dir) or report, "sources": sources}
