from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_WORKERS = 5
DEFAULT_CACHE_HOURS = 12.0
HISTORY_CALENDAR_DAYS = 15
MIN_HISTORY_SESSIONS = 6
MAX_MARKET_PAGES = 1000


@dataclass(frozen=True, slots=True)
class ScannerConfig:
    yield_more: float = 15.0
    yield_less: float = 40.0
    price_more: float = 70.0
    price_less: float = 120.0
    duration_more: float = 3.0
    duration_less: float = 18.0
    volume_more: float = 2000.0
    bond_volume_more: float = 60000.0
    require_known_coupons: bool = True
    workers: int = DEFAULT_WORKERS
    cache_hours: float = DEFAULT_CACHE_HOURS
    cache_dir: Path | None = None
    output: Path | None = None
    log_level: str = "INFO"
    log_file: Path | None = None

    def validate(self) -> None:
        if not 1 <= self.workers <= 8:
            raise ValueError("--workers должен быть от 1 до 8")
        if self.cache_hours < 0:
            raise ValueError("--cache-hours не может быть отрицательным")
        if self.yield_more > self.yield_less:
            raise ValueError("Доходность ОТ не может быть больше доходности ДО")
        if self.price_more > self.price_less:
            raise ValueError("Цена ОТ не может быть больше цены ДО")
        if self.duration_more > self.duration_less:
            raise ValueError("Дюрация ОТ не может быть больше дюрации ДО")
        if self.volume_more < 0 or self.bond_volume_more < 0:
            raise ValueError("Объёмы торгов не могут быть отрицательными")
