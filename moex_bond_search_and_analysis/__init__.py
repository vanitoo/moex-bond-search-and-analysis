"""Compatibility shim for running repository entrypoint scripts without installation.

The project uses a src/ layout. When a root-level script is executed directly,
Python adds the repository root to sys.path but not src/. Extending this package
path lets imports such as ``moex_bond_search_and_analysis.rating_signal`` resolve
from src/moex_bond_search_and_analysis in direct-script and subprocess runs.
"""
from pathlib import Path

_src_package = Path(__file__).resolve().parent.parent / "src" / "moex_bond_search_and_analysis"
if _src_package.is_dir():
    __path__.append(str(_src_package))
