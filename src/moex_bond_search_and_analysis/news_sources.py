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
from bs4 import BeautifulSoup

from moex_bond_search_and_analysis.schemas import NewsItem


DEFAULT_TIMEOUT = 20
DEFAULT_ATTEMPTS = 3
DEFAULT_RETRY_DELAY = 2.0
MOEX_ALL_NEWS_RSS = "https://www.moex.com/export/news.aspx?cat=200"
ACRA_URL = "https://www.acra-ratings.ru/?lang=ru"
EXPERT_RA_URL = "https://raexpert.ru/ratings/"


@dataclass
class ProviderStatus:
    provider: str
    ok: bool
    item_count: int = 0
    error: str | None = None
    used_proxy: bool = False

    def as_dict(self) -> dict:
        return {"provider": self.provider, "ok": self.ok, "item_count": self.item_count,
                "error": self.error, "used_proxy": self.used_proxy}


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
    """Возвращает только явно заданный news proxy.

    Системные HTTPS_PROXY/HTTP_PROXY намеренно не подхватываются: прокси для новостей
    должен включаться явно, чтобы он случайно не влиял на MOEX/АКРА/Эксперт РА.
    """
    value = os.getenv(env_name)
    return value.strip() if value and value.strip() else None


def _proxies(proxy_url: str | None) -> dict[str, str] | None:
    return {"http": proxy_url, "https": proxy_url} if proxy_url else None


def _request(url: str, *, proxy_url: str | None = None, timeout: int = DEFAULT_TIMEOUT,
             attempts: int = DEFAULT_ATTEMPTS, retry_delay: float = DEFAULT_RETRY_DELAY) -> requests.Response:
    last_error: requests.RequestException | None = None
    session = requests.Session()
    session.trust_env = False
    for attempt in range(1, attempts + 1):
        try:
            response = session.get(url, timeout=timeout,
                                   headers={"User-Agent": "Mozilla/5.0 bond-news-pipeline/2.1"},
                                   proxies=_proxies(proxy_url))
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
        date = datetime(*published[:6], tzinfo=timezone.utc).replace(tzinfo=None) if published else datetime.now()
        source = getattr(getattr(entry, "source", None), "title", "") or provider
        items.append(NewsItem(source=source, title=str(getattr(entry, "title", "")), date=date,
                              url=str(getattr(entry, "link", ""))))
    return items


def google_news(company: str, *, proxy_url: str | None = None) -> list[NewsItem]:
    query = urllib.parse.quote(company)
    url = f"https://news.google.com/rss/search?q={query}+when:1y&hl=ru&gl=RU&ceid=RU:ru"
    return _parse_rss(_request(url, proxy_url=proxy_url).content, "Google News")


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower().replace("ё", "е")).strip()


def _company_aliases(company: str) -> list[str]:
    text = str(company or "").strip()
    aliases: list[str] = []
    aliases.extend(part.strip() for part in re.findall(r'["«“](.*?)["»”]', text) if len(part.strip()) >= 4)
    cleaned = re.sub(r"\b(публичное|акционерное|общество|общество с ограниченной ответственностью|пао|ао|ооо|холдинговая компания)\b",
                     " ", text, flags=re.IGNORECASE)
    cleaned = re.sub(r'["«»“”]', " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.-")
    if len(cleaned) >= 5:
        aliases.append(cleaned)
    return list(dict.fromkeys(_normalize(alias) for alias in aliases if alias))


def _matches(text: str, company: str, secids: Iterable[str]) -> bool:
    haystack = _normalize(text)
    tokens = {_normalize(secid) for secid in secids if str(secid).strip()}
    return any(token and token in haystack for token in tokens) or any(alias in haystack for alias in _company_aliases(company))


def moex_news(company: str, secids: Iterable[str] = (), *, proxy_url: str | None = None) -> list[NewsItem]:
    items = _parse_rss(_request(MOEX_ALL_NEWS_RSS, proxy_url=proxy_url).content, "MOEX")
    return [item for item in items if _matches(f"{item.title} {item.url}", company, secids)]


def _html_rating_news(url: str, provider: str, company: str, secids: Iterable[str],
                      *, proxy_url: str | None = None) -> list[NewsItem]:
    response = _request(url, proxy_url=proxy_url)
    if not response.content.strip():
        raise RuntimeError(f"{provider}: пустой HTTP-ответ")
    soup = BeautifulSoup(response.content, "html.parser")
    items: list[NewsItem] = []
    seen: set[str] = set()
    for node in soup.find_all(["a", "article", "li", "tr", "div"]):
        text = " ".join(node.stripped_strings)
        if len(text) < 5 or len(text) > 1000 or not _matches(text, company, secids):
            continue
        link = node if node.name == "a" else node.find("a", href=True)
        href = link.get("href") if link else ""
        item_url = urllib.parse.urljoin(url, href) if href else url
        title = re.sub(r"\s+", " ", text).strip()
        key = _normalize(title)
        if key in seen:
            continue
        seen.add(key)
        items.append(NewsItem(source=provider, title=title[:500], date=datetime.now(), url=item_url))
    return items


def acra_news(company: str, secids: Iterable[str] = (), *, proxy_url: str | None = None) -> list[NewsItem]:
    return _html_rating_news(ACRA_URL, "АКРА", company, secids, proxy_url=proxy_url)


def expert_ra_news(company: str, secids: Iterable[str] = (), *, proxy_url: str | None = None) -> list[NewsItem]:
    return _html_rating_news(EXPERT_RA_URL, "Эксперт РА", company, secids, proxy_url=proxy_url)


def aggregate_news(company: str, secids: Iterable[str] = (), *,
                   providers: Iterable[str] = ("google", "moex", "acra", "expert_ra"),
                   proxy_env: str = "NEWS_PROXY", use_proxy: bool = False) -> AggregatedNews:
    proxy_url = proxy_url_from_env(proxy_env) if use_proxy else None
    result = AggregatedNews()
    seen: set[tuple[str, str]] = set()
    for provider in providers:
        key = str(provider).strip().lower()
        if not key:
            continue
        provider_proxy = proxy_url if key == "google" else None
        try:
            if key == "google":
                items, provider_name = google_news(company, proxy_url=provider_proxy), "Google News"
            elif key == "moex":
                items, provider_name = moex_news(company, secids, proxy_url=None), "MOEX"
            elif key == "acra":
                items, provider_name = acra_news(company, secids, proxy_url=None), "АКРА"
            elif key in {"expert_ra", "expertra", "raexpert"}:
                items, provider_name = expert_ra_news(company, secids, proxy_url=None), "Эксперт РА"
            else:
                result.providers.append(ProviderStatus(provider=key, ok=False, error="Неизвестный provider"))
                continue
        except Exception as exc:
            result.providers.append(ProviderStatus(provider=key, ok=False, error=str(exc), used_proxy=bool(provider_proxy)))
            continue
        result.providers.append(ProviderStatus(provider=provider_name, ok=True, item_count=len(items),
                                               used_proxy=bool(provider_proxy)))
        for item in items:
            dedupe_key = (_normalize(item.title), str(item.url).strip())
            if dedupe_key not in seen:
                seen.add(dedupe_key)
                result.items.append(item)
    result.items.sort(key=lambda item: item.date, reverse=True)
    return result
