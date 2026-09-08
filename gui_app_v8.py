from __future__ import annotations

import json

import streamlit as st
import streamlit.components.v1 as components

import gui_app_v2 as base
import gui_app_v6 as v6
import gui_app_v7 as v7


def _render_copy_log(log: str) -> None:
    """Показывает явную кнопку копирования полного pipeline-лога."""
    payload = json.dumps(log, ensure_ascii=False).replace("</", "<\\/")
    components.html(
        f"""
        <div style="display:flex;gap:8px;align-items:center;font-family:sans-serif">
          <button id="copy-log" style="padding:8px 14px;cursor:pointer;border:1px solid #999;border-radius:6px;background:white">
            📋 Скопировать лог
          </button>
          <span id="copy-status" style="font-size:13px"></span>
        </div>
        <script>
          const text = {payload};
          const button = document.getElementById('copy-log');
          const status = document.getElementById('copy-status');
          async function copyText() {{
            try {{
              await navigator.clipboard.writeText(text);
              status.textContent = 'Скопировано';
            }} catch (e) {{
              const area = document.createElement('textarea');
              area.value = text;
              area.style.position = 'fixed';
              area.style.opacity = '0';
              document.body.appendChild(area);
              area.focus();
              area.select();
              const ok = document.execCommand('copy');
              document.body.removeChild(area);
              status.textContent = ok ? 'Скопировано' : 'Не удалось скопировать';
            }}
          }}
          button.addEventListener('click', copyText);
        </script>
        """,
        height=48,
    )


def run_with_ui(run_dir, selected, config, refresh_ratings) -> None:
    config_path = base.save_gui_config(config)
    with st.status("Pipeline выполняется…", expanded=True) as status:
        code, log = base.execute_modules(run_dir, selected, config_path, refresh_ratings)
        log_path = run_dir / "gui_last_run.log"
        log_path.write_text(log, encoding="utf-8")
        _render_copy_log(log)
        if code == 0:
            status.update(label="Анализ успешно завершён", state="complete")
            st.success("Готово. Единый bonds_master.json также обновлён.")
            if st.button("Обновить страницу", type="primary"):
                st.rerun()
        else:
            status.update(label=f"Ошибка выполнения, код {code}", state="error")
            st.error(f"Лог сохранён: {log_path}")


def main() -> None:
    base.module_state = v7.module_state
    base.run_with_ui = run_with_ui
    v6.main()


if __name__ == "__main__":
    main()
