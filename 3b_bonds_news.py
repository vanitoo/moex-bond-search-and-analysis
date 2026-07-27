from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

from pipeline_common import dated_name, latest, normalize

DANGER = {
    "Дефолт/просрочка": ("дефолт", "просроч", "не выплат", "невыплат"),
    "Банкротство": ("банкрот", "несостоятельн", "конкурсное производство"),
    "Снижение рейтинга": ("снизил рейтинг", "понизил рейтинг", "негативный прогноз", "рейтинг отозван"),
    "Финансовое ухудшение": ("чистый убыток", "выручка сниз", "долговая нагрузка вырос", "нарушение ковенант"),
}
POSITIVE = {
    "Повышение рейтинга": ("повысил рейтинг", "рейтинг повышен", "позитивный прогноз"),
    "Исполнение обязательств": ("выплатил купон", "погасил облигац", "исполнил обязательства"),
}


def source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for pattern in ("news/**/*.txt", "news/**/*.md", "news/**/*.json", "новости/**/*.txt", "новости/**/*.md", "новости/**/*.json"):
        files.extend(root.glob(pattern))
    return [p for p in files if p.is_file() and p.stat().st_size <= 5_000_000]


def match_text(secid: str, name: str, files: list[Path]) -> tuple[str, list[str]]:
    tokens = {normalize(secid)}
    tokens.update(w for w in re.findall(r"[a-zа-я0-9]+", normalize(name)) if len(w) >= 5)
    chunks, matched = [], []
    for path in files:
        haystack = normalize(path.name + " " + str(path.parent))
        if not any(token and token in haystack for token in list(tokens)[:8]):
            continue
        try:
            chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
            matched.append(str(path))
        except OSError:
            pass
    return "\n".join(chunks), matched


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input")
    parser.add_argument("--news-dir", default=".")
    parser.add_argument("--output")
    args = parser.parse_args()
    source = Path(args.input) if args.input else latest(Path("."), "bond_search_*.xlsx")
    df = pd.read_excel(source, sheet_name="Результаты поиска")
    files = source_files(Path(args.news_dir))
    result = []
    for _, row in df.iterrows():
        secid = str(row.get("Код ценной бумаги") or "").strip()
        if not secid:
            continue
        name = str(row.get("Полное наименование") or secid)
        text, matched = match_text(secid, name, files)
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
    pd.DataFrame(result).to_excel(output, sheet_name="Новости", index=False)
    print(output)


if __name__ == "__main__":
    main()
