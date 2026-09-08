from datetime import datetime
import os
import re
import emoji

from moex_bond_search_and_analysis.logger import Logger
from moex_bond_search_and_analysis.news_sources import google_news, proxy_url_from_env
from moex_bond_search_and_analysis.schemas import NewsItem


def google_search(company: str, log: Logger) -> list[NewsItem]:
    """Совместимый wrapper для старого кода.

    Использует NEWS_PROXY (или стандартные HTTPS_PROXY/HTTP_PROXY), если переменная окружения задана.
    Значение прокси намеренно не выводится в лог.
    """
    log.info(emoji.emojize(f"\n🔍 Поиск новостей: {company}"))
    proxy = proxy_url_from_env("NEWS_PROXY")
    if proxy:
        log.info("🌐 Google News: используется настроенный прокси (адрес скрыт)")
    try:
        items = google_news(company, proxy_url=proxy)
    except Exception as exc:
        raise RuntimeError(f"Google News RSS недоступен: {exc}") from exc
    if items:
        log.info(f"✅ Получен корректный RSS. Найдено новостей: {len(items)}")
    else:
        log.info("ℹ️ Получен корректный RSS, но по запросу действительно нет новостей")
    return items


def safe_filename(value: str, max_length: int = 160) -> str:
    """Возвращает безопасное имя файла для Windows/Linux/macOS."""
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value))
    value = re.sub(r"\s+", "_", value).strip(" ._")
    return (value or "issuer")[:max_length].rstrip(" ._")


def write_to_file(folder_path: str, company: str, news: list[NewsItem]) -> None:
    """✍️ Записывает новости в файл."""
    filename = os.path.join(folder_path, f"{safe_filename(company)}.txt")
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"📰 Новости для компании {company}\n")
        f.write("=" * 50 + "\n\n")

        for item in sorted(news, key=lambda x: x.date, reverse=True):
            f.write(f"📅 Дата: {item.date.strftime('%Y-%m-%d %H:%M')}\n")
            f.write(f"📰 Источник: {item.source}\n")
            f.write(f"📌 Заголовок: {item.title}\n")
            f.write(f"🔗 URL: {item.url}\n")
            f.write("-" * 30 + "\n\n")
