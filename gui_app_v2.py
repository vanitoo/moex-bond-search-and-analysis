from __future__ import annotations

import json
import os
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
    ("market_search", "1. Поиск облигаций", "Выберите V1 или экспериментальный V2"),
    ("cashflow", "2. Денежные потоки", "Купоны, оферты и погашения"),
    ("news_search", "3а. Поиск новостей", "Скачивание и обновление новостей"),
    ("news", "3б. Анализ новостей", "Риски и стоп-факторы"),
    ("liquidity", "4б. Ликвидность", "Стакан, оборот и доступный объём"),
    ("ofz_spread", "4в. Спред к ОФЗ", "Премия к сопоставимой ОФЗ"),
    ("analysis", "5. Первичный анализ", "Рыночная оценка"),
    ("deep_analysis", "6. Глубокий анализ", "Второй слой оценки"),
    ("credit", "7. Кредитный анализ", "Рейтинги и финансовые показатели"),
    ("decision", "8. Финальное решение", "Работает при любом наборе включённых модулей"),
]
MODULE_KEYS = [item[0] for item in MODULES]
LABELS = {key: title for key, title, _ in MODULES}
DEPENDENCIES = {
    "cashflow": ["market_search"], "news_search": ["market_search"],
    "news": ["market_search", "news_search"], "liquidity": ["market_search"],
    "ofz_spread": ["market_search"], "analysis": ["market_search", "cashflow", "news", "liquidity", "ofz_spread"],
    "deep_analysis": ["analysis"], "credit": ["deep_analysis"], "decision": [],
}
RESULT_FILES = {
    "market_search": "bond_search_*.xlsx", "cashflow": "bond_cashflow_*.xlsx", "news_search": "news/**/*",
    "news": "bond_news_*.xlsx", "liquidity": "bond_purchase_volume_*.xlsx", "ofz_spread": "bond_ofz_spread_*.xlsx",
    "analysis": "bond_analysis_*.xlsx", "deep_analysis": "bond_deep_analysis_*.xlsx",
    "credit": "bond_credit_analysis_*.xlsx", "decision": "bond_decisions_*.xlsx",
}


def project_python() -> Path:
    """Возвращает Python проекта, предпочитая локальное виртуальное окружение."""
    candidates = [
        PROJECT_ROOT / ".venv" / "Scripts" / "python.exe",
        PROJECT_ROOT / "venv" / "Scripts" / "python.exe",
        PROJECT_ROOT / "env" / "Scripts" / "python.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return Path(sys.executable)


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def run_dirs() -> list[Path]:
    return sorted([p for p in PROJECT_ROOT.glob("bond_????_??_??") if p.is_dir()], key=lambda p: p.name, reverse=True)


def latest_file(run_dir: Path, pattern: str) -> Path | None:
    files = [p for p in run_dir.glob(pattern) if p.is_file() and not p.name.startswith("~$")]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def module_state(run_dir: Path, key: str) -> dict[str, Any]:
    if not run_dir.exists():
        return {"status": "Нет результата", "updated": "—", "file": None}
    pattern = RESULT_FILES[key]
    files = [p for p in run_dir.glob(pattern) if p.is_file()] if "**" in pattern else []
    path = max(files, key=lambda p: p.stat().st_mtime) if files else latest_file(run_dir, pattern)
    if path is None:
        return {"status": "Нет результата", "updated": "—", "file": None}
    return {"status": "Готово", "updated": datetime.fromtimestamp(path.stat().st_mtime).strftime("%d.%m.%Y %H:%M"), "file": path}


def save_gui_config(config: dict[str, Any]) -> Path:
    path = PROJECT_ROOT / "configs" / "gui_active.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def config_editor() -> dict[str, Any]:
    active = PROJECT_ROOT / "configs" / "gui_active.json"
    source = active if active.exists() else DEFAULT_CONFIG
    config = load_json(source, {"strategy": "balanced", "modules": {}})
    modules = config.setdefault("modules", {})
    with st.expander("Настройка модулей", expanded=False):
        cols = st.columns(2)
        for index, (key, title, description) in enumerate(MODULES):
            settings = modules.setdefault(key, {})
            with cols[index % 2]:
                settings["enabled"] = st.toggle(title, value=bool(settings.get("enabled", True)), key=f"enabled_{key}")
                st.caption(description)
                if key == "market_search":
                    current = str(settings.get("version", "v1")).lower()
                    scanner_label = st.radio(
                        "Версия сканера",
                        ["V1 — старый контрольный", "V2 — пакетный экспериментальный"],
                        index=1 if current == "v2" else 0,
                        horizontal=False,
                        key="market_scanner_version",
                    )
                    settings["version"] = "v2" if scanner_label.startswith("V2") else "v1"
                    if settings["version"] == "v2":
                        settings["workers"] = st.slider(
                            "Параллельных запросов V2",
                            min_value=1,
                            max_value=8,
                            value=int(settings.get("workers", 5)),
                            key="market_v2_workers",
                        )
                        settings["cache_hours"] = st.number_input(
                            "Срок кэша V2, часов",
                            min_value=0.0,
                            max_value=168.0,
                            value=float(settings.get("cache_hours", 12)),
                            step=1.0,
                            key="market_v2_cache_hours",
                        )
                        st.warning("V2 экспериментальный. Для честного сравнения запускайте V1 и V2 в разные папки или очищайте результат этапа 1.")
        if st.button("Сохранить профиль модулей", use_container_width=True):
            st.success(f"Сохранено: {save_gui_config(config).relative_to(PROJECT_ROOT)}")
    return config


def execute_modules(run_dir: Path, modules: list[str], config_path: Path, refresh_ratings: bool) -> tuple[int, str]:
    run_dir.mkdir(parents=True, exist_ok=True)
    python_executable = project_python()
    command = [str(python_executable), str(PROJECT_ROOT / "run_pipeline.py"), "--run-dir", str(run_dir), "--config", str(config_path)]
    for key in modules:
        command += ["--only-module", key]
    if refresh_ratings:
        command.append("--refresh-ratings")

    child_env = os.environ.copy()
    child_env["PYTHONUTF8"] = "1"
    child_env["PYTHONIOENCODING"] = "utf-8"
    child_env["PYTHONUNBUFFERED"] = "1"

    process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        env=child_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    placeholder = st.empty()
    lines: list[str] = []
    assert process.stdout is not None
    lines.append(f"Python pipeline: {python_executable}")
    placeholder.code("\n".join(lines), language="text")
    for line in process.stdout:
        lines.append(line.rstrip())
        placeholder.code("\n".join(lines[-40:]), language="text")
    return process.wait(), "\n".join(lines)


def run_with_ui(run_dir: Path, selected: list[str], config: dict[str, Any], refresh_ratings: bool) -> None:
    config_path = save_gui_config(config)
    with st.status("Pipeline выполняется…", expanded=True) as status:
        code, log = execute_modules(run_dir, selected, config_path, refresh_ratings)
        log_path = run_dir / "gui_last_run.log"
        log_path.write_text(log, encoding="utf-8")
        if code == 0:
            status.update(label="Анализ успешно завершён", state="complete")
            st.success("Готово. Обновите страницу.")
            if st.button("Обновить страницу", type="primary"):
                st.rerun()
        else:
            status.update(label=f"Ошибка выполнения, код {code}", state="error")
            st.error(f"Лог сохранён: {log_path}")


def render_start_today(config: dict[str, Any]) -> None:
    st.subheader("Анализ на сегодня ещё не запускался")
    st.info("Создам папку сегодняшнего дня и запущу включённые модули. Финальное решение можно оставить включённым при любой конфигурации.")
    st.caption(f"Pipeline будет запущен через: {project_python()}")
    scanner = config.get("modules", {}).get("market_search", {}).get("version", "v1").upper()
    st.info(f"Для первого этапа выбран сканер: {scanner}")
    enabled = [key for key in MODULE_KEYS if config.get("modules", {}).get(key, {}).get("enabled", True)]
    st.write("Будут запущены модули:")
    st.write(" → ".join(LABELS[key] for key in enabled))
    refresh = st.checkbox("Принудительно обновить рейтинги", value=False, key="start_refresh")
    confirm = st.checkbox("Запустить анализ с выбранной конфигурацией", key="start_confirm")
    if st.button("▶ Запустить анализ на сегодня", type="primary", use_container_width=True, disabled=not confirm):
        run_with_ui(TODAY_RUN, enabled, config, refresh)


def read_excel_safely(path: Path | None, preferred: list[str] | None = None) -> pd.DataFrame:
    if path is None:
        return pd.DataFrame()
    try:
        book = pd.ExcelFile(path)
        sheet = next((x for x in (preferred or []) if x in book.sheet_names), book.sheet_names[0])
        return pd.read_excel(path, sheet_name=sheet)
    except Exception as exc:
        st.warning(f"Не удалось прочитать {path.name}: {exc}")
        return pd.DataFrame()


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


def render_overview(run_dir: Path) -> None:
    states = [{"Модуль": title, **module_state(run_dir, key)} for key, title, _ in MODULES]
    frame = pd.DataFrame(states).drop(columns=["file"])
    complete = int((frame["status"] == "Готово").sum())
    decisions = read_excel_safely(latest_file(run_dir, "bond_decisions_*.xlsx"), ["Решения"])
    candidates = int((decisions.get("Допущена в портфель", pd.Series(dtype=str)).astype(str).str.upper() == "ДА").sum()) if not decisions.empty else 0
    a, b, c = st.columns(3)
    a.metric("Модулей готово", f"{complete}/{len(MODULES)}")
    b.metric("Бумаг в решениях", len(decisions))
    c.metric("Допущено", candidates)
    st.dataframe(frame, use_container_width=True, hide_index=True)


def render_bonds(run_dir: Path) -> None:
    decisions = read_excel_safely(latest_file(run_dir, "bond_decisions_*.xlsx"), ["Решения"])
    data = decisions if not decisions.empty else read_excel_safely(latest_file(run_dir, "bond_search_*.xlsx"), ["Результаты поиска"])
    if data.empty:
        st.info("Таблица облигаций ещё не сформирована.")
        return
    query = st.text_input("Поиск по названию или SECID")
    view = data.copy()
    if query:
        mask = pd.Series(False, index=view.index)
        for column in ["Полное наименование", "Код ценной бумаги"]:
            if column in view.columns:
                mask |= view[column].astype(str).str.contains(query, case=False, na=False)
        view = view[mask]
    st.dataframe(view, use_container_width=True, hide_index=True)


def render_rerun(run_dir: Path, config: dict[str, Any]) -> None:
    st.subheader("Обновить только часть анализа")
    st.info("Финальное решение можно пересчитать отдельно. Оно использует только включённые модули и доступные результаты.")
    st.caption(f"Pipeline будет запущен через: {project_python()}")
    scanner = config.get("modules", {}).get("market_search", {}).get("version", "v1").upper()
    st.caption(f"Выбранный сканер первого этапа: {scanner}")
    selected = st.multiselect("Какие модули обновить", MODULE_KEYS, format_func=lambda key: LABELS[key], default=[])
    refresh = st.checkbox("Принудительно обновить рейтинги", value=False, key="rerun_refresh")
    enabled = {key for key in MODULE_KEYS if config.get("modules", {}).get(key, {}).get("enabled", True)}
    missing: list[str] = []
    for key in selected:
        for dep in DEPENDENCIES.get(key, []):
            if dep not in enabled:
                continue
            if dep not in selected and module_state(run_dir, dep)["file"] is None:
                missing.append(f"{LABELS[key]} требует включённый модуль: {LABELS[dep]}")
    if missing:
        st.error("Не хватает входных данных:\n\n" + "\n\n".join(sorted(set(missing))))
    if st.button("▶ Запустить выбранные модули", type="primary", disabled=not bool(selected) or bool(missing), use_container_width=True):
        run_with_ui(run_dir, selected, config, refresh)


def main() -> None:
    st.set_page_config(page_title="MOEX Bond Lab", page_icon="📊", layout="wide")
    st.title("📊 MOEX Bond Lab")
    st.caption("Финальное решение при любом наборе включённых модулей.")
    config = config_editor()
    dirs = run_dirs()
    choices = ["➕ Новый анализ на сегодня"] + [path.name for path in dirs]
    default = choices.index(TODAY_RUN.name) if TODAY_RUN.name in choices else 0
    selected = st.sidebar.selectbox("Анализ", choices, index=default)
    if selected == "➕ Новый анализ на сегодня":
        render_start_today(config)
        return
    run_dir = PROJECT_ROOT / selected
    is_today = run_dir.name == TODAY_RUN.name
    st.sidebar.success("Текущий день: модули можно обновлять") if is_today else st.sidebar.info("Архив: только просмотр")
    tabs = st.tabs(["Обзор", "Облигации", "Модули и причины", "Запуск / обновление"])
    with tabs[0]:
        render_overview(run_dir)
    with tabs[1]:
        render_bonds(run_dir)
    with tabs[2]:
        trace = trace_table(run_dir)
        st.dataframe(trace, use_container_width=True, hide_index=True) if not trace.empty else st.info("Журнал пока отсутствует")
    with tabs[3]:
        render_rerun(run_dir, config) if is_today else st.info("Архив доступен только для просмотра")


if __name__ == "__main__":
    main()
