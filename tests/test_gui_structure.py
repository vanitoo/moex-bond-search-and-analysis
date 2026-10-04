from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FEATURES = ROOT / "app" / "gui" / "features"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_current_is_the_only_feature_with_main():
    offenders: list[str] = []
    for path in FEATURES.glob("*.py"):
        if path.name in {"current.py", "__init__.py"}:
            continue
        mains = [
            node
            for node in _tree(path).body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main"
        ]
        if mains:
            offenders.append(path.name)
    assert offenders == []


def test_feature_modules_do_not_use_historical_version_aliases():
    offenders: list[str] = []
    pattern = re.compile(r"\bas\s+v\d+\b|_v\d+\b")
    for path in FEATURES.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if pattern.search(text):
            offenders.append(path.name)
    assert offenders == []


def test_current_shell_does_not_monkeypatch_other_modules():
    path = FEATURES / "current.py"
    assignments: list[str] = []
    for node in ast.walk(_tree(path)):
        if not isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                assignments.append(f"{target.value.id}.{target.attr}")
    assert assignments == []
