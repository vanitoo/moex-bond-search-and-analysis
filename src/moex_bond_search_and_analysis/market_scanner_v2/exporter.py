from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pandas as pd

from .models import ScannerConfig


def export_excel(
    output: Path,
    result: pd.DataFrame,
    rejected: pd.DataFrame,
    config: ScannerConfig,
    market_count: int,
    candidate_count: int,
    elapsed: float,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    parameters = asdict(config)
    stats = pd.DataFrame({
        "Показатель": [
            "Строк рынка",
            "После локальной фильтрации",
            "Итоговых выпусков",
            "Исключено после обогащения",
            "Время, секунд",
            "Версия сканера",
        ],
        "Значение": [market_count, candidate_count, len(result), len(rejected), round(elapsed, 2), "V2.2"],
    })
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        result.to_excel(writer, sheet_name="Результаты поиска", index=False)
        rejected.to_excel(writer, sheet_name="Исключённые V2", index=False)
        pd.DataFrame({"Параметр": parameters.keys(), "Значение": [str(v) for v in parameters.values()]}).to_excel(
            writer, sheet_name="Параметры", index=False
        )
        stats.to_excel(writer, sheet_name="Статистика V2", index=False)
