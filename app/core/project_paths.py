from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = PROJECT_ROOT / "app"
SRC_ROOT = PROJECT_ROOT / "src"
RUNS_ROOT = PROJECT_ROOT / "runs"
DATA_ROOT = PROJECT_ROOT / "data"
REPORTS_ROOT = PROJECT_ROOT / "reports"
CONFIGS_ROOT = PROJECT_ROOT / "configs"
DEFAULT_CONFIG = CONFIGS_ROOT / "balanced.json"
GUI_CONFIG = CONFIGS_ROOT / "gui_active.json"
VIRTUAL_PORTFOLIOS_ROOT = DATA_ROOT / "virtual_portfolios"
PORTFOLIO_HISTORY_ROOT = DATA_ROOT / "portfolio_monitor_history"
PORTFOLIO_MONITOR_RUNS_ROOT = DATA_ROOT / "portfolio_monitor_runs"
