# 📊 Поиск информации об эмитентах и новостей о компаниях 📊
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

try:
    import truststore
except ImportError:  # совместимость со старым venv до обновления зависимостей
    truststore = None
else:
    # Это entrypoint приложения, поэтому безопасно подключаем системное хранилище
    # сертификатов Windows/macOS/Linux до импорта requests/urllib3.
    truststore.inject_into_ssl()

import emoji
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from moex_bond_search_and_analysis.logger import like_print_log
from moex_bond_search_and_analysis.news import write_to_file
from moex_bond_search_and_analysis.news_sources import aggregate_news, proxy_url_from_env
from moex_bond_search_and_analysis.utils import create_news_folder, setup_encoding


MOEX_TIMEOUT = 20
MOEX_ATTEMPTS = 4
MOEX_RETRY_DELAY = 1.5
DEFAULT_MAX_FAILURE_SHARE = 0.30
DEFAULT_PROVIDERS = "google,moex,acra,expert_ra"


def latest_search_file(root: Path) -> Path:
    files = [path for path in root.glob("bond_search_*.xlsx") if not path.name.startswith("~$")]
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


def _moex_direct_get(url: str) -> requests.Response:
    session = requests.Session()
    session.trust_env = False
    return session.get(url, timeout=MOEX_TIMEOUT, headers={"User-Agent": "bond-pipeline/2.1"})


def fetch_company_mapping(secids: list[str]) -> tuple[dict[str, list[str]], list[str]]:
    mapping: dict[str, list[str]] = {}
    failed: list[str] = []
    for index, secid in enumerate(secids, 1):
        like_print_log.info(f"[{index}/{len(secids)}] Определение эмитента: {secid}")
        url = (
            "https://iss.moex.com/iss/securities.json"
            f"?q={secid}&iss.meta=off&securities.columns=secid,emitent_title"
        )
        last_error: Exception | None = None
        success = False
        for attempt in range(1, MOEX_ATTEMPTS + 1):
            try:
                response = _moex_direct_get(url)
                response.raise_for_status()
                payload = response.json()
                block = payload.get("securities", {})
                columns = block.get("columns", [])
                rows = block.get("data", [])
                if not rows or "emitent_title" not in columns:
                    last_error = RuntimeError("MOEX не вернул emitent_title")
                else:
                    secid_idx = columns.index("secid")
                    title_idx = columns.index("emitent_title")
                    row = next((item for item in rows if str(item[secid_idx]).upper() == secid), rows[0])
                    company = str(row[title_idx] or "").strip()
                    if company:
                        mapping.setdefault(company, []).append(secid)
                        like_print_log.info(f"✅ {secid} → {company}")
                        success = True
                        break
                    last_error = RuntimeError("MOEX вернул пустое название эмитента")
            except (requests.RequestException, ValueError, KeyError, IndexError, RuntimeError) as exc:
                last_error = exc
            if attempt < MOEX_ATTEMPTS:
                delay = MOEX_RETRY_DELAY * attempt
                like_print_log.info(
                    f"   ⚠️ MOEX ISS ошибка для {secid}, попытка {attempt}/{MOEX_ATTEMPTS}: "
                    f"{type(last_error).__name__}. Повтор через {delay:.1f} с."
                )
                time.sleep(delay)
        if not success:
            failed.append(secid)
            like_print_log.info(
                f"   ❌ Не удалось определить эмитента {secid} после {MOEX_ATTEMPTS} попыток: "
                f"{last_error}. Выпуск пропущен, обработка продолжается."
            )
        time.sleep(0.2)
    return mapping, failed


def clear_news_folder(folder: Path) -> int:
    removed = 0
    folder.mkdir(parents=True, exist_ok=True)
    for pattern in ("*.txt", "_coverage_meta.json"):
        for old_file in folder.glob(pattern):
            old_file.unlink()
            removed += 1
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description="Сбор новостей по найденным облигациям")
    parser.add_argument("--input", type=Path, help="Файл bond_search_YYYY-MM-DD.xlsx")
    parser.add_argument("--delay", type=float, default=1.0, help="Пауза между эмитентами, секунд")
    parser.add_argument("--max-failure-share", type=float, default=DEFAULT_MAX_FAILURE_SHARE)
    parser.add_argument("--providers", default=DEFAULT_PROVIDERS)
    parser.add_argument("--proxy-env", default="NEWS_PROXY")
    parser.add_argument(
        "--use-proxy",
        action="store_true",
        help="Явно включить прокси только для Google News. MOEX/АКРА/Эксперт РА всегда идут напрямую.",
    )
    args = parser.parse_args()
    if not 0 <= args.max_failure_share <= 1:
        parser.error("--max-failure-share должен быть в диапазоне от 0 до 1")

    providers = [item.strip().lower() for item in args.providers.split(",") if item.strip()]
    if not providers:
        parser.error("Нужно включить хотя бы один news provider")

    setup_encoding()
    if truststore is None:
        like_print_log.info(
            "⚠️ truststore не установлен: HTTPS использует CA-bundle Python. "
            "Установите зависимости проекта, чтобы использовать системные сертификаты Windows."
        )
    else:
        like_print_log.info("🔐 HTTPS: используется системное хранилище доверенных сертификатов ОС")

    source = args.input or latest_search_file(Path.cwd())
    like_print_log.info(f"📂 Загружаем данные из {source.name}...")
    secids = load_secids(source)
    like_print_log.info(f"✅ Найдено выпусков: {len(secids)}")

    company_mapping, unresolved_secids = fetch_company_mapping(secids)
    if not company_mapping:
        raise RuntimeError("Не удалось определить ни одного эмитента. Поиск новостей остановлен.")
    like_print_log.info(f"✅ Найдено уникальных эмитентов: {len(company_mapping)}")
    if unresolved_secids:
        like_print_log.info(
            f"⚠️ Не удалось определить эмитента для {len(unresolved_secids)}/{len(secids)} выпусков: "
            + ", ".join(unresolved_secids)
        )
    like_print_log.info("Источники: " + ", ".join(providers))
    if args.use_proxy:
        if proxy_url_from_env(args.proxy_env):
            like_print_log.info(f"🌐 Прокси ВКЛЮЧЁН только для Google News через {args.proxy_env} (адрес скрыт)")
        else:
            like_print_log.info(f"⚠️ --use-proxy задан, но переменная {args.proxy_env} пуста; Google пойдёт напрямую")
    else:
        like_print_log.info("🌐 Прокси ВЫКЛЮЧЕН. Все источники идут напрямую.")

    news_folder = Path(create_news_folder())
    removed = clear_news_folder(news_folder)
    if removed:
        like_print_log.info(f"🧹 Удалено старых файлов новостей/метаданных: {removed}")

    coverage_rows: list[dict] = []
    unavailable_companies = 0

    for index, (company, company_secids) in enumerate(company_mapping.items(), 1):
        like_print_log.info(f"[{index}/{len(company_mapping)}] Поиск новостей: {company}")
        result = aggregate_news(
            company,
            company_secids,
            providers=providers,
            proxy_env=args.proxy_env,
            use_proxy=args.use_proxy,
        )
        if result.items:
            try:
                write_to_file(str(news_folder), company, result.items)
                like_print_log.info(emoji.emojize(f"✍️ Сохранено новостей: {len(result.items)} для {company}"))
            except OSError as exc:
                like_print_log.info(
                    f"   ⚠️ Не удалось записать файл новостей для {company}: {exc}. "
                    "Покрытие источников будет сохранено, обработка продолжается."
                )
        else:
            like_print_log.info(f"ℹ️ Для {company} релевантных записей не найдено")

        if result.successful_providers == 0:
            unavailable_companies += 1

        coverage_rows.append({
            "company": company,
            "secids": company_secids,
            "coverage": result.coverage,
            "item_count": len(result.items),
            "successful_providers": result.successful_providers,
            "enabled_providers": result.enabled_providers,
            "providers": [status.as_dict() for status in result.providers],
        })
        for status in result.providers:
            if status.ok:
                proxy_note = " через proxy" if status.used_proxy else " напрямую"
                like_print_log.info(f"   ✅ {status.provider}: доступен{proxy_note}, релевантных записей {status.item_count}")
            else:
                proxy_note = " через proxy" if status.used_proxy else " напрямую"
                like_print_log.info(f"   ⚠️ {status.provider}: недоступен{proxy_note}: {status.error}")
        if index < len(company_mapping):
            time.sleep(args.delay)

    coverage_path = news_folder / "_coverage_meta.json"
    coverage_path.write_text(
        json.dumps({
            "providers": providers,
            "proxy_enabled": args.use_proxy,
            "companies": coverage_rows,
            "unresolved_secids": unresolved_secids,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    failure_share = unavailable_companies / len(company_mapping)
    if failure_share > args.max_failure_share:
        raise RuntimeError(
            "Этап новостей нельзя считать выполненным: ни один источник не доступен для "
            f"{unavailable_companies} из {len(company_mapping)} эмитентов ({failure_share:.0%}), "
            f"допустимо не более {args.max_failure_share:.0%}."
        )
    like_print_log.info(
        f"🎉 Обработка завершена. Эмитентов с хотя бы одним доступным источником: "
        f"{len(company_mapping) - unavailable_companies}/{len(company_mapping)}. "
        f"Покрытие: {coverage_path}"
    )


if __name__ == "__main__":
    main()
