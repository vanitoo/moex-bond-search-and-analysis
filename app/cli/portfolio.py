from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from app.core.process_runner import entrypoint_command, run_command
from app.core.project_paths import GUI_CONFIG, PROJECT_ROOT, RUNS_ROOT, VIRTUAL_PORTFOLIOS_ROOT
from app.core.run_paths import iter_analysis_dirs, latest_analysis_run
from app.portfolio.portfolio_allocator import allocate_budget
from app.portfolio.portfolio_ledger import append_transaction, cash_balance, read_ledger
from app.portfolio.portfolio_plan import apply_allocation_plan
from app.portfolio.portfolio_store import create_portfolio, load_portfolio, remove_position, save_portfolio, upsert_position

LEDGER_ROOT = PROJECT_ROOT / "data" / "portfolio_ledger"


def _is_complete_analysis(run_dir: Path) -> bool:
    decisions = run_dir / "decisions"
    return (decisions / "bonds_master.json").exists() and (decisions / "portfolio_shortlist.json").exists()


def _fresh_analysis_run(max_age_hours: float) -> Path | None:
    cutoff = datetime.now() - timedelta(hours=max_age_hours)
    candidates = [
        path for path in iter_analysis_dirs(PROJECT_ROOT)
        if _is_complete_analysis(path)
        and datetime.fromtimestamp(path.stat().st_mtime) >= cutoff
    ]
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def _run_full_analysis(portfolio_name: str, config: str) -> None:
    command = entrypoint_command(PROJECT_ROOT / "bondlab.py", [
        "pipeline", "--from-stage", "1", "--to-stage", "10",
        "--config", str(Path(config).resolve()), "--portfolio", portfolio_name,
    ])
    run_command(command, cwd=PROJECT_ROOT, project_root=PROJECT_ROOT)


def _load_master(run_dir: Path) -> tuple[dict, dict[str, dict]]:
    path = run_dir / "decisions" / "bonds_master.json"
    if not path.exists():
        raise FileNotFoundError(f"Нет master dataset: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    bonds = payload.get("bonds") or []
    return payload, {str(x.get("secid")): x for x in bonds if x.get("secid")}


def _candidate_secids(run_dir: Path) -> list[str]:
    path = run_dir / "decisions" / "portfolio_shortlist.json"
    if not path.exists():
        raise FileNotFoundError(f"Нет shortlist: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [str(x.get("secid")) for x in payload.get("shortlist", []) if x.get("secid")]


def create_command(args: argparse.Namespace) -> None:
    path = create_portfolio(VIRTUAL_PORTFOLIOS_ROOT, args.name)
    print(f"Создан портфель: {args.name}")
    print(path)


def show_command(args: argparse.Namespace) -> None:
    portfolio = load_portfolio(VIRTUAL_PORTFOLIOS_ROOT, args.name)
    tx = read_ledger(LEDGER_ROOT, args.name)
    print(f"Портфель: {portfolio.get('name')}")
    print(f"Позиций: {len(portfolio.get('positions') or [])}")
    print(f"Операций: {len(tx)}")
    print(f"Свободные деньги по журналу: {cash_balance(tx):,.2f} ₽")
    for row in portfolio.get("positions") or []:
        print(f"  {row.get('secid')}: {row.get('quantity')} шт.; вложено {float(row.get('invested') or 0):,.2f} ₽")


def ledger_command(args: argparse.Namespace) -> None:
    tx = read_ledger(LEDGER_ROOT, args.name)
    print(f"Журнал {args.name}; операций: {len(tx)}; cash: {cash_balance(tx):,.2f} ₽")
    for row in tx:
        suffix = f" {row.get('secid')}" if row.get("secid") else ""
        qty = f" x{row.get('quantity')}" if row.get("quantity") else ""
        print(f"{row.get('occurred_at')} {row.get('type')}{suffix}{qty}: {float(row.get('amount') or 0):,.2f} ₽")


def transaction_command(args: argparse.Namespace) -> None:
    portfolio = load_portfolio(VIRTUAL_PORTFOLIOS_ROOT, args.name)
    kind = args.type.upper()
    if kind in {"SELL", "REDEMPTION"}:
        positions = {str(x.get("secid") or ""): dict(x) for x in portfolio.get("positions", [])}
        position = positions.get(str(args.secid or ""))
        if position is None:
            raise ValueError(f"Позиция не найдена: {args.secid}")
        old_qty = int(position.get("quantity") or 0)
        qty = old_qty if kind == "REDEMPTION" and args.quantity is None else int(args.quantity or 0)
        if qty <= 0 or qty > old_qty:
            raise ValueError(f"Некорректное количество: {qty}; в портфеле {old_qty}")
        if qty == old_qty:
            portfolio = remove_position(portfolio, args.secid)
        else:
            old_invested = float(position.get("invested") or 0)
            position["quantity"] = old_qty - qty
            position["invested"] = round(old_invested * (old_qty - qty) / old_qty, 2)
            portfolio = upsert_position(portfolio, position)
        save_portfolio(VIRTUAL_PORTFOLIOS_ROOT, portfolio)
        args.quantity = qty
    row = append_transaction(
        LEDGER_ROOT, args.name, kind, amount=args.amount, secid=args.secid,
        quantity=args.quantity, unit_cost=args.unit_cost, note=args.note,
    )
    print(json.dumps(row, ensure_ascii=False, indent=2))


def invest_command(args: argparse.Namespace) -> None:
    portfolio = load_portfolio(VIRTUAL_PORTFOLIOS_ROOT, args.name)
    if args.run_dir:
        run_dir = Path(args.run_dir).resolve()
        print(f"Используем явно указанный анализ: {run_dir.name}")
    elif args.force_refresh:
        print("Запрошен принудительный новый анализ рынка.")
        _run_full_analysis(args.name, args.config)
        run_dir = latest_analysis_run(PROJECT_ROOT)
    else:
        run_dir = _fresh_analysis_run(args.max_age_hours)
        if run_dir is not None:
            print(f"Используем свежий готовый анализ: {run_dir.name}")
        else:
            print(f"Готового анализа моложе {args.max_age_hours:g} ч нет — запускаем pipeline 1–10.")
            _run_full_analysis(args.name, args.config)
            run_dir = latest_analysis_run(PROJECT_ROOT)

    if run_dir is None or not _is_complete_analysis(run_dir):
        raise FileNotFoundError("Не найден завершённый анализ с master dataset и shortlist.")

    _, bonds = _load_master(run_dir)
    candidates = _candidate_secids(run_dir)
    previous_cash = cash_balance(read_ledger(LEDGER_ROOT, args.name))
    available = previous_cash + args.amount
    if available <= 0:
        raise ValueError("Нет доступных денег для распределения")

    plan = allocate_budget(
        portfolio, bonds, candidates, available,
        max_position_percent=args.max_position_percent,
        max_issuer_percent=args.max_issuer_percent,
    )
    print(f"\nПортфель: {args.name}")
    print(f"Новый взнос: {args.amount:,.2f} ₽")
    print(f"Свободный остаток: {previous_cash:,.2f} ₽")
    print(f"Доступно: {available:,.2f} ₽\n")
    for line in plan["lines"]:
        print(f"{line['action']:9} {line['secid']}  {line['quantity']} шт. x {line['unit_cost']:,.2f} = {line['amount']:,.2f} ₽  ({line['reason']})")
    print(f"\nПлан покупки: {plan['invested']:,.2f} ₽")
    print(f"Останется cash: {plan['reserve']:,.2f} ₽")
    if plan["excluded"]:
        print(f"Исключено кандидатов: {len(plan['excluded'])}")

    if not plan["lines"]:
        print("Подходящих покупок нет. Портфель не изменён.")
        return
    if not args.yes:
        answer = input("\nПодтвердить DEPOSIT и BUY операции? [y/N]: ").strip().lower()
        if answer not in {"y", "yes", "д", "да"}:
            print("Отменено. Портфель и журнал не изменены.")
            return

    batch = uuid4().hex
    if args.amount > 0:
        append_transaction(LEDGER_ROOT, args.name, "DEPOSIT", amount=args.amount, note="invest command", batch_id=batch)
    updated = apply_allocation_plan(portfolio, plan["lines"], bonds)
    for line in plan["lines"]:
        append_transaction(
            LEDGER_ROOT, args.name, "BUY", amount=line["amount"], secid=line["secid"],
            quantity=line["quantity"], unit_cost=line["unit_cost"], note=line.get("reason"), batch_id=batch,
        )
    save_portfolio(VIRTUAL_PORTFOLIOS_ROOT, updated)
    print(f"\nГотово. Покупки записаны. Свободный cash: {cash_balance(read_ledger(LEDGER_ROOT, args.name)):,.2f} ₽")


def main() -> None:
    parser = argparse.ArgumentParser(description="Управление виртуальными портфелями")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create")
    create.add_argument("--name", required=True)
    create.set_defaults(func=create_command)

    show = sub.add_parser("show")
    show.add_argument("--name", required=True)
    show.set_defaults(func=show_command)

    ledger = sub.add_parser("ledger")
    ledger.add_argument("--name", required=True)
    ledger.set_defaults(func=ledger_command)

    tx = sub.add_parser("transaction")
    tx.add_argument("--name", required=True)
    tx.add_argument("--type", required=True, choices=["DEPOSIT", "BUY", "SELL", "COUPON", "REDEMPTION"])
    tx.add_argument("--amount", required=True, type=float)
    tx.add_argument("--secid")
    tx.add_argument("--quantity", type=int)
    tx.add_argument("--unit-cost", type=float)
    tx.add_argument("--note")
    tx.set_defaults(func=transaction_command)

    invest = sub.add_parser("invest")
    invest.add_argument("--name", required=True)
    invest.add_argument("--amount", required=True, type=float)
    invest.add_argument("--refresh", action="store_true", help="Совместимость: invest и так обновит данные, если свежего анализа нет")
    invest.add_argument("--force-refresh", action="store_true", help="Всегда выполнить новый pipeline 1-10")
    invest.add_argument("--max-age-hours", type=float, default=12.0, help="Максимальный возраст готового анализа для повторного использования")
    invest.add_argument("--config", default=str(GUI_CONFIG))
    invest.add_argument("--run-dir")
    invest.add_argument("--max-position-percent", type=float, default=20.0)
    invest.add_argument("--max-issuer-percent", type=float, default=25.0)
    invest.add_argument("-y", "--yes", action="store_true", help="Применить план без интерактивного подтверждения")
    invest.set_defaults(func=invest_command)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
