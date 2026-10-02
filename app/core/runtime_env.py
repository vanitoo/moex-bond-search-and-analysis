from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


def runtime_pythonpath(project_root: Path, extra: Iterable[Path] = ()) -> list[str]:
    """Return the import roots required by legacy stage subprocesses."""

    app_root = project_root / "app"
    paths = [
        app_root / "core",
        app_root / "portfolio",
        app_root,
        project_root / "src",
        project_root,
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
    return env
