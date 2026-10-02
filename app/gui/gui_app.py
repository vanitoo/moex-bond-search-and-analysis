from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
for path in (str(PROJECT_ROOT), str(SRC_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from app.gui.streamlit_compat import install_streamlit_width_compat

install_streamlit_width_compat()

from app.gui.features.current import main


if __name__ == "__main__":
    main()
