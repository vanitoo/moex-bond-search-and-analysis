import os
from pathlib import Path

from app.core.runtime_env import build_subprocess_env, runtime_pythonpath


def test_runtime_pythonpath_has_expected_project_roots(tmp_path: Path):
    paths = runtime_pythonpath(tmp_path)
    assert paths == [
        str(tmp_path),
        str(tmp_path / "src"),
    ]


def test_subprocess_env_enables_utf8_and_unbuffered(tmp_path: Path):
    env = build_subprocess_env(tmp_path)
    assert env["PYTHONUTF8"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["PYTHONUNBUFFERED"] == "1"
    parts = env["PYTHONPATH"].split(os.pathsep)
    assert str(tmp_path) in parts
    assert str(tmp_path / "src") in parts
    assert str(tmp_path / "app" / "core") not in parts
    assert str(tmp_path / "app" / "portfolio") not in parts
