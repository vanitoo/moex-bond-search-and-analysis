from __future__ import annotations

import argparse
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


def decode_escaped_unicode(value: str) -> str:
    """Декодирует имена вида #U0410#U043a..., создаваемые некоторыми загрузчиками."""
    return re.sub(
        r"#U([0-9A-Fa-f]{4,6})",
        lambda match: chr(int(match.group(1), 16)),
        value,
    )


def source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for pattern in (
        "news/**/*.txt", "news/**/*.md", "news/**/*.json",
        "новости/**/*.txt", "новости/**/*.md", "новости/**/*.json",
        "**/news_*.txt", "**/news_*.md", "**/news_*.json",
    ):
        files.extend(root.glob(pattern))
    unique = {p.resolve(): p for p in files if p.is_file() and p.stat().st_size <= 5_000_000}
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input")
    parser.add_argument("--news-dir", default=".")
    parser.add_argument("--output")
    args = parser.parse_args()
    source = Path(args.input) if args.input else latest(Path("."), "bond_search_*.xlsx")
    df = clean_secid_rows(pd.read_excel(source, sheet_name="Результаты поиска"))
    files = source_files(Path(args.news_dir))
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
        result.append({
            "Код ценной бумаги": secid,
            "Новостных файлов": len(matched),
            "Негативные события": "; ".join(dangers) or "—",
            "Позитивные события": "; ".join(positives) or "—",
            "Критический новостной стоп": "ДА" if any(x in dangers for x in ("Дефолт/просрочка", "Банкротство")) else "НЕТ",
            "Источники новостей": "; ".join(matched) or "—",
            "Полнота новостей": "Нет данных" if not matched else "Есть локальные источники",
        })
    output = Path(args.output or dated_name("bond_news", "xlsx"))
    pd.DataFrame(result).drop_duplicates(subset=["Код ценной бумаги"]).to_excel(output, sheet_name="Новости", index=False)
    print(f"Найдено новостных файлов: {len(files)}")
    print(output)


if __name__ == "__main__":
    main()
