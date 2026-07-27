from datetime import datetime
import os
import time
import emoji
import urllib.parse

import feedparser
import requests
from moex_bond_search_and_analysis.logger import Logger
from moex_bond_search_and_analysis.schemas import NewsItem


GOOGLE_NEWS_TIMEOUT = 20
GOOGLE_NEWS_ATTEMPTS = 3
GOOGLE_NEWS_RETRY_DELAY = 2.0


def google_search(company: str, log: Logger) -> list[NewsItem]:
    """🔍 Выполняет поиск новостей по компании.

    Пустой корректный RSS означает, что новостей действительно нет.
    Сетевая ошибка, блокировка или некорректный ответ приводят к исключению,
    чтобы pipeline не создавал ложные пустые результаты.
    """
    log.info(emoji.emojize(f"\n🔍 Поиск новостей: {company}"))
    query = urllib.parse.quote(company)
    url = f"https://news.google.com/rss/search?q={query}+when:1y&hl=ru&gl=RU&ceid=RU:ru"
    log.info(f"📌 Сформирован URL запроса: {url}")

    last_error: requests.RequestException | None = None
    response: requests.Response | None = None
    for attempt in range(1, GOOGLE_NEWS_ATTEMPTS + 1):
        try:
            response = requests.get(
                url,
                timeout=GOOGLE_NEWS_TIMEOUT,
                headers={"User-Agent": "Mozilla/5.0 bond-news-pipeline/1.0"},
            )
            response.raise_for_status()
            break
        except requests.RequestException as exc:
            last_error = exc
            response = None
            if attempt == GOOGLE_NEWS_ATTEMPTS:
                break
            delay = GOOGLE_NEWS_RETRY_DELAY * attempt
            log.info(
                f"⚠️ Google News временно недоступен (попытка "
                f"{attempt}/{GOOGLE_NEWS_ATTEMPTS}): {exc}. "
                f"Повтор через {delay:g} сек."
            )
            time.sleep(delay)

    if response is None:
        raise RuntimeError(
            f"Google News RSS недоступен после {GOOGLE_NEWS_ATTEMPTS} попыток. "
            f"Запрос: {url}. Ошибка: {last_error}"
        ) from last_error

    if not response.content.strip():
        raise RuntimeError(
            "Google News RSS вернул пустой HTTP-ответ. Поиск остановлен, чтобы не записывать "
            "ложные результаты '0 новостей'."
        )

    feed: feedparser.FeedParserDict = feedparser.parse(response.content)
    if getattr(feed, "bozo", False):
        error = getattr(feed, "bozo_exception", "неизвестная ошибка RSS")
        raise RuntimeError(
            "Google News вернул некорректный RSS. Возможно, доступ заблокирован или вместо RSS "
            f"пришла служебная страница. Ошибка разбора: {error}"
        )

    if not getattr(feed, "feed", None):
        raise RuntimeError(
            "Ответ Google News не похож на RSS-ленту. Поиск остановлен, чтобы не считать сбой "
            "успешным пустым результатом."
        )

    news_items = [
        NewsItem(
            source=entry.source.title if "source" in entry else "Google News",
            title=entry.title,
            date=datetime.strptime(entry.published, "%a, %d %b %Y %H:%M:%S %Z"),
            url=entry.link,
        )
        for entry in feed.entries
    ]

    if news_items:
        log.info(f"✅ Получен корректный RSS. Найдено новостей: {len(news_items)}")
    else:
        log.info("ℹ️ Получен корректный RSS, но по запросу действительно нет новостей")
    return news_items


def write_to_file(folder_path: str, company: str, news: list[NewsItem]) -> None:
    """✍️ Записывает новости в файл."""
    filename = os.path.join(folder_path, f"{company.replace(' ', '_')}.txt")
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"📰 Новости для компании {company}\n")
        f.write("=" * 50 + "\n\n")

        for item in sorted(news, key=lambda x: x.date, reverse=True):
            f.write(f"📅 Дата: {item.date.strftime('%Y-%m-%d %H:%M')}\n")
            f.write(f"📰 Источник: {item.source}\n")
            f.write(f"📌 Заголовок: {item.title}\n")
            f.write(f"🔗 URL: {item.url}\n")
            f.write("-" * 30 + "\n\n")
