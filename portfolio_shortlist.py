from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


STRONG_SCORE = 86
ADMITTED_SCORE = 82
MIN_SHORTLIST = 8
MAX_SHORTLIST = 12

RATING_ORDER = [
    "D", "C", "CC", "CCC", "B-", "B", "B+", "BB-", "BB", "BB+",
    "BBB-", "BBB", "BBB+", "A-", "A", "A+", "AA-", "AA", "AA+", "AAA",
]


def _text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _score(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return -1.0


def _rating_rank(value: Any) -> int:
    raw = _text(value).upper().replace("(RU)", "").replace("RU", "")
    cleaned = "".join(ch for ch in raw if ch.isalpha() or ch in "+-")
    for item in sorted(RATING_ORDER, key=len, reverse=True):
        if item in cleaned:
            return RATING_ORDER.index(item)
    return -1


def _confidence_rank(value: Any) -> int:
    text = _text(value).lower()
    if "высок" in text:
        return 2
    if "сред" in text:
        return 1
    return 0


def _issuer_key(row: pd.Series) -> str:
    issuer = _text(row.get("Эмитент"))
    if issuer:
        return issuer.casefold()
    # Без эмитента не склеиваем разные выпуски эвристикой по названию:
    # безопаснее считать такой SECID отдельным эмитентом.
    return f"secid:{_text(row.get('Код ценной бумаги')).upper()}"


def recommendation_tier(row: pd.Series) -> str:
    score = _score(row.get("Финальный балл"))
    decision = _text(row.get("Финальное решение")).lower()
    blockers = _text(row.get("Блокеры"))
    credit_missing = _text(row.get("Недостающие кредитные данные")).lower().replace("ё", "е")

    if "не покупать" in decision or (blockers and blockers != "—") or score < 50:
        return "НЕ ПОКУПАТЬ"
    if score >= STRONG_SCORE:
        if "финансовая отчетность" in credit_missing:
            return "РЕКОМЕНДОВАТЬ, НО ДАННЫЕ НЕПОЛНЫЕ"
        return "РЕКОМЕНДОВАТЬ"
    if score >= ADMITTED_SCORE:
        return "ДОПУСТИТЬ К ПОКУПКЕ"
    if score >= 68:
        return "РАССМАТРИВАТЬ"
    return "РУЧНАЯ ПРОВЕРКА"


def decision_confidence(row: pd.Series) -> str:
    credit_missing = _text(row.get("Недостающие кредитные данные")).lower().replace("ё", "е")
    completeness = _text(row.get("Полнота оценки")).lower()
    if "кредитный рейтинг" in credit_missing or "credit" in completeness:
        return "Низкая"
    if "финансовая отчетность" in credit_missing:
        return "Средняя"
    if "неполная" in completeness:
        return "Средняя"
    return "Высокая"


def annotate_decisions(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["Уровень рекомендации"] = [recommendation_tier(row) for _, row in result.iterrows()]
    result["Уверенность решения"] = [decision_confidence(row) for _, row in result.iterrows()]
    return result


def _rank_frame(frame: pd.DataFrame) -> pd.DataFrame:
    ranked = frame.copy()
    ranked["_score"] = ranked["Финальный балл"].map(_score)
    ranked["_confidence"] = ranked.get(
        "Уверенность решения", pd.Series("", index=ranked.index)
    ).map(_confidence_rank)
    ranked["_rating"] = ranked.get(
        "Рейтинг", pd.Series("", index=ranked.index)
    ).map(_rating_rank)
    ranked["_liquidity"] = pd.to_numeric(
        ranked.get("Максимум к покупке, руб.", pd.Series(0, index=ranked.index)),
        errors="coerce",
    ).fillna(0)
    ranked["_yield"] = pd.to_numeric(
        ranked.get("Доходность", pd.Series(0, index=ranked.index)),
        errors="coerce",
    ).fillna(0)
    return ranked.sort_values(
        ["_score", "_confidence", "_rating", "_liquidity", "_yield"],
        ascending=[False, False, False, False, False],
    )


def _unique_issuers(frame: pd.DataFrame, limit: int, used: set[str] | None = None) -> list[pd.Series]:
    used = used if used is not None else set()
    selected: list[pd.Series] = []
    for _, row in _rank_frame(frame).iterrows():
        key = _issuer_key(row)
        if key in used:
            continue
        used.add(key)
        selected.append(row)
        if len(selected) >= limit:
            break
    return selected


def build_shortlist(
    decisions: pd.DataFrame,
    *,
    min_size: int = MIN_SHORTLIST,
    max_size: int = MAX_SHORTLIST,
    strong_score: int = STRONG_SCORE,
    admitted_score: int = ADMITTED_SCORE,
) -> dict[str, Any]:
    if decisions.empty:
        return {
            "analyzed": 0,
            "admitted": 0,
            "strong": 0,
            "shortlist_count": 0,
            "shortlist": [],
            "strong_candidates": [],
        }

    frame = annotate_decisions(decisions)
    admitted_mask = (
        frame.get("Допущена в портфель", pd.Series("", index=frame.index))
        .astype(str).str.strip().str.upper().eq("ДА")
    )
    scores = pd.to_numeric(frame["Финальный балл"], errors="coerce").fillna(-1)
    admitted = frame[admitted_mask & (scores >= admitted_score)].copy()
    strong = admitted[scores.loc[admitted.index] >= strong_score].copy()

    used: set[str] = set()
    selected = _unique_issuers(strong, max_size, used)

    if len(selected) < min_size:
        strong_ids = {_text(row.get("Код ценной бумаги")) for row in selected}
        fallback = admitted[
            ~admitted["Код ценной бумаги"].astype(str).isin(strong_ids)
        ]
        selected.extend(
            _unique_issuers(fallback, min(max_size - len(selected), min_size - len(selected)), used)
        )

    def nullable_float(value: Any) -> float | None:
        if value is None or pd.isna(value):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def clean_row(row: pd.Series) -> dict[str, Any]:
        return {
            "secid": _text(row.get("Код ценной бумаги")),
            "name": _text(row.get("Полное наименование")),
            "issuer": _text(row.get("Эмитент")),
            "score": _score(row.get("Финальный балл")),
            "yield": nullable_float(row.get("Доходность")),
            "rating": _text(row.get("Рейтинг")),
            "tier": _text(row.get("Уровень рекомендации")),
            "confidence": _text(row.get("Уверенность решения")),
            "max_share": _text(row.get("Максимальная доля")),
            "max_purchase_rub": nullable_float(row.get("Максимум к покупке, руб.")),
            "warnings": _text(row.get("Предупреждения")),
            "credit_missing": _text(row.get("Недостающие кредитные данные")),
        }

    strong_rows = [clean_row(row) for _, row in _rank_frame(strong).iterrows()]
    shortlist_rows = [clean_row(row) for row in selected]

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "analyzed": int(len(frame)),
        "admitted": int(len(admitted)),
        "strong": int(len(strong)),
        "unique_strong_issuers": len({_issuer_key(row) for _, row in strong.iterrows()}),
        "shortlist_count": len(shortlist_rows),
        "thresholds": {
            "strong_score": strong_score,
            "admitted_score": admitted_score,
            "min_shortlist": min_size,
            "max_shortlist": max_size,
        },
        "shortlist": shortlist_rows,
        "strong_candidates": strong_rows,
    }


def write_shortlist(decisions: pd.DataFrame, output_dir: Path, stamp: str) -> dict[str, Any]:
    payload = build_shortlist(decisions)
    output_dir.mkdir(parents=True, exist_ok=True)

    dated_json = output_dir / f"bond_shortlist_{stamp}.json"
    dated_xlsx = output_dir / f"bond_shortlist_{stamp}.xlsx"
    stable = output_dir / "decisions" / "portfolio_shortlist.json"
    stable.parent.mkdir(parents=True, exist_ok=True)

    text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
    dated_json.write_text(text, encoding="utf-8")
    stable.write_text(text, encoding="utf-8")

    with pd.ExcelWriter(dated_xlsx, engine="openpyxl") as writer:
        pd.DataFrame(payload["shortlist"]).to_excel(writer, sheet_name="Shortlist", index=False)
        pd.DataFrame(payload["strong_candidates"]).to_excel(writer, sheet_name="Сильные кандидаты", index=False)
        pd.DataFrame([{
            "Проанализировано": payload["analyzed"],
            "Допущено": payload["admitted"],
            "Сильных кандидатов": payload["strong"],
            "Уникальных эмитентов среди сильных": payload["unique_strong_issuers"],
            "В shortlist": payload["shortlist_count"],
        }]).to_excel(writer, sheet_name="Статистика", index=False)

    payload["json_path"] = str(dated_json)
    payload["xlsx_path"] = str(dated_xlsx)
    payload["stable_path"] = str(stable)
    return payload


def load_shortlist_secids(run_dir: Path) -> list[str]:
    path = run_dir / "decisions" / "portfolio_shortlist.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [
        str(item.get("secid") or "").strip()
        for item in payload.get("shortlist", [])
        if str(item.get("secid") or "").strip()
    ]
