from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "balanced.json"
TODAY_RUN = PROJECT_ROOT / f"bond_{datetime.now():%Y_%m_%d}"

MODULES = [
    ("market_search", "1. Поиск облигаций", "Долгий этап: полный скан рынка"),
    ("cashflow", "2. Денежные потоки", "Купоны, оферты, погашения"),
    ("news_search", "3а. Поиск новостей", "Скачивание и обновление локальных новостей"),
    ("news", "3б. Анализ новостей", "Риски, позитивные события, стоп-факторы"),
    ("liquidity", "4б. Ликвидность", "Стакан, оборот и доступный объём покупки"),
    ("ofz_spread", "4в. Спред к ОФЗ", "Премия доходности к сопоставимой ОФЗ"),
    ("analysis", "5. Первичный анализ", "Рыночная оценка"),
    ("deep_analysis", "6. Глубокий анализ", "Второй слой оценки"),
    ("credit", "7. Кредитный анализ", "Рейтинги и финансовые показатели"),
    ("decision", "8. Финальное решение", "Допуск в портфель и блокеры"),
]

DEPENDENCIES = {
    "cashflow": ["market_search"],
    "news_search": ["market_search"],
    "news": ["market_search", "news_search"],
    "liquidity": ["market_search"],
    "ofz_spread": ["market_search"],
    "analysis": ["market_search", "cashflow", "news", "liquidity", "ofz_spread"],
    "deep_analysis": ["analysis"],
    "credit": ["deep_analysis"],
    "decision": ["credit", "liquidity"],
}

RESULT_FILES = {
    "market_search": "bond_search_*.xlsx",
    "cashflow": "bond_cashflow_*.xlsx",
    "news_search": "news/**/*",
    "news": "bond_news_*.xlsx",
    "liquidity": "bond_purchase_volume_*.xlsx",
    "ofz_spread": "bond_ofz_spread_*.xlsx",
    "analysis": "bond_analysis_*.xlsx",
    "deep_analysis": "bond_deep_analysis_*.xlsx",
    "credit": "bond_credit_analysis_*.xlsx",
    "decision": "bond_decisions_*.xlsx",
}


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def run_dirs() -> list[Path]:
    return sorted(
        [p for p in PROJECT_ROOT.glob("bond_????_??_??") if p.is_dir()],
        key=lambda p: p.name,
        reverse=True,
    )


def latest_file(run_dir: Path, pattern: str) -> Path | None:
    files = [p for p in run_dir.glob(pattern) if p.is_file() and not p.name.startswith("~$")]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def module_state(run_dir: Path, key: str) -> dict[str, Any]:
    pattern = RESULT_FILES[key]
    if "**" in pattern:
        files = [p for p in run_dir.glob(pattern) if p.is_file()]
        path = max(files, key=lambda p: p.stat().st_mtime) if files else None
    else:
        path = latest_file(run_dir, pattern)
    if not path:
        return {"status": "Нет результата", "updated": "—", "file": None}
    return {
        "status": "Готово",
        "updated": datetime.fromtimestamp(path.stat().st_mtime).strftime("%d.%m.%Y %H:%M"),
        "file": path,
    }


def read_excel_safely(path: Path | None, preferred: list[str] | None = None) -> pd.DataFrame:
    if not path:
        return pd.DataFrame()
    try:
        book = pd.ExcelFile(path)
        sheet = next((name for name in (preferred or []) if name in book.sheet_names), book.sheet_names[0])
        return pd.read_excel(path, sheet_name=sheet)
    except Exception as exc:
        st.warning(f"Не удалось прочитать {path.name}: {exc}")
        return pd.DataFrame()


def decisions_table(run_dir: Path) -> pd.DataFrame:
    path = latest_file(run_dir, "bond_decisions_*.xlsx")
    return read_excel_safely(path, ["Решения", "Кандидаты в портфель"])


def trace_table(run_dir: Path) -> pd.DataFrame:
    path = run_dir / "decisions" / "module_results.jsonl"
    if not path.exists():
        return pd.DataFrame()
    rows = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return pd.DataFrame(rows)


def config_editor(config_path: Path) -> dict[str, Any]:
    config = load_json(config_path, {"strategy": "balanced", "modules": {}})
    modules = config.setdefault("modules", {})
    st.subheader("Настройка модулей")
    st.caption("Изменения сохраняются в отдельный GUI-профиль и не портят исходный balanced.json.")
    cols = st.columns(2)
    for index, (key, title, description) in enumerate(MODULES):
        settings = modules.setdefault(key, {})
        with cols[index % 2]:
            enabled = st.toggle(title, value=bool(settings.get("enabled", True)), key=f"enabled_{key}")
            mode = st.selectbox(
                "Режим",
                ["information", "score", "hard_filter", "hard_stop"],
                index=["information", "score", "hard_filter", "hard_stop"].index(settings.get("mode", "information"))
                if settings.get("mode", "information") in ["information", "score", "hard_filter", "hard_stop"] else 0,
                key=f"mode_{key}",
                label_visibility="collapsed",
            )
            st.caption(description)
            settings["enabled"] = enabled
            settings["mode"] = mode
    return config


def save_gui_config(config: dict[str, Any]) -> Path:
    path = PROJECT_ROOT / "configs" / "gui_active.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def execute_modules(run_dir: Path, modules: list[str], config_path: Path, refresh_ratings: bool) -> tuple[int, str]:
    command = [
        sys.executable,
        str(PROJECT_ROOT / "run_pipeline.py"),
        "--run-dir", str(run_dir),
        "--config", str(config_path),
    ]
    for key in modules:
        command += ["--only-module", key]
    if refresh_ratings:
        command.append("--refresh-ratings")

    process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    output = st.empty()
    lines: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        lines.append(line.rstrip())
        output.code("\n".join(lines[-35:]), language="text")
    return process.wait(), "\n".join(lines)


def render_overview(run_dir: Path) -> None:
    states = [{"Модуль": title, **module_state(run_dir, key)} for key, title, _ in MODULES]
    state_df = pd.DataFrame(states).drop(columns=["file"])
    complete = int((state_df["status"] == "Готово").sum())

    decisions = decisions_table(run_dir)
    candidates = 0
    rejected = 0
    if not decisions.empty and "Допущена в портфель" in decisions.columns:
        candidates = int((decisions["Допущена в портфель"].astype(str).str.upper() == "ДА").sum())
        rejected = int((decisions["Допущена в портфель"].astype(str).str.upper() != "ДА").sum())

    a, b, c, d = st.columns(4)
    a.metric("Модулей готово", f"{complete}/{len(MODULES)}")
    b.metric("Бумаг в решениях", len(decisions))
    c.metric("Допущено", candidates)
    d.metric("Не допущено", rejected)
    st.dataframe(state_df, use_container_width=True, hide_index=True)


def render_bonds(run_dir: Path) -> None:
    decisions = decisions_table(run_dir)
    if decisions.empty:
        search = read_excel_safely(latest_file(run_dir, "bond_search_*.xlsx"), ["Результаты поиска"])
        if search.empty:
            st.info("В выбранном анализе ещё нет таблицы облигаций.")
            return
        st.dataframe(search, use_container_width=True, hide_index=True)
        return

    col1, col2, col3 = st.columns(3)
    text = col1.text_input("Поиск по названию или SECID")
    decision_values = sorted(decisions.get("Финальное решение", pd.Series(dtype=str)).dropna().astype(str).unique())
    chosen_decisions = col2.multiselect("Финальное решение", decision_values)
    only_eligible = col3.checkbox("Только допущенные")

    filtered = decisions.copy()
    if text:
        mask = pd.Series(False, index=filtered.index)
        for column in ["Полное наименование", "Код ценной бумаги"]:
            if column in filtered.columns:
                mask |= filtered[column].astype(str).str.contains(text, case=False, na=False)
        filtered = filtered[mask]
    if chosen_decisions and "Финальное решение" in filtered.columns:
        filtered = filtered[filtered["Финальное решение"].astype(str).isin(chosen_decisions)]
    if only_eligible and "Допущена в портфель" in filtered.columns:
        filtered = filtered[filtered["Допущена в портфель"].astype(str).str.upper() == "ДА"]

    st.dataframe(filtered, use_container_width=True, hide_index=True)

    if "Код ценной бумаги" in filtered.columns and not filtered.empty:
        secid = st.selectbox("Разобрать путь облигации", filtered["Код ценной бумаги"].astype(str).tolist())
        trace = trace_table(run_dir)
        if not trace.empty and "secid" in trace.columns:
            detail = trace[trace["secid"].astype(str) == secid]
            columns = [c for c in ["module", "status", "score_delta", "reason", "reason_code", "hard_stop"] if c in detail.columns]
            st.dataframe(detail[columns], use_container_width=True, hide_index=True)
        else:
            st.info("Для этого запуска ещё нет унифицированного журнала решений.")


def render_rerun(run_dir: Path, is_today: bool) -> None:
    if not is_today:
        st.warning("Предыдущие дни доступны только для просмотра. Перезапуск разрешён только в папке текущего дня.")
        return

    st.subheader("Точечный перезапуск")
    st.info("Первый модуль можно не выбирать. Остальные этапы используют уже сохранённый результат поиска текущего дня.")

    labels = {key: title for key, title, _ in MODULES}
    selected = st.multiselect(
        "Какие модули обновить",
        [key for key, _, _ in MODULES],
        format_func=lambda key: labels[key],
        default=[],
    )
    refresh_ratings = st.checkbox("Принудительно обновить рейтинги", value=False)

    if selected:
        missing = []
        for key in selected:
            for dependency in DEPENDENCIES.get(key, []):
                if dependency not in selected and module_state(run_dir, dependency)["file"] is None:
                    missing.append(f"{labels[key]} требует результат: {labels[dependency]}")
        if missing:
            st.error("Не хватает входных данных:\n\n" + "\n\n".join(sorted(set(missing))))

    config = config_editor(DEFAULT_CONFIG)
    if st.button("Сохранить настройки", use_container_width=True):
        path = save_gui_config(config)
        st.success(f"Профиль сохранён: {path.relative_to(PROJECT_ROOT)}")

    disabled_selected = [key for key in selected if not config.get("modules", {}).get(key, {}).get("enabled", True)]
    if disabled_selected:
        st.warning("Выбранные, но отключённые в профиле модули будут пропущены: " + ", ".join(labels[k] for k in disabled_selected))

    can_run = bool(selected) and not any(
        dependency not in selected and module_state(run_dir, dependency)["file"] is None
        for key in selected for dependency in DEPENDENCIES.get(key, [])
    )
    if st.button("Запустить выбранные модули", type="primary", disabled=not can_run, use_container_width=True):
        config_path = save_gui_config(config)
        with st.status("Pipeline выполняется…", expanded=True) as status:
            code, log = execute_modules(run_dir, selected, config_path, refresh_ratings)
            log_path = run_dir / "gui_last_run.log"
            log_path.write_text(log, encoding="utf-8")
            if code == 0:
                status.update(label="Выбранные модули успешно обновлены", state="complete")
                st.success("Готово. Страница перечитает новые отчёты после обновления.")
            else:
                status.update(label=f"Ошибка выполнения, код {code}", state="error")
                st.error(f"Подробный лог сохранён в {log_path.name}")


def main() -> None:
    st.set_page_config(page_title="MOEX Bond Lab", page_icon="📊", layout="wide")
    st.title("📊 MOEX Bond Lab")
    st.caption("История анализов, прозрачность модулей и точечный перезапуск без повторного 40-минутного сканирования.")

    dirs = run_dirs()
    if not dirs:
        st.warning("Папки bond_YYYY_MM_DD пока не найдены. Сначала запустите pipeline хотя бы один раз.")
        return

    names = [p.name for p in dirs]
    default_index = names.index(TODAY_RUN.name) if TODAY_RUN.name in names else 0
    selected_name = st.sidebar.selectbox("Дата анализа", names, index=default_index)
    run_dir = PROJECT_ROOT / selected_name
    is_today = run_dir.name == TODAY_RUN.name
    st.sidebar.write(f"Папка: `{run_dir.name}`")
    st.sidebar.success("Текущий день: можно обновлять модули") if is_today else st.sidebar.info("Архив: только просмотр")

    tab1, tab2, tab3, tab4 = st.tabs(["Обзор", "Облигации", "Модули и причины", "Перезапуск"])
    with tab1:
        render_overview(run_dir)
    with tab2:
        render_bonds(run_dir)
    with tab3:
        trace = trace_table(run_dir)
        if trace.empty:
            st.info("Журнал решений отсутствует. Он появится после запуска pipeline с новой архитектурой.")
        else:
            module_values = sorted(trace.get("module", pd.Series(dtype=str)).dropna().astype(str).unique())
            status_values = sorted(trace.get("status", pd.Series(dtype=str)).dropna().astype(str).unique())
            c1, c2 = st.columns(2)
            selected_modules = c1.multiselect("Модуль", module_values)
            selected_statuses = c2.multiselect("Статус", status_values)
            view = trace.copy()
            if selected_modules:
                view = view[view["module"].astype(str).isin(selected_modules)]
            if selected_statuses:
                view = view[view["status"].astype(str).isin(selected_statuses)]
            st.dataframe(view, use_container_width=True, hide_index=True)
    with tab4:
        render_rerun(run_dir, is_today)


if __name__ == "__main__":
    main()
