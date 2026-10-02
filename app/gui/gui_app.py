from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = APP_DIR / "core"
PORTFOLIO_DIR = APP_DIR / "portfolio"
GUI_DIR = APP_DIR / "gui"
LAYERS_DIR = GUI_DIR / "layers"
SRC_DIR = PROJECT_ROOT / "src"

for path in (
    str(LAYERS_DIR),
    str(GUI_DIR),
    str(CORE_DIR),
    str(PORTFOLIO_DIR),
    str(APP_DIR),
    str(SRC_DIR),
    str(PROJECT_ROOT),
):
    if path not in sys.path:
        sys.path.insert(0, path)

from streamlit_compat import install_streamlit_width_compat

install_streamlit_width_compat()

from gui_app_v16 import main


if __name__ == "__main__":
    main()
