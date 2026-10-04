from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd


@dataclass(frozen=True)
class FrameContract:
    """Explicit contract for a DataFrame crossing a pipeline stage boundary."""

    name: str
    required_columns: frozenset[str]
    secid_column: str = "Код ценной бумаги"

    @classmethod
    def from_columns(cls, name: str, columns: Iterable[str], *, secid_column: str = "Код ценной бумаги") -> "FrameContract":
        return cls(name=name, required_columns=frozenset(columns), secid_column=secid_column)

    def missing_columns(self, frame: pd.DataFrame) -> frozenset[str]:
        return self.required_columns.difference(frame.columns)

    def validate(self, frame: pd.DataFrame) -> pd.DataFrame:
        missing = self.missing_columns(frame)
        if missing:
            raise ValueError(
                f"{self.name}: отсутствуют обязательные колонки: "
                + ", ".join(sorted(missing))
            )
        return frame

    def clean(self, frame: pd.DataFrame) -> pd.DataFrame:
        self.validate(frame)
        if self.secid_column not in frame.columns:
            return frame.copy()
        return frame.dropna(subset=[self.secid_column]).copy()
