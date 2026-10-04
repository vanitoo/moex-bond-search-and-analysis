from pathlib import Path

from app.core.process_runner import entrypoint_command, module_command, python_command


def test_python_command_uses_explicit_interpreter():
    assert python_command("script.py", "--flag", python=Path("/venv/python")) == [
        "/venv/python",
        "script.py",
        "--flag",
    ]


def test_module_command_builds_package_execution():
    assert module_command(
        "app.stages.8_bonds_decision",
        ["--config", "configs/gui_active.json"],
        python="python",
    ) == [
        "python",
        "-m",
        "app.stages.8_bonds_decision",
        "--config",
        "configs/gui_active.json",
    ]


def test_entrypoint_command_builds_file_execution():
    assert entrypoint_command(
        "bondlab.py",
        ["monitor", "--portfolio", "Main"],
        python="python",
    ) == [
        "python",
        "bondlab.py",
        "monitor",
        "--portfolio",
        "Main",
    ]
