import pandas as pd

from portfolio_shortlist import annotate_decisions, build_shortlist


def _row(secid, issuer, score, admitted="ДА", missing="—"):
    return {
        "Код ценной бумаги": secid,
        "Полное наименование": secid,
        "Эмитент": issuer,
        "Финальный балл": score,
        "Финальное решение": "Купить" if admitted == "ДА" else "Рассматривать",
        "Допущена в портфель": admitted,
        "Доходность": 18.0,
        "Рейтинг": "AA",
        "Максимальная доля": "до 3–5%",
        "Максимум к покупке, руб.": 500000,
        "Блокеры": "—",
        "Предупреждения": "—",
        "Полнота оценки": "Полная",
        "Недостающие кредитные данные": missing,
    }


def test_tiers_and_confidence_for_missing_financials():
    frame = pd.DataFrame([
        _row("SEC-A", "Issuer A", 88, missing="Финансовая отчётность"),
        _row("SEC-B", "Issuer B", 84),
        _row("SEC-C", "Issuer C", 72),
    ])
    annotated = annotate_decisions(frame)
    assert annotated.loc[0, "Уровень рекомендации"] == "РЕКОМЕНДОВАТЬ, НО ДАННЫЕ НЕПОЛНЫЕ"
    assert annotated.loc[0, "Уверенность решения"] == "Средняя"
    assert annotated.loc[1, "Уровень рекомендации"] == "ДОПУСТИТЬ К ПОКУПКЕ"
    assert annotated.loc[2, "Уровень рекомендации"] == "РАССМАТРИВАТЬ"


def test_shortlist_deduplicates_issuers_and_fills_to_minimum():
    rows = [
        _row("SEC-A1", "Issuer A", 90),
        _row("SEC-A2", "Issuer A", 89),
        _row("SEC-B", "Issuer B", 89),
        _row("SEC-C", "Issuer C", 88),
        _row("SEC-D", "Issuer D", 87),
        _row("SEC-E", "Issuer E", 86),
        _row("SEC-F", "Issuer F", 85),
        _row("SEC-G", "Issuer G", 84),
        _row("SEC-H", "Issuer H", 83),
    ]
    result = build_shortlist(pd.DataFrame(rows), min_size=8, max_size=12)
    secids = [item["secid"] for item in result["shortlist"]]
    issuers = [item["issuer"] for item in result["shortlist"]]
    assert result["strong"] == 6
    assert result["shortlist_count"] == 8
    assert "SEC-A1" in secids
    assert "SEC-A2" not in secids
    assert len(set(issuers)) == 8


def test_shortlist_respects_maximum():
    rows = [_row(f"SEC-{i}", f"Issuer {i}", 90) for i in range(20)]
    result = build_shortlist(pd.DataFrame(rows), min_size=8, max_size=12)
    assert result["shortlist_count"] == 12
