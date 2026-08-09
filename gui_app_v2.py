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

from master_dataset import build_master_dataset

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "balanced.json"
TODAY_RUN = PROJECT_ROOT / f"bond_{datetime.now():%Y_%m_%d}"

MODULES = [
    ("market_search", "1. Поиск облигаций", "Общие критерии для V1 и V2; выбирается только способ сканирования"),
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

COMPARE_METRICS = {
    "Доходность, %": "market.yield",
    "Цена, %": "market.price",
    "Дюрация, мес.": "market.duration_months",
    "Объём за 15 дней, шт.": "market.volume_15d",
    "Мин. дневной объём, шт.": "market.min_daily_volume",
    "Bid": "liquidity.bid",
    "Offer": "liquidity.offer",
    "Bid/Ask спред, %": "liquidity.spread_percent",
    "Максимум к покупке, руб.": "liquidity.max_purchase_rub",
    "Спред к ОФЗ, б.п.": "ofz_spread.spread_bp",
    "Доходность ОФЗ, %": "ofz_spread.ofz_yield",
    "Первичный балл": "analysis.score",
    "Глубокий балл": "deep_analysis.score",
    "Кредитный балл": "credit.score",
    "Финальный балл": "decision.score",
}
DEFAULT_COMPARE_METRICS = ["Доходность, %", "Цена, %", "Дюрация, мес.", "Спред к ОФЗ, б.п.", "Финальный балл"]


def project_python() -> Path:
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


def search_criteria_editor(settings: dict[str, Any]) -> None:
    st.markdown("**Общие критерии поиска для V1 и V2**")
    left, right = st.columns(2)
    with left:
        settings["yield_more"] = st.number_input("Доходность ОТ, %", value=float(settings.get("yield_more", 15)), step=1.0)
        settings["price_more"] = st.number_input("Цена ОТ, % от номинала", value=float(settings.get("price_more", 70)), step=1.0)
        settings["duration_more"] = st.number_input("Дюрация ОТ, месяцев", value=float(settings.get("duration_more", 3)), step=1.0)
        settings["volume_more"] = st.number_input("Минимальный объём каждого из 15 дней, шт.", min_value=0.0, value=float(settings.get("volume_more", 2000)), step=100.0)
    with right:
        settings["yield_less"] = st.number_input("Доходность ДО, %", value=float(settings.get("yield_less", 40)), step=1.0)
        settings["price_less"] = st.number_input("Цена ДО, % от номинала", value=float(settings.get("price_less", 120)), step=1.0)
        settings["duration_less"] = st.number_input("Дюрация ДО, месяцев", value=float(settings.get("duration_less", 18)), step=1.0)
        settings["bond_volume_more"] = st.number_input("Совокупный объём за 15 дней, шт.", min_value=0.0, value=float(settings.get("bond_volume_more", 60000)), step=1000.0)
    settings["require_known_coupons"] = st.checkbox(
        "Только облигации с известными купонами до погашения",
        value=bool(settings.get("require_known_coupons", True)),
    )
    errors = []
    if settings["yield_more"] > settings["yield_less"]:
        errors.append("Доходность ОТ больше доходности ДО")
    if settings["price_more"] > settings["price_less"]:
        errors.append("Цена ОТ больше цены ДО")
    if settings["duration_more"] > settings["duration_less"]:
        errors.append("Дюрация ОТ больше дюрации ДО")
    if errors:
        st.error("; ".join(errors))


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
                    search_criteria_editor(settings)
                    current = str(settings.get("version", "v1")).lower()
                    scanner_label = st.radio(
                        "Версия сканера",
                        ["V1 — старый контрольный", "V2 — пакетный экспериментальный"],
                        index=1 if current == "v2" else 0,
                        key="market_scanner_version",
                    )
                    settings["version"] = "v2" if scanner_label.startswith("V2") else "v1"
                    if settings["version"] == "v2":
                        settings["workers"] = st.slider(
                            "Параллельных запросов V2", min_value=1, max_value=8,
                            value=int(settings.get("workers", 5)), key="market_v2_workers",
                        )
                        settings["cache_hours"] = st.number_input(
                            "Срок кэша V2, часов", min_value=0.0, max_value=168.0,
                            value=float(settings.get("cache_hours", 12)), step=1.0, key="market_v2_cache_hours",
                        )
                        st.warning("V2 экспериментальный. V1 и V2 получают абсолютно одинаковые критерии поиска.")
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
        command, cwd=PROJECT_ROOT, env=child_env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    placeholder = st.empty()
    lines: list[str] = [f"Python pipeline: {python_executable}"]
    assert process.stdout is not None
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
            st.success("Готово. Единый bonds_master.json также обновлён.")
            if st.button("Обновить страницу", type="primary"):
                st.rerun()
        else:
            status.update(label=f"Ошибка выполнения, код {code}", state="error")
            st.error(f"Лог сохранён: {log_path}")


def render_start_today(config: dict[str, Any]) -> None:
    st.subheader("Анализ на сегодня ещё не запускался")
    st.info("Создам папку сегодняшнего дня и запущу включённые модули.")
    st.caption(f"Pipeline будет запущен через: {project_python()}")
    settings = config.get("modules", {}).get("market_search", {})
    scanner = settings.get("version", "v1").upper()
    st.info(
        f"Первый этап: {scanner}; доходность {settings.get('yield_more', 15)}–{settings.get('yield_less', 40)}%; "
        f"цена {settings.get('price_more', 70)}–{settings.get('price_less', 120)}%; "
        f"дюрация {settings.get('duration_more', 3)}–{settings.get('duration_less', 18)} мес."
    )
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


def master_is_stale(run_dir: Path, master: Path) -> bool:
    if not master.exists():
        return True
    source_patterns = [value for key, value in RESULT_FILES.items() if key != "news_search"]
    source_files = []
    for pattern in source_patterns:
        source_files.extend([p for p in run_dir.glob(pattern) if p.is_file()])
    return any(path.stat().st_mtime > master.stat().st_mtime for path in source_files)


def load_master(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "decisions" / "bonds_master.json"
    try:
        if master_is_stale(run_dir, path):
            build_master_dataset(run_dir, path)
        return load_json(path, {"bonds": []})
    except Exception as exc:
        st.warning(f"Не удалось собрать единый набор данных: {exc}")
        return {"bonds": []}


def render_overview(run_dir: Path) -> None:
    states = [{"Модуль": title, **module_state(run_dir, key)} for key, title, _ in MODULES]
    frame = pd.DataFrame(states).drop(columns=["file"])
    complete = int((frame["status"] == "Готово").sum())
    master = load_master(run_dir)
    bonds = master.get("bonds", [])
    admitted = sum(1 for bond in bonds if bond.get("decision", {}).get("admitted") is True)
    a, b, c = st.columns(3)
    a.metric("Модулей готово", f"{complete}/{len(MODULES)}")
    b.metric("Бумаг в master", len(bonds))
    c.metric("Допущено", admitted)
    st.dataframe(frame, use_container_width=True, hide_index=True)
    if master.get("generated_at"):
        st.caption(f"Единый набор GUI обновлён: {master['generated_at']}")


def render_bonds(run_dir: Path) -> None:
    master = load_master(run_dir)
    bonds = master.get("bonds", [])
    if not bonds:
        st.info("Таблица облигаций ещё не сформирована.")
        return
    rows = []
    for bond in bonds:
        rows.append({
            "SECID": bond.get("secid"),
            "Название": bond.get("name"),
            "Доходность, %": bond.get("market", {}).get("yield"),
            "Цена, %": bond.get("market", {}).get("price"),
            "Дюрация, мес.": bond.get("market", {}).get("duration_months"),
            "Спред к ОФЗ, б.п.": bond.get("ofz_spread", {}).get("spread_bp"),
            "Рейтинг": bond.get("credit", {}).get("rating"),
            "Финальный балл": bond.get("decision", {}).get("score"),
            "Решение": bond.get("decision", {}).get("status"),
        })
    data = pd.DataFrame(rows)
    query = st.text_input("Поиск по названию или SECID")
    if query:
        data = data[data["SECID"].astype(str).str.contains(query, case=False, na=False) | data["Название"].astype(str).str.contains(query, case=False, na=False)]
    st.dataframe(data, use_container_width=True, hide_index=True)


def deep_get(item: dict[str, Any], dotted_path: str) -> Any:
    value: Any = item
    for part in dotted_path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def candidate_file(run_dir: Path) -> Path:
    return run_dir / "decisions" / "candidates.json"


def saved_candidates(run_dir: Path) -> list[str]:
    payload = load_json(candidate_file(run_dir), {"secids": []})
    return [str(value) for value in payload.get("secids", [])]


def save_candidates(run_dir: Path, secids: list[str]) -> None:
    path = candidate_file(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"updated_at": datetime.now().isoformat(timespec="seconds"), "secids": secids}, ensure_ascii=False, indent=2), encoding="utf-8")


def bond_label(bond: dict[str, Any]) -> str:
    name = str(bond.get("name") or "Без названия")
    return f"{name} · {bond.get('secid')}"


def score_for_leader(bond: dict[str, Any]) -> float | None:
    for path in ("decision.score", "deep_analysis.score", "analysis.score"):
        value = deep_get(bond, path)
        try:
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            pass
    return None


def render_bond_explanation(bond: dict[str, Any]) -> None:
    score = score_for_leader(bond)
    decision = bond.get("decision", {}).get("status") or "Решение не сформировано"
    title = bond_label(bond)
    st.markdown(f"**{title}**")
    st.write(f"Решение: **{decision}**" + (f" · балл **{score:.0f}**" if score is not None else ""))
    events = bond.get("modules", {})
    risks = []
    good = []
    for module, event in events.items():
        status = str(event.get("status") or "")
        reason = str(event.get("reason") or "")
        if status in {"FAIL", "WARNING", "NO_DATA", "ERROR"}:
            risks.append(f"{LABELS.get(module, module)}: {reason}")
        elif status == "PASS" and reason and reason != "Проверка пройдена":
            good.append(f"{LABELS.get(module, module)}: {reason}")
    if good:
        st.success("Сильные стороны: " + " | ".join(good[:3]))
    if risks:
        st.warning("Что проверить: " + " | ".join(risks[:4]))
    elif events:
        st.success("По журналу включённых модулей предупреждений нет.")


def render_candidates(run_dir: Path) -> None:
    st.subheader("Кандидаты к покупке")
    st.caption("Соберите собственный короткий список и сравнивайте бумаги на одном экране. Данные берутся из bonds_master.json, а не напрямую из Excel.")
    master = load_master(run_dir)
    bonds = master.get("bonds", [])
    if not bonds:
        st.info("Нет данных для сравнения. Сначала выполните хотя бы поиск облигаций.")
        return

    by_secid = {str(bond.get("secid")): bond for bond in bonds}
    options = list(by_secid)
    defaults = [secid for secid in saved_candidates(run_dir) if secid in by_secid]
    selected = st.multiselect(
        "Выберите 2–10 облигаций",
        options,
        default=defaults,
        max_selections=10,
        format_func=lambda secid: bond_label(by_secid[secid]),
    )
    if st.button("Сохранить список кандидатов"):
        save_candidates(run_dir, selected)
        st.success("Список сохранён для этого дня анализа.")

    if len(selected) < 2:
        st.info("Выберите минимум две облигации для сравнения.")
        return

    chosen = [by_secid[secid] for secid in selected]
    available_metrics = [
        name for name, path in COMPARE_METRICS.items()
        if any(deep_get(bond, path) is not None for bond in chosen)
    ]
    default_metrics = [name for name in DEFAULT_COMPARE_METRICS if name in available_metrics]
    metrics = st.multiselect("Параметры сравнения", available_metrics, default=default_metrics or available_metrics[:5])

    compare_rows = []
    labels = {bond["secid"]: (bond.get("name") or bond["secid"]) for bond in chosen}
    for metric in metrics:
        row = {"Параметр": metric}
        path = COMPARE_METRICS[metric]
        for bond in chosen:
            row[labels[bond["secid"]]] = deep_get(bond, path)
        compare_rows.append(row)
    st.dataframe(pd.DataFrame(compare_rows), use_container_width=True, hide_index=True)

    scored = [(bond, score_for_leader(bond)) for bond in chosen]
    scored = [(bond, score) for bond, score in scored if score is not None]
    if scored:
        leader, leader_score = max(scored, key=lambda pair: pair[1])
        st.info(f"По текущему итоговому/глубокому скорингу лидирует **{bond_label(leader)}** — {leader_score:.0f} баллов. Это не отдельная рекомендация: результат зависит от включённых модулей.")

    chart_metrics = st.multiselect("Графики", metrics, default=metrics[: min(3, len(metrics))], key="candidate_charts")
    for metric in chart_metrics:
        values = []
        for bond in chosen:
            value = deep_get(bond, COMPARE_METRICS[metric])
            try:
                numeric = float(value) if value is not None else None
            except (TypeError, ValueError):
                numeric = None
            if numeric is not None:
                values.append({"Облигация": labels[bond["secid"]], metric: numeric})
        if values:
            st.markdown(f"**{metric}**")
            st.bar_chart(pd.DataFrame(values).set_index("Облигация"))

    st.markdown("### Почему такие оценки")
    for bond in chosen:
        with st.container(border=True):
            render_bond_explanation(bond)


def render_rerun(run_dir: Path, config: dict[str, Any]) -> None:
    st.subheader("Обновить только часть анализа")
    st.info("Финальное решение можно пересчитать отдельно. После запуска bonds_master.json перестроится автоматически.")
    st.caption(f"Pipeline будет запущен через: {project_python()}")
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
    st.caption("Сканер → анализ → сравнение кандидатов → финальное решение.")
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
    tabs = st.tabs(["Обзор", "Облигации", "Кандидаты", "Модули и причины", "Запуск / обновление"])
    with tabs[0]:
        render_overview(run_dir)
    with tabs[1]:
        render_bonds(run_dir)
    with tabs[2]:
        render_candidates(run_dir)
    with tabs[3]:
        trace = trace_table(run_dir)
        st.dataframe(trace, use_container_width=True, hide_index=True) if not trace.empty else st.info("Журнал пока отсутствует")
    with tabs[4]:
        render_rerun(run_dir, config) if is_today else st.info("Архив доступен только для просмотра")


if __name__ == "__main__":
    main()
