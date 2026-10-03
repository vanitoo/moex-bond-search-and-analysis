from __future__ import annotations

from app.gui.streamlit_compat import install_streamlit_width_compat

install_streamlit_width_compat()

from app.gui.features.current import main


if __name__ == "__main__":
    main()
