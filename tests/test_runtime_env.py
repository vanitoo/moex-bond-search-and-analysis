import os
from pathlib import Path

from runtime_env import build_subprocess_env, runtime_pythonpath


def test_runtime_pythonpath_has_expected_project_roots(tmp_path: Path):
    paths = runtime_pythonpath(tmp_path)
    assert paths[:5] == [
        str(tmp_path / "app" / "core"),
        str(tmp_path / "app" / "portfolio"),
        str(tmp_path / "app"),
        str(tmp_path / "src"),
        str(tmp_path),
    ]


def test_subprocess_env_enables_utf8_and_unbuffered(tmp_path: Path):
    env = build_subprocess_env(tmp_path)
    assert env["PYTHONUTF8"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["PYTHONUNBUFFERED"] == "1"
    assert str(tmp_path / "src") in env["PYTHONPATH"].split(os.pathsep)
