from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from pipeline_common import latest, safe_float
from portfolio_store import load_portfolio

MOEX = "https://iss.moex.com/iss"


def _run(command: list[str], cwd: Path) -> None:
    print("\n> " + " ".join(command))
    subprocess.run(command, cwd=cwd, check=True)


def _rows(payload: dict[str, Any], block: str) -> list[dict[str, Any]]:
    section = payload.get(block) or {}
    columns = section.get("columns") or []
    return [dict(zip(columns, row)) for row in section.get("data") or []]


def fetch_market(secid: str) -> dict[str, Any]:
    response = requests.get(
        f"{MOEX}/engines/stock/markets/bonds/securities/{secid}.json",
        params={
            "iss.meta": "off",
            "iss.only": "securities,marketdata",
            "securities.columns": "SECID,SHORTNAME,SECNAME,FACEVALUE,MATDATE",
            "marketdata.columns": "SECID,LAST,MARKETPRICE,LCURRENTPRICE,BID,OFFER,YIELD,YIELDATWAP,YIELDCLOSE,DURATION,UPDATETIME",
        },
        timeout=25,
    )
    response.raise_for_status()
    payload = response.json()
    securities = _rows(payload, "securities")
    marketdata = _rows(payload, "marketdata")
    sec = next((row for row in securities if str(row.get("SECID")) == secid), securities[0] if securities else {})
    md = next((row for row in marketdata if str(row.get("SECID")) == secid), marketdata[0] if marketdata else {})
    price = safe_float(md.get("BID") or md.get("LAST") or md.get("MARKETPRICE") or md.get("LCURRENTPRICE"))
    ytm = safe_float(md.get("YIELD") or md.get("YIELDATWAP") or md.get("YIELDCLOSE"))
    duration_days = safe_float(md.get("DURATION"))
    return {
        "Код ценной бумаги": secid,
        "Краткое наименование": sec.get("SHORTNAME") or secid,
        "Полное наименование": sec.get("SECNAME") or sec.get("SHORTNAME") or secid,
        "Цена, %": price,
        "Доходность": ytm,
        "Дюрация, дней": duration_days,
        "Дюрация, месяцев": duration_days / 30.4375 if duration_days else None,
        "Номинал": safe_float(sec.get("FACEVALUE")),
        "Дата погашения": sec.get("MATDATE") or "",
        "Время рынка": md.get("UPDATETIME") or "",
    }


def build_portfolio_input(portfolio: dict[str, Any], output: Path) -> Path:
    rows: list[dict[str, Any]] = []
    for position in portfolio.get("positions", []):
        secid = str(position.get("secid") or "").strip().upper()
        if not secid:
            continue
        try:
            row = fetch_market(secid)
        except Exception as exc:
            row = {
                "Код ценной бумаги": secid,
                "Краткое наименование": position.get("name") or secid,
                "Полное наименование": position.get("name") or secid,
                "Ошибка рынка": str(exc),
            }
        rows.append(row)
    if not rows:
        raise ValueError("В портфеле нет позиций")
    output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_excel(output, sheet_name="Результаты поиска", index=False)
    return output


def _append_text(value: Any, extra: str) -> str:
    base = str(value or "").strip()
    if not base or base.lower() == "nan":
        return extra
    return base if extra in base else f"{base}; {extra}"


def overlay_fresh_news(run_dir: Path, news_path: Path) -> Path | None:
    decisions_path = latest(run_dir, "bond_decisions_*.xlsx", required=False)
    if decisions_path is None or not news_path.exists():
        return None
    decisions = pd.read_excel(decisions_path, sheet_name="Решения")
    news = pd.read_excel(news_path, sheet_name="Новости")
    if "Код ценной бумаги" not in decisions.columns or "Код ценной бумаги" not in news.columns:
        return None
    news_by = {str(row.get("Код ценной бумаги") or "").strip(): row for _, row in news.iterrows()}
    for idx, row in decisions.iterrows():
        secid = str(row.get("Код ценной бумаги") or "").strip()
        fresh = news_by.get(secid)
        if fresh is None:
            continue
        negative = str(fresh.get("Негативные события") or "").strip()
        critical = str(fresh.get("Критический новостной стоп") or "").strip().upper() == "ДА"
        if critical:
            decisions.at[idx, "Финальное решение"] = "Не покупать"
            decisions.at[idx, "Жёсткий стоп"] = "ДА"
            decisions.at[idx, "Блокеры"] = _append_text(row.get("Блокеры"), f"Свежий новостной стоп: {negative}")
        elif negative and negative not in {"—", "nan"}:
            current = str(row.get("Финальное решение") or "").strip()
            if current not in {"Не покупать"}:
                decisions.at[idx, "Финальное решение"] = "Требуется ручная проверка"
            decisions.at[idx, "Блокеры"] = _append_text(row.get("Блокеры"), f"Свежий негатив: {negative}")
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    output = run_dir / f"bond_decisions_daily_{stamp}.xlsx"
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        decisions.to_excel(writer, sheet_name="Решения", index=False)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Лёгкое ежедневное обновление только бумаг из портфеля")
    parser.add_argument("--name", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--portfolio-dir", default="data/virtual_portfolios")
    parser.add_argument("--config", default="configs/gui_active.json")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    run_dir = Path(args.run_dir).expanduser().resolve()
    portfolio_dir = Path(args.portfolio_dir).expanduser().resolve()
    config_path = Path(args.config).expanduser().resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    portfolio = load_portfolio(portfolio_dir, args.name)

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    portfolio_input = run_dir / f"bond_search_portfolio_{stamp}.xlsx"
    build_portfolio_input(portfolio, portfolio_input)

    providers = "google,moex,acra,expert_ra"
    use_proxy = False
    proxy_env = "NEWS_PROXY"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            news_cfg = ((config.get("modules") or {}).get("news_search") or {})
            configured = news_cfg.get("providers") or []
            if configured:
                providers = ",".join(str(x) for x in configured)
            use_proxy = bool(news_cfg.get("proxy_enabled"))
            proxy_env = str(news_cfg.get("proxy_env") or proxy_env)
        except (OSError, json.JSONDecodeError):
            pass

    news_search_cmd = [
        sys.executable, str(root / "3a_bonds_news_search.py"),
        "--input", str(portfolio_input),
        "--providers", providers,
        "--proxy-env", proxy_env,
        "--delay", "0.25",
    ]
    if use_proxy:
        news_search_cmd.append("--use-proxy")
    _run(news_search_cmd, run_dir)

    news_output = run_dir / f"bond_news_daily_{stamp}.xlsx"
    _run([
        sys.executable, str(root / "3b_bonds_news.py"),
        "--input", str(portfolio_input),
        "--news-dir", str(run_dir),
        "--output", str(news_output),
    ], run_dir)

    spread_output = run_dir / f"bond_ofz_spread_daily_{stamp}.xlsx"
    try:
        _run([
            sys.executable, str(root / "4c_bonds_ofz_spread.py"),
            "--input", str(portfolio_input),
            "--output", str(spread_output),
        ], run_dir)
    except subprocess.CalledProcessError as exc:
        print(f"⚠️ Не удалось обновить спред к ОФЗ: {exc}. Мониторинг продолжится с последними доступными данными.")

    overlaid = overlay_fresh_news(run_dir, news_output)
    print("\nЕжедневное обновление портфеля завершено")
    print(f"Портфель: {args.name}")
    print(f"Вход: {portfolio_input}")
    print(f"Новости: {news_output}")
    print(f"Спреды: {spread_output if spread_output.exists() else 'не обновлены'}")
    print(f"Решения с учётом свежих новостей: {overlaid or 'не созданы'}")


if __name__ == "__main__":
    main()
