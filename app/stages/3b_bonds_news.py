from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd

from pipeline_common import clean_secid_rows, dated_name, latest, normalize

DANGER = {
    "Дефолт/просрочка": ("дефолт", "просроч", "не выплат", "невыплат", "технический дефолт"),
    "Банкротство": ("банкрот", "несостоятельн", "конкурсное производство", "наблюдение введено"),
    "Снижение рейтинга": ("снизил рейтинг", "понизил рейтинг", "негативный прогноз", "рейтинг отозван"),
    "Финансовое ухудшение": ("чистый убыток", "выручка сниз", "долговая нагрузка вырос", "нарушение ковенант"),
}
POSITIVE = {
    "Повышение рейтинга": ("повысил рейтинг", "рейтинг повышен", "позитивный прогноз"),
    "Исполнение обязательств": ("выплатил купон", "погасил облигац", "исполнил обязательства"),
}

RATING_EVENT_COLUMNS = [
    "Эмитент", "Код ценной бумаги", "Агентство", "Действие", "Текущий рейтинг",
    "Предыдущий рейтинг", "Прогноз", "Дата события", "Объект рейтинга", "Источник", "Заголовок",
]


def decode_escaped_unicode(value: str) -> str:
    return re.sub(r"#U([0-9A-Fa-f]{4,6})", lambda match: chr(int(match.group(1), 16)), value)


def source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for pattern in (
        "news*/**/*.txt", "news*/**/*.md", "новости*/**/*.txt", "новости*/**/*.md",
        "**/news_*.txt", "**/news_*.md",
    ):
        files.extend(root.glob(pattern))
    unique = {p.resolve(): p for p in files if p.is_file() and p.stat().st_size <= 5_000_000 and not p.name.startswith("_")}
    return list(unique.values())


def meaningful_tokens(secid: str, *names: str) -> set[str]:
    tokens = {normalize(secid)}
    for name in names:
        decoded = decode_escaped_unicode(str(name or ""))
        words = re.findall(r"[a-zа-я0-9]+", normalize(decoded))
        tokens.update(word for word in words if len(word) >= 4 and word not in {"пао", "ао", "ооо", "облигации", "выпуск"})
    return tokens


def match_text(secid: str, names: list[str], files: list[Path]) -> tuple[str, list[str]]:
    tokens = meaningful_tokens(secid, *names)
    chunks: list[str] = []
    matched: list[str] = []
    for path in files:
        decoded_path = decode_escaped_unicode(str(path))
        path_haystack = normalize(decoded_path)
        filename_match = any(token and token in path_haystack for token in tokens)
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        content_haystack = normalize(decode_escaped_unicode(content[:100_000]))
        content_match = any(token and token in content_haystack for token in tokens)
        if not filename_match and not content_match:
            continue
        chunks.append(content)
        matched.append(str(path))
    return "\n".join(chunks), matched


def _latest_json(root: Path, filename: str) -> Path | None:
    candidates = list(root.glob(f"news*/**/{filename}")) + list(root.glob(f"новости*/**/{filename}"))
    return max(candidates, key=lambda item: item.stat().st_mtime) if candidates else None


def load_coverage(root: Path) -> dict[str, dict]:
    path = _latest_json(root, "_coverage_meta.json")
    if path is None:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    result: dict[str, dict] = {}
    for item in payload.get("companies", []):
        if not isinstance(item, dict):
            continue
        for secid in item.get("secids", []):
            result[str(secid).strip().upper()] = item
    return result


def load_rating_events(root: Path) -> tuple[list[dict], dict[str, list[dict]]]:
    path = _latest_json(root, "_rating_events.json")
    if path is None:
        return [], {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [], {}
    events = [item for item in payload.get("events", []) if isinstance(item, dict)]
    by_secid: dict[str, list[dict]] = {}
    for event in events:
        for secid in event.get("secids", []):
            by_secid.setdefault(str(secid).strip().upper(), []).append(event)
    return events, by_secid


def coverage_description(meta: dict | None) -> str:
    if not meta:
        return "NO_DATA"
    coverage = str(meta.get("coverage") or "NO_DATA").upper()
    providers = meta.get("providers") or []
    ok = [str(item.get("provider")) for item in providers if isinstance(item, dict) and item.get("ok")]
    failed = [str(item.get("provider")) for item in providers if isinstance(item, dict) and not item.get("ok")]
    parts = [coverage]
    if ok:
        parts.append("доступны: " + ", ".join(ok))
    if failed:
        parts.append("недоступны: " + ", ".join(failed))
    if int(meta.get("item_count") or 0) == 0 and ok:
        parts.append("релевантных новостей не найдено")
    return "; ".join(parts)


def rating_summary(events: list[dict]) -> tuple[str, str, str, str, str]:
    if not events:
        return "—", "—", "—", "—", "—"
    agencies = "; ".join(dict.fromkeys(str(x.get("agency") or "") for x in events if x.get("agency"))) or "—"
    actions = "; ".join(dict.fromkeys(str(x.get("action") or "") for x in events if x.get("action"))) or "—"
    ratings = "; ".join(dict.fromkeys(str(x.get("current_rating") or "") for x in events if x.get("current_rating"))) or "—"
    forecasts = "; ".join(dict.fromkeys(str(x.get("forecast") or "") for x in events if x.get("forecast"))) or "—"
    dates = sorted((str(x.get("event_date") or "") for x in events if x.get("event_date")), reverse=True)
    return agencies, actions, ratings, forecasts, dates[0] if dates else "—"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input")
    parser.add_argument("--news-dir", default=".")
    parser.add_argument("--output")
    args = parser.parse_args()
    source = Path(args.input) if args.input else latest(Path("."), "bond_search_*.xlsx")
    df = clean_secid_rows(pd.read_excel(source, sheet_name="Результаты поиска"))
    news_root = Path(args.news_dir)
    files = source_files(news_root)
    coverage = load_coverage(news_root)
    rating_events, rating_by_secid = load_rating_events(news_root)
    result = []
    for _, row in df.iterrows():
        secid = str(row.get("Код ценной бумаги") or "").strip().upper()
        names = [
            str(row.get("Полное наименование") or ""),
            str(row.get("Краткое наименование") or ""),
            str(row.get("Эмитент") or ""),
            str(row.get("Наименование эмитента") or ""),
        ]
        text, matched = match_text(secid, names, files)
        normalized = normalize(text)
        dangers = [label for label, markers in DANGER.items() if any(marker in normalized for marker in markers)]
        positives = [label for label, markers in POSITIVE.items() if any(marker in normalized for marker in markers)]
        meta = coverage.get(secid)
        events = rating_by_secid.get(secid, [])
        agencies, actions, ratings, forecasts, event_date = rating_summary(events)
        if any(str(event.get("action")) in {"ПОНИЖЕН", "ОТОЗВАН"} for event in events):
            if "Снижение рейтинга" not in dangers:
                dangers.append("Снижение рейтинга")
        if any(str(event.get("action")) == "ПОВЫШЕН" for event in events):
            if "Повышение рейтинга" not in positives:
                positives.append("Повышение рейтинга")
        result.append({
            "Код ценной бумаги": secid,
            "Новостных файлов": len(matched),
            "Негативные события": "; ".join(dangers) or "—",
            "Позитивные события": "; ".join(positives) or "—",
            "Критический новостной стоп": "ДА" if any(x in dangers for x in ("Дефолт/просрочка", "Банкротство")) else "НЕТ",
            "Источники новостей": "; ".join(matched) or "—",
            "Полнота новостей": coverage_description(meta),
            "Провайдеров доступно": None if not meta else meta.get("successful_providers"),
            "Провайдеров включено": None if not meta else meta.get("enabled_providers"),
            "Рейтинговых событий": len(events),
            "Рейтинговые агентства": agencies,
            "Действия рейтинга": actions,
            "Рейтинги из новостей": ratings,
            "Прогнозы рейтинга": forecasts,
            "Последнее рейтинговое событие": event_date,
        })
    output = Path(args.output or dated_name("bond_news", "xlsx"))
    pd.DataFrame(result).drop_duplicates(subset=["Код ценной бумаги"]).to_excel(output, sheet_name="Новости", index=False)

    rating_output = Path(dated_name("bond_rating_events", "xlsx"))
    rating_rows: list[dict] = []
    for event in rating_events:
        secids = event.get("secids") or [""]
        for secid in secids:
            rating_rows.append({
                "Эмитент": event.get("company"),
                "Код ценной бумаги": secid,
                "Агентство": event.get("agency"),
                "Действие": event.get("action"),
                "Текущий рейтинг": event.get("current_rating"),
                "Предыдущий рейтинг": event.get("previous_rating"),
                "Прогноз": event.get("forecast"),
                "Дата события": event.get("event_date"),
                "Объект рейтинга": event.get("object_type"),
                "Источник": event.get("source_url"),
                "Заголовок": event.get("title"),
            })
    pd.DataFrame(rating_rows, columns=RATING_EVENT_COLUMNS).to_excel(rating_output, sheet_name="Рейтинговые события", index=False)

    print(f"Найдено новостных файлов: {len(files)}")
    print(f"Метаданные покрытия для выпусков: {len(coverage)}")
    print(f"Структурированных рейтинговых событий: {len(rating_events)}")
    print(output)
    print(rating_output)


if __name__ == "__main__":
    main()
