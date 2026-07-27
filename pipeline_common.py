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
    if value is None or pd.isna(value):
        return ""
    return re.sub(r"\s+", " ", str(value).strip().lower().replace("ё", "е"))


def clean_secid_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Удаляет служебные строки, пустые SECID и дубли выпусков."""
    if "Код ценной бумаги" not in df.columns:
        return df.copy()
    result = df.copy()
    result = result.dropna(subset=["Код ценной бумаги"])
    result["Код ценной бумаги"] = result["Код ценной бумаги"].astype(str).str.strip().str.upper()
    result = result[result["Код ценной бумаги"].str.fullmatch(r"RU[A-Z0-9]{10}", na=False)]
    return result.drop_duplicates(subset=["Код ценной бумаги"], keep="first").reset_index(drop=True)


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
    base = clean_secid_rows(base)
    extra = clean_secid_rows(extra)
    if prefix:
        extra = extra.rename(columns={c: f"{prefix}{c}" for c in extra.columns if c != "Код ценной бумаги"})
    return base.merge(extra, on="Код ценной бумаги", how="left")


def dated_name(prefix: str, suffix: str) -> str:
    return f"{prefix}_{datetime.now():%Y-%m-%d}.{suffix}"
