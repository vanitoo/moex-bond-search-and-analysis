from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

from app.core.project_paths import PROJECT_ROOT
from app.core.runtime_env import build_subprocess_env


def python_command(*parts: object, python: str | Path | None = None) -> list[str]:
    """Build a Python command without leaking executable/path logic to callers."""

    executable = str(python or sys.executable)
    return [executable, *(str(part) for part in parts)]


def module_command(
    module: str,
    args: Iterable[object] = (),
    *,
    python: str | Path | None = None,
) -> list[str]:
    """Build a package-module command."""

    return python_command("-m", module, *args, python=python)


def entrypoint_command(
    entrypoint: str | Path,
    args: Iterable[object] = (),
    *,
    python: str | Path | None = None,
) -> list[str]:
    """Build a Python entrypoint command."""

    return python_command(entrypoint, *args, python=python)


def run_command(
    command: Sequence[object],
    *,
    cwd: Path = PROJECT_ROOT,
    project_root: Path = PROJECT_ROOT,
    check: bool = True,
    **kwargs: Any,
) -> subprocess.CompletedProcess[Any]:
    """Run a project subprocess with the canonical runtime environment."""

    options = dict(kwargs)
    options.setdefault("env", build_subprocess_env(project_root))
    return subprocess.run(
        [str(part) for part in command],
        cwd=cwd,
        check=check,
        **options,
    )


def run_module(
    module: str,
    args: Iterable[object] = (),
    *,
    cwd: Path = PROJECT_ROOT,
    project_root: Path = PROJECT_ROOT,
    check: bool = True,
    python: str | Path | None = None,
    **kwargs: Any,
) -> subprocess.CompletedProcess[Any]:
    """Run an application package module using the canonical environment."""

    return run_command(
        module_command(module, args, python=python),
        cwd=cwd,
        project_root=project_root,
        check=check,
        **kwargs,
    )


def popen_command(
    command: Sequence[object],
    *,
    cwd: Path = PROJECT_ROOT,
    project_root: Path = PROJECT_ROOT,
    **kwargs: Any,
) -> subprocess.Popen[Any]:
    """Start a long-running project subprocess with the canonical environment."""

    options = dict(kwargs)
    options.setdefault("env", build_subprocess_env(project_root))
    return subprocess.Popen(
        [str(part) for part in command],
        cwd=cwd,
        **options,
    )
