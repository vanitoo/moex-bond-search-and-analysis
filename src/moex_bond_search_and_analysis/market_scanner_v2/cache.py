from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

CACHE_SCHEMA_VERSION = "v2_2"


class JsonCache:
    def __init__(self, root: Path, ttl_hours: float, logger: logging.Logger) -> None:
        self.root = root
        self.ttl_hours = ttl_hours
        self.logger = logger

    def path(self, namespace: str, key: str) -> Path:
        directory = self.root / CACHE_SCHEMA_VERSION / namespace
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{key}.json"

    def get(self, namespace: str, key: str) -> Any | None:
        path = self.path(namespace, key)
        if self.ttl_hours <= 0 or not path.exists():
            return None
        age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
        if age > timedelta(hours=self.ttl_hours):
            self.logger.debug("Кэш устарел: %s", path)
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.logger.debug("Кэш прочитан: %s", path)
            return payload
        except (OSError, json.JSONDecodeError) as exc:
            self.logger.warning("Не удалось прочитать кэш %s: %s", path, exc)
            return None

    def put(self, namespace: str, key: str, payload: Any) -> None:
        path = self.path(namespace, key)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
        self.logger.debug("Кэш записан: %s", path)
