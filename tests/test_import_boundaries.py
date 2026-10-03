from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
TESTS = ROOT / "tests"


def _python_files(root: Path):
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def _internal_module_names() -> set[str]:
    names: set[str] = set()
    for folder in (APP / "core", APP / "portfolio", APP / "gui" / "features"):
        names.update(path.stem for path in folder.glob("*.py") if path.name != "__init__.py")
    return names


def test_active_runtime_does_not_mutate_sys_path():
    offenders: list[str] = []
    for path in _python_files(APP):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute) or node.attr != "path":
                continue
            if isinstance(node.value, ast.Name) and node.value.id == "sys":
                offenders.append(str(path.relative_to(ROOT)))
                break
    assert offenders == []


def test_runtime_and_tests_do_not_use_internal_modules_as_top_level_imports():
    local_names = _internal_module_names()
    offenders: list[str] = []
    for base in (APP, TESTS):
        for path in _python_files(base):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                module = ""
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.split(".", 1)[0] in local_names:
                            offenders.append(f"{path.relative_to(ROOT)}: import {alias.name}")
                    continue
                root_name = module.split(".", 1)[0]
                if root_name in local_names:
                    offenders.append(f"{path.relative_to(ROOT)}: from {module}")
    assert offenders == []
