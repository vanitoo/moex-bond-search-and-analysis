from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


def safe_float(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "" or (isinstance(value, float) and pd.isna(value)):
        return default
    try:
        return float(str(value).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return default


def normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower().replace("ё", "е"))


def latest(root: Path, pattern: str, required: bool = True) -> Path | None:
    files = [p for p in root.glob(pattern) if not p.name.startswith("~$")]
    if not files:
        if required:
            raise FileNotFoundError(f"Не найден файл {pattern}")
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def read_table(path: Path, sheet_name: str | int = 0) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            for key in ("items", "bonds", "candidates", "news", "cashflows", "volumes"):
                if isinstance(payload.get(key), list):
                    payload = payload[key]
                    break
        return pd.DataFrame(payload)
    return pd.read_excel(path, sheet_name=sheet_name)


def merge_by_secid(base: pd.DataFrame, extra: pd.DataFrame, prefix: str = "") -> pd.DataFrame:
    if extra.empty or "Код ценной бумаги" not in extra.columns:
        return base
    extra = extra.drop_duplicates("Код ценной бумаги", keep="last").copy()
    if prefix:
        extra = extra.rename(columns={c: f"{prefix}{c}" for c in extra.columns if c != "Код ценной бумаги"})
    return base.merge(extra, on="Код ценной бумаги", how="left")


def dated_name(prefix: str, suffix: str) -> str:
    return f"{prefix}_{datetime.now():%Y-%m-%d}.{suffix}"
