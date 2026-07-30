from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from .cache import JsonCache
from .exporter import export_excel
from .filters import local_filter, output_row, split_accepted_rejected
from .models import ScannerConfig
from .moex_client import MoexClient

LOGGER = logging.getLogger("market_scanner_v2")


def setup_logging(level: str, log_file: Path) -> None:
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    LOGGER.setLevel(numeric_level)
    LOGGER.handlers.clear()
    LOGGER.propagate = False
    console = logging.StreamHandler()
    console.setLevel(numeric_level)
    console.setFormatter(formatter)
    LOGGER.addHandler(console)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    LOGGER.addHandler(file_handler)


def _enrich(row: dict[str, Any], client: MoexClient) -> dict[str, Any]:
    secid = str(row.get("SECID") or "")
    primary_board = client.fetch_primary_board(secid)
    board = primary_board or str(row.get("BOARDID") or "TQCB")
    history = client.fetch_history(secid, board)
    cashflow = client.fetch_cashflow(secid)
    return {**row, "BOARDID": board, **history, **cashflow}


def run_scan(config: ScannerConfig, project_root: Path) -> Path:
    config.validate()
    log_file = config.log_file or Path.cwd() / "market_scanner_v2.log"
    setup_logging(config.log_level, log_file)
    cache_dir = config.cache_dir or project_root / "data" / "cache" / "market_scanner_v2"
    output = config.output or Path.cwd() / f"bond_search_{date.today():%Y-%m-%d}.xlsx"

    started = time.perf_counter()
    cache = JsonCache(cache_dir, config.cache_hours, LOGGER)
    client = MoexClient(cache, LOGGER)
    market = client.fetch_market()
    candidates = local_filter(pd.DataFrame(market), config)
    LOGGER.info("После фильтра цены, доходности и дюрации: %s выпусков", len(candidates))

    enriched: list[dict[str, Any]] = []
    records = candidates.to_dict("records")
    with ThreadPoolExecutor(max_workers=config.workers, thread_name_prefix="moex-v2") as pool:
        futures = {pool.submit(_enrich, row, client): str(row.get("SECID")) for row in records}
        for index, future in enumerate(as_completed(futures), 1):
            secid = futures[future]
            try:
                enriched.append(future.result())
                LOGGER.info("Обогащение [%s/%s] готово: %s", index, len(futures), secid)
            except Exception as exc:
                LOGGER.exception("Обогащение [%s/%s] ошибка %s: %s", index, len(futures), secid, exc)

    all_rows = pd.DataFrame(output_row(row) for row in enriched)
    result, rejected = split_accepted_rejected(all_rows, config)
    elapsed = time.perf_counter() - started
    export_excel(output, result, rejected, config, len(market), len(candidates), elapsed)
    LOGGER.info("V2 завершён за %.1f сек. Найдено: %s; исключено: %s", elapsed, len(result), len(rejected))
    LOGGER.info("Результат: %s", output)
    return output
