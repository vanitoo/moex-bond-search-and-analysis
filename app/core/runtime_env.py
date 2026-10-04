from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


def runtime_pythonpath(project_root: Path, extra: Iterable[Path] = ()) -> list[str]:
    """Return the import roots required by application subprocesses."""

    # Runtime code imports application modules through the app.* package
    # and integrations through the src-layout package. Keep PYTHONPATH limited
    # to those two import roots instead of exposing internal directories as
    # top-level modules.
    paths = [
        project_root,
        project_root / "src",
        *extra,
    ]
    seen: set[str] = set()
    result: list[str] = []
    for path in paths:
        value = str(path)
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def build_subprocess_env(
    project_root: Path,
    *,
    unbuffered: bool = True,
    utf8: bool = True,
    run_id: str | None = None,
    run_store: Path | None = None,
) -> dict[str, str]:
    env = os.environ.copy()
    pythonpath = runtime_pythonpath(project_root)
    existing = env.get("PYTHONPATH")
    if existing:
        pythonpath.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath)
    if utf8:
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
    if unbuffered:
        env["PYTHONUNBUFFERED"] = "1"
    if run_id:
        env["BONDLAB_RUN_ID"] = run_id
    if run_store:
        env["BONDLAB_RUN_STORE"] = str(run_store)
    return env
