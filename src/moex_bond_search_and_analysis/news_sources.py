from __future__ import annotations

import os
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

import feedparser
import requests

from moex_bond_search_and_analysis.schemas import NewsItem


DEFAULT_TIMEOUT = 20
DEFAULT_ATTEMPTS = 3
DEFAULT_RETRY_DELAY = 2.0
MOEX_ALL_NEWS_RSS = "https://www.moex.com/export/news.aspx?cat=200"


@dataclass
class ProviderStatus:
    provider: str
    ok: bool
    item_count: int = 0
    error: str | None = None
    used_proxy: bool = False

    def as_dict(self) -> dict:
        return {
            "provider": self.provider,
            "ok": self.ok,
            "item_count": self.item_count,
            "error": self.error,
            "used_proxy": self.used_proxy,
        }


@dataclass
class AggregatedNews:
    items: list[NewsItem] = field(default_factory=list)
    providers: list[ProviderStatus] = field(default_factory=list)

    @property
    def successful_providers(self) -> int:
        return sum(status.ok for status in self.providers)

    @property
    def enabled_providers(self) -> int:
        return len(self.providers)

    @property
    def coverage(self) -> str:
        if not self.providers or self.successful_providers == 0:
            return "NO_DATA"
        if self.successful_providers == self.enabled_providers:
            return "FULL"
        if self.successful_providers >= max(1, self.enabled_providers // 2):
            return "PARTIAL"
        return "POOR"


def proxy_url_from_env(env_name: str = "NEWS_PROXY") -> str | None:
    """Возвращает прокси без логирования секрета.

    Приоритет: специальная переменная NEWS_PROXY, затем стандартные HTTPS_PROXY/HTTP_PROXY.
    """
    for key in (env_name, "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        value = os.getenv(key)
        if value and value.strip():
            return value.strip()
    return None


def _proxies(proxy_url: str | None) -> dict[str, str] | None:
    if not proxy_url:
        return None
    return {"http": proxy_url, "https": proxy_url}


def _request(url: str, *, proxy_url: str | None = None, timeout: int = DEFAULT_TIMEOUT,
             attempts: int = DEFAULT_ATTEMPTS, retry_delay: float = DEFAULT_RETRY_DELAY) -> requests.Response:
    last_error: requests.RequestException | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(
                url,
                timeout=timeout,
                headers={"User-Agent": "Mozilla/5.0 bond-news-pipeline/2.0"},
                proxies=_proxies(proxy_url),
            )
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(retry_delay * attempt)
    assert last_error is not None
    raise last_error


def _parse_rss(content: bytes, provider: str) -> list[NewsItem]:
    if not content.strip():
        raise RuntimeError(f"{provider}: пустой HTTP-ответ")
    feed = feedparser.parse(content)
    if getattr(feed, "bozo", False):
        raise RuntimeError(f"{provider}: некорректный RSS: {getattr(feed, 'bozo_exception', 'unknown')}")
    if not getattr(feed, "feed", None):
        raise RuntimeError(f"{provider}: ответ не похож на RSS")

    items: list[NewsItem] = []
    for entry in feed.entries:
        published = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
        if published:
            date = datetime(*published[:6], tzinfo=timezone.utc).replace(tzinfo=None)
        else:
            date = datetime.now()
        source = ""
        if "source" in entry:
            source = getattr(entry.source, "title", "") or ""
        items.append(
            NewsItem(
                source=source or provider,
                title=str(getattr(entry, "title", "")),
                date=date,
                url=str(getattr(entry, "link", "")),
            )
        )
    return items


def google_news(company: str, *, proxy_url: str | None = None) -> list[NewsItem]:
    query = urllib.parse.quote(company)
    url = f"https://news.google.com/rss/search?q={query}+when:1y&hl=ru&gl=RU&ceid=RU:ru"
    response = _request(url, proxy_url=proxy_url)
    return _parse_rss(response.content, "Google News")


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower().replace("ё", "е")).strip()


def _company_aliases(company: str) -> list[str]:
    text = str(company or "").strip()
    aliases: list[str] = []
    quoted = re.findall(r'["«“](.*?)["»”]', text)
    aliases.extend(part.strip() for part in quoted if len(part.strip()) >= 4)
    cleaned = re.sub(
        r"\b(публичное|акционерное|общество|общество с ограниченной ответственностью|пао|ао|ооо|холдинговая компания)\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r'["«»“”]', " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.-")
    if len(cleaned) >= 5:
        aliases.append(cleaned)
    return list(dict.fromkeys(_normalize(alias) for alias in aliases if alias))


def moex_news(company: str, secids: Iterable[str] = (), *, proxy_url: str | None = None) -> list[NewsItem]:
    """Фильтрует официальный RSS Московской биржи по SECID и названию эмитента.

    RSS MOEX является общебиржевой лентой, поэтому сначала загружается лента, затем локально
    выбираются записи, относящиеся к конкретному выпуску/эмитенту.
    """
    response = _request(MOEX_ALL_NEWS_RSS, proxy_url=proxy_url)
    items = _parse_rss(response.content, "MOEX")
    secid_tokens = {_normalize(secid) for secid in secids if str(secid).strip()}
    aliases = _company_aliases(company)
    result: list[NewsItem] = []
    for item in items:
        haystack = _normalize(f"{item.title} {item.url}")
        if any(token and token in haystack for token in secid_tokens) or any(alias in haystack for alias in aliases):
            result.append(item)
    return result


def aggregate_news(company: str, secids: Iterable[str] = (), *, providers: Iterable[str] = ("google", "moex"),
                   proxy_env: str = "NEWS_PROXY") -> AggregatedNews:
    proxy_url = proxy_url_from_env(proxy_env)
    result = AggregatedNews()
    seen: set[tuple[str, str]] = set()

    for provider in providers:
        key = str(provider).strip().lower()
        if not key:
            continue
        try:
            if key == "google":
                items = google_news(company, proxy_url=proxy_url)
                provider_name = "Google News"
            elif key == "moex":
                items = moex_news(company, secids, proxy_url=proxy_url)
                provider_name = "MOEX"
            else:
                result.providers.append(ProviderStatus(provider=key, ok=False, error="Неизвестный provider"))
                continue
        except Exception as exc:
            result.providers.append(
                ProviderStatus(provider=key, ok=False, error=str(exc), used_proxy=bool(proxy_url))
            )
            continue

        result.providers.append(
            ProviderStatus(provider=provider_name, ok=True, item_count=len(items), used_proxy=bool(proxy_url))
        )
        for item in items:
            dedupe_key = (_normalize(item.title), str(item.url).strip())
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            result.items.append(item)

    result.items.sort(key=lambda item: item.date, reverse=True)
    return result
