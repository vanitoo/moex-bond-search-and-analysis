# 📊 Поиск информации об эмитентах и новостей о компаниях 📊
#
# Читает результат этапа 1 из текущей папки запуска, определяет эмитентов
# через API Московской биржи и сохраняет найденные новости в локальные файлы.

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import emoji
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from moex_bond_search_and_analysis.logger import like_print_log
from moex_bond_search_and_analysis.news import google_search, write_to_file
from moex_bond_search_and_analysis.utils import create_news_folder, setup_encoding


MOEX_TIMEOUT = 20


def latest_search_file(root: Path) -> Path:
    files = [
        path
        for path in root.glob("bond_search_*.xlsx")
        if not path.name.startswith("~$")
    ]
    if not files:
        raise FileNotFoundError(
            f"В папке {root} не найден bond_search_YYYY-MM-DD.xlsx. "
            "Сначала запустите этап 1 или передайте --input."
        )
    return max(files, key=lambda path: path.stat().st_mtime)


def load_secids(source: Path) -> list[str]:
    df = pd.read_excel(source, sheet_name="Результаты поиска")
    column = "Код ценной бумаги"
    if column not in df.columns:
        raise ValueError(f"В файле {source} отсутствует столбец '{column}'")

    secids = df[column].dropna().astype(str).str.strip().str.upper()
    secids = secids[secids.str.fullmatch(r"RU[A-Z0-9]{10}", na=False)]
    return secids.drop_duplicates().tolist()


def fetch_company_names(secids: list[str]) -> list[str]:
    """Получает именно названия эмитентов, а не ИНН из соседнего столбца MOEX."""
    company_names: list[str] = []

    for index, secid in enumerate(secids, 1):
        like_print_log.info(f"[{index}/{len(secids)}] Определение эмитента: {secid}")
        url = (
            "https://iss.moex.com/iss/securities.json"
            f"?q={secid}&iss.meta=off&securities.columns=secid,emitent_title"
        )
        try:
            response = requests.get(url, timeout=MOEX_TIMEOUT)
            response.raise_for_status()
            payload = response.json()
            block = payload.get("securities", {})
            columns = block.get("columns", [])
            rows = block.get("data", [])

            if not rows or "emitent_title" not in columns:
                like_print_log.info(f"⚠️ Эмитент для {secid} не найден")
                continue

            secid_idx = columns.index("secid")
            title_idx = columns.index("emitent_title")
            row = next(
                (item for item in rows if str(item[secid_idx]).upper() == secid),
                rows[0],
            )
            company = str(row[title_idx] or "").strip()
            if not company:
                like_print_log.info(f"⚠️ MOEX вернул пустое название эмитента для {secid}")
                continue

            company_names.append(company)
            like_print_log.info(f"✅ {secid} → {company}")
        except (requests.RequestException, ValueError, KeyError, IndexError) as exc:
            raise RuntimeError(f"Не удалось определить эмитента {secid}: {exc}") from exc

        time.sleep(0.5)

    return list(dict.fromkeys(company_names))


def main() -> None:
    parser = argparse.ArgumentParser(description="Сбор новостей по найденным облигациям")
    parser.add_argument("--input", type=Path, help="Файл bond_search_YYYY-MM-DD.xlsx")
    parser.add_argument(
        "--delay",
        type=float,
        default=3.0,
        help="Пауза между поисковыми запросами, секунд",
    )
    args = parser.parse_args()

    setup_encoding()
    source = args.input or latest_search_file(Path.cwd())
    like_print_log.info(f"📂 Загружаем данные из {source.name}...")
    secids = load_secids(source)
    like_print_log.info(f"✅ Найдено выпусков: {len(secids)}")

    company_names = fetch_company_names(secids)
    if not company_names:
        raise RuntimeError("Не удалось определить ни одного эмитента. Поиск новостей остановлен.")
    like_print_log.info(f"✅ Найдено уникальных эмитентов: {len(company_names)}")

    news_folder_path = create_news_folder()
    for index, company in enumerate(company_names, 1):
        like_print_log.info(f"[{index}/{len(company_names)}] Поиск новостей: {company}")
        news = google_search(company, like_print_log)
        write_to_file(news_folder_path, company, news)
        like_print_log.info(
            emoji.emojize(f"✍️ Сохранено новостей: {len(news)} для {company}")
        )
        if index < len(company_names):
            time.sleep(args.delay)

    like_print_log.info(f"🎉 Обработка завершена. Папка новостей: {news_folder_path}")


if __name__ == "__main__":
    main()
