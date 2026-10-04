from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app.core.configuration import is_enabled, load_config, module_config
from app.core.pipeline_common import clean_secid_rows, latest, normalize, safe_float
from app.core.stage_registry import BY_SCRIPT, MODULES, ModuleSpec


def decisions_dir(run_dir: Path) -> Path:
    path = run_dir / "decisions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def append_event(run_dir: Path, event: dict[str, Any]) -> None:
    target = decisions_dir(run_dir) / "module_results.jsonl"
    with target.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")


def record_disabled(run_dir: Path, spec: ModuleSpec, config: dict[str, Any]) -> None:
    append_event(run_dir, {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "module": spec.key,
        "status": "DISABLED",
        "passed": None,
        "hard_stop": False,
        "score_delta": 0,
        "reason_code": "MODULE_DISABLED",
        "reason": "Модуль отключён конфигурацией",
        "mode": module_config(config, spec.key).get("mode", "information"),
    })
    write_summaries(run_dir, config)


def _find_secid_column(df: pd.DataFrame) -> str | None:
    for column in ("Код ценной бумаги", "SECID", "secid"):
        if column in df.columns:
            return column
    return None


def _status_for_row(module: str, row: pd.Series) -> tuple[str, bool | None, bool, float, str, str]:
    text = normalize(" ".join(str(v) for v in row.values if not pd.isna(v)))
    score_delta = 0.0
    hard_stop = False
    passed: bool | None = True
    status = "PASS"
    code = "MODULE_PASS"
    reason = "Проверка пройдена"

    if module == "news":
        files = int(safe_float(row.get("Новостных файлов"), 0) or 0)
        critical = normalize(row.get("Критический новостной стоп")) in {"да", "true", "1"}
        if critical:
            return "FAIL", False, True, -100.0, "CRITICAL_NEWS", str(row.get("Негативные события") or "Критическое событие")
        if files == 0:
            return "NO_DATA", None, False, 0.0, "NEWS_NOT_FOUND", "Новостные источники не найдены"
        return status, passed, hard_stop, score_delta, code, str(row.get("Негативные события") or reason)

    if module == "cashflow":
        completeness = normalize(row.get("Полнота cashflow") or row.get("Полнота денежных потоков"))
        if "нет данных" in completeness or "низк" in completeness:
            return "WARNING", None, False, -15.0, "INCOMPLETE_CASHFLOW", completeness or "Неполный денежный поток"

    if module == "liquidity":
        max_amount = safe_float(row.get("Максимум к покупке, руб."), 0) or 0
        offer_value = safe_float(row.get("Объём предложения в стакане, руб."), 0) or 0
        if max_amount <= 0:
            return "FAIL", False, True, -100.0, "NO_PURCHASE_VOLUME", "Нет подтверждённого объёма покупки"
        if offer_value <= 0:
            return "WARNING", True, False, -10.0, "ORDERBOOK_UNKNOWN", "Стакан не получен; лимит основан на обороте"

    if module == "ofz_spread":
        spread_bp = safe_float(row.get("Спред, б.п.") or row.get("Спред к ОФЗ, б.п."))
        if spread_bp is not None and spread_bp >= 1000:
            return "WARNING", True, False, -25.0, "EXTREME_OFZ_SPREAD", f"Спред {spread_bp:.0f} б.п."
        if spread_bp is not None and spread_bp >= 600:
            return "WARNING", True, False, -12.0, "HIGH_OFZ_SPREAD", f"Спред {spread_bp:.0f} б.п."

    if module == "credit":
        missing = normalize(row.get("Недостающие данные"))
        rating = normalize(row.get("Рейтинг"))
        model_key = normalize(row.get("Ключ модели"))
        if not rating:
            return "NO_DATA", None, False, -40.0, "CREDIT_RATING_MISSING", str(row.get("Недостающие данные") or "Нет рейтинга")
        if model_key in {"", "corporate"} and "финансовая отчетность" in missing:
            return "NO_DATA", None, False, -25.0, "CORPORATE_FINANCIALS_MISSING", str(row.get("Недостающие данные") or "Нет корпоративной отчётности")
        if model_key in {"bank", "region", "structured_finance"} and missing not in {"", "—", "-"}:
            return "WARNING", True, False, -8.0, "SECTOR_DATA_PARTIAL", str(row.get("Недостающие данные"))

    if module == "decision":
        decision = normalize(row.get("Финальное решение"))
        if "не покупать" in decision:
            return "FAIL", False, True, 0.0, "FINAL_REJECT", str(row.get("Блокеры") or decision)
        if "недостаточно данных" in decision:
            return "NO_DATA", None, False, 0.0, "FINAL_NO_DATA", str(row.get("Ручные проверки") or decision)
        if "купить" in decision:
            return "PASS", True, False, 0.0, "FINAL_BUY", str(row.get("Причины") or decision)
        return "WARNING", False, False, 0.0, "FINAL_REVIEW", decision or "Требуется проверка"

    if "жесткий стоп" in text or "жёсткий стоп" in text:
        hard_stop = True
    return status, passed, hard_stop, score_delta, code, reason


def collect_stage(run_dir: Path, spec: ModuleSpec, config: dict[str, Any]) -> None:
    if spec.output_pattern is None:
        append_event(run_dir, {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "module": spec.key,
            "status": "PASS",
            "passed": True,
            "hard_stop": False,
            "score_delta": 0,
            "reason_code": "STAGE_COMPLETED",
            "reason": "Этап выполнен",
        })
        write_summaries(run_dir, config)
        return

    source = latest(run_dir, spec.output_pattern, required=False)
    if source is None:
        append_event(run_dir, {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "module": spec.key,
            "status": "ERROR",
            "passed": None,
            "hard_stop": False,
            "score_delta": 0,
            "reason_code": "OUTPUT_NOT_FOUND",
            "reason": f"Не найден результат {spec.output_pattern}",
        })
        write_summaries(run_dir, config)
        return

    try:
        df = pd.read_excel(source, sheet_name=spec.sheet)
    except Exception:
        df = pd.read_excel(source, sheet_name=0)
    secid_column = _find_secid_column(df)
    if secid_column and secid_column != "Код ценной бумаги":
        df = df.rename(columns={secid_column: "Код ценной бумаги"})
    df = clean_secid_rows(df)

    for _, row in df.iterrows():
        status, passed, hard_stop, score_delta, code, reason = _status_for_row(spec.key, row)
        append_event(run_dir, {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "secid": row.get("Код ценной бумаги"),
            "module": spec.key,
            "status": status,
            "passed": passed,
            "hard_stop": hard_stop,
            "score_delta": score_delta,
            "reason_code": code,
            "reason": reason,
            "mode": module_config(config, spec.key).get("mode", "information"),
        })
    write_summaries(run_dir, config)


def write_summaries(run_dir: Path, config: dict[str, Any]) -> None:
    source = decisions_dir(run_dir) / "module_results.jsonl"
    events = []
    if source.exists():
        for line in source.read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    by_security: dict[str, dict[str, Any]] = {}
    module_counts: dict[str, dict[str, int]] = {}
    for event in events:
        module = str(event.get("module") or "unknown")
        status = str(event.get("status") or "UNKNOWN")
        module_counts.setdefault(module, {})[status] = module_counts.setdefault(module, {}).get(status, 0) + 1
        secid = event.get("secid")
        if not secid:
            continue
        item = by_security.setdefault(secid, {
            "secid": secid,
            "passed_modules": [],
            "warning_modules": [],
            "failed_modules": [],
            "no_data_modules": [],
            "disabled_modules": [],
            "score_delta": 0.0,
            "reasons": [],
        })
        item["score_delta"] += float(event.get("score_delta") or 0)
        if status == "PASS": item["passed_modules"].append(module)
        elif status == "WARNING": item["warning_modules"].append(module)
        elif status == "FAIL": item["failed_modules"].append(module)
        elif status == "NO_DATA": item["no_data_modules"].append(module)
        elif status == "DISABLED": item["disabled_modules"].append(module)
        if event.get("reason"):
            item["reasons"].append({"module": module, "status": status, "reason": event["reason"]})

    out = decisions_dir(run_dir)
    (out / "securities_summary.json").write_text(json.dumps(list(by_security.values()), ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "strategy": config.get("strategy"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "modules": module_counts,
        "unique_securities": len(by_security),
    }
    (out / "pipeline_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
