from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from app.gui.selection_profiles_ui import search_criteria_editor as render_search_criteria_editor

from master_dataset import build_master_dataset
from runtime_env import build_subprocess_env
from stage_registry import GUI_MODULES, MODULE_DEPENDENCIES, RESULT_FILES as STAGE_RESULT_FILES

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUNS_ROOT = PROJECT_ROOT / "runs"
DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "balanced.json"
TODAY_RUN = RUNS_ROOT / f"bond_{datetime.now():%Y_%m_%d}"

MODULES = list(GUI_MODULES)
MODULE_KEYS = [item[0] for item in MODULES]
LABELS = {key: title for key, title, _ in MODULES}
DEPENDENCIES = {key: list(value) for key, value in MODULE_DEPENDENCIES.items()}
RESULT_FILES = {key: value for key, value in STAGE_RESULT_FILES.items() if value is not None}

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
    current = [p for p in RUNS_ROOT.glob("bond_????_??_??") if p.is_dir()] if RUNS_ROOT.exists() else []
    legacy = [p for p in PROJECT_ROOT.glob("bond_????_??_??") if p.is_dir()]
    by_name = {p.name: p for p in legacy}
    by_name.update({p.name: p for p in current})  # runs/ имеет приоритет над legacy-корнем
    return sorted(by_name.values(), key=lambda p: p.name, reverse=True)


def resolve_run_dir(name: str) -> Path:
    current = RUNS_ROOT / name
    if current.is_dir():
        return current
    return PROJECT_ROOT / name


def latest_file(run_dir: Path, pattern: str) -> Path | None:
    files = [p for p in run_dir.glob(pattern) if p.is_file() and not p.name.startswith("~$")]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def _latest_module_event(run_dir: Path, key: str) -> dict[str, Any] | None:
    trace = run_dir / "decisions" / "module_results.jsonl"
    if not trace.exists():
        return None
    latest: dict[str, Any] | None = None
    for line in trace.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("module") == key:
            latest = event
    return latest


def module_state(run_dir: Path, key: str) -> dict[str, Any]:
    if not run_dir.exists():
        return {"status": "Нет результата", "updated": "—", "file": None}

    pattern = RESULT_FILES[key]
    files = [p for p in run_dir.glob(pattern) if p.is_file()] if "**" in pattern else []
    path = max(files, key=lambda p: p.stat().st_mtime) if files else latest_file(run_dir, pattern)
    if path is not None:
        return {
            "status": "Готово",
            "updated": datetime.fromtimestamp(path.stat().st_mtime).strftime("%d.%m.%Y %H:%M"),
            "file": path,
        }

    event = _latest_module_event(run_dir, key)
    if not event:
        return {"status": "Нет результата", "updated": "—", "file": None}

    status = str(event.get("status") or "")
    mode = str(event.get("mode") or "information")
    if status == "ERROR" and mode == "information":
        timestamp = str(event.get("timestamp") or "")
        try:
            updated = datetime.fromisoformat(timestamp).strftime("%d.%m.%Y %H:%M")
        except ValueError:
            updated = "—"
        return {
            "status": "Источник недоступен",
            "updated": updated,
            "file": run_dir / "decisions" / "module_results.jsonl",
            "degraded": True,
            "reason": event.get("reason") or "Внешний источник данных недоступен",
        }

    return {"status": "Нет результата", "updated": "—", "file": None}


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
                    render_search_criteria_editor(settings)
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
                if key == "credit":
                    settings["fetch_financials"] = st.toggle(
                        "Автоматически получать финансовые данные из ГИР БО ФНС",
                        value=bool(settings.get("fetch_financials", True)),
                        key="credit_fetch_financials",
                    )
                    if settings["fetch_financials"]:
                        f1, f2 = st.columns(2)
                        settings["financial_cache_days"] = int(f1.number_input(
                            "Кэш финансов, дней", min_value=0, max_value=365,
                            value=int(settings.get("financial_cache_days", 35)), step=1,
                            key="credit_financial_cache_days",
                        ))
                        settings["financial_workers"] = int(f2.slider(
                            "Параллельных запросов ФНС", min_value=1, max_value=4,
                            value=int(settings.get("financial_workers", 1)),
                            key="credit_financial_workers",
                        ))
                        f3, f4 = st.columns(2)
                        settings["financial_delay_seconds"] = float(f3.number_input(
                            "Пауза между запросами ФНС, сек.", min_value=0.0, max_value=10.0,
                            value=float(settings.get("financial_delay_seconds", 1.2)), step=0.2,
                            key="credit_financial_delay_seconds",
                        ))
                        settings["financial_retries"] = int(f4.slider(
                            "Повторов запроса ФНС", min_value=1, max_value=8,
                            value=int(settings.get("financial_retries", 4)),
                            key="credit_financial_retries",
                        ))
                        st.caption(
                            "Источник — публичный ГИР БО ФНС. Для банков и части финансовых организаций "
                            "данные могут отсутствовать; такие позиции остаются с пониженной уверенностью."
                        )
                    settings["fetch_bank_metrics"] = st.toggle(
                        "Получать банковские нормативы из Банка России",
                        value=bool(settings.get("fetch_bank_metrics", True)),
                        key="credit_fetch_bank_metrics",
                    )
                    if settings["fetch_bank_metrics"]:
                        b1, b2 = st.columns(2)
                        settings["bank_cache_days"] = int(b1.number_input(
                            "Кэш банковских нормативов, дней", min_value=0, max_value=365,
                            value=int(settings.get("bank_cache_days", 7)), step=1,
                            key="credit_bank_cache_days",
                        ))
                        settings["bank_delay_seconds"] = float(b2.number_input(
                            "Пауза между запросами ЦБ, сек.", min_value=0.0, max_value=10.0,
                            value=float(settings.get("bank_delay_seconds", 0.4)), step=0.1,
                            key="credit_bank_delay_seconds",
                        ))
                        st.caption(
                            "Используется официальная форма 0409135 Банка России: Н1.0, Н1.1, Н1.2, Н2, Н3 и Н4. "
                            "Корпоративные Debt/EBITDA к банкам не применяются."
                        )
        if st.button("Сохранить профиль модулей", use_container_width=True):
            st.success(f"Сохранено: {save_gui_config(config).relative_to(PROJECT_ROOT)}")
    return config


def execute_modules(run_dir: Path, modules: list[str], config_path: Path, refresh_ratings: bool) -> tuple[int, str]:
    run_dir.mkdir(parents=True, exist_ok=True)
    python_executable = project_python()
    command = [str(python_executable), str(PROJECT_ROOT / "bondlab.py"), "pipeline", "--run-dir", str(run_dir), "--config", str(config_path)]
    for key in modules:
        command += ["--only-module", key]
    if refresh_ratings:
        command.append("--refresh-ratings")
    child_env = build_subprocess_env(PROJECT_ROOT)
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


def _render_copy_log(log: str) -> None:
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


def run_with_ui(run_dir: Path, selected: list[str], config: dict[str, Any], refresh_ratings: bool) -> None:
    config_path = save_gui_config(config)
    with st.status("Pipeline выполняется…", expanded=True) as status:
        code, log = execute_modules(run_dir, selected, config_path, refresh_ratings)
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
    breakdown = deep_get(bond, "decision.score_breakdown")
    points_to_strong = deep_get(bond, "decision.points_to_strong")
    if breakdown:
        st.caption("Расчёт: " + str(breakdown))
    try:
        if points_to_strong is not None and float(points_to_strong) > 0:
            st.caption(f"До сильного порога 86: {float(points_to_strong):.0f} балл.")
    except (TypeError, ValueError):
        pass
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

    negative = deep_get(bond, "decision.negative_factors")
    shortlist_reason = deep_get(bond, "decision.shortlist_reason")
    if negative and str(negative) not in {"—", "Явных отрицательных факторов не зафиксировано"}:
        st.caption("Факторы снижения: " + str(negative))
    if shortlist_reason:
        st.caption("Shortlist: " + str(shortlist_reason))


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
