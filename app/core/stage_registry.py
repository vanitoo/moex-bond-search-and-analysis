from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModuleSpec:
    """Contract used by result collection and module tracing."""

    key: str
    script: str
    output_pattern: str | None
    sheet: str | int = 0


@dataclass(frozen=True)
class PipelineStage:
    """One logical stage of the full market-analysis pipeline."""

    number: int
    key: str
    script: str
    description: str
    output_pattern: str | None
    sheet: str | int = 0
    alternatives: tuple[str, ...] = ()


PIPELINE_STAGES: tuple[PipelineStage, ...] = (
    PipelineStage(
        1,
        "market_search",
        "1_bonds_search_by_criteria.py",
        "V1: старый последовательный сканер рынка MOEX. Оставлен как контрольный и резервный вариант.",
        "bond_search_*.xlsx",
        "Результаты поиска",
        ("1_bonds_market_scanner_v2.py",),
    ),
    PipelineStage(
        2,
        "cashflow",
        "2_bonds_cashflow.py",
        "Получает и анализирует будущие купоны, амортизации, оферты и полноту денежных потоков.",
        "bond_cashflow_*.xlsx",
        0,
    ),
    PipelineStage(
        3,
        "news_search",
        "3a_bonds_news_search.py",
        "Определяет эмитентов найденных выпусков и скачивает свежие новости в локальную папку.",
        None,
        0,
    ),
    PipelineStage(
        4,
        "news",
        "3b_bonds_news.py",
        "Анализирует новости, выявляет негативные и позитивные события и формирует новостные стоп-факторы.",
        "bond_news_*.xlsx",
        "Новости",
    ),
    PipelineStage(
        5,
        "liquidity",
        "4b_bonds_purchase_volume.py",
        "Проверяет цену, стакан, оборот и ликвидность, затем рассчитывает допустимый объём покупки.",
        "bond_purchase_volume_*.xlsx",
        "Объем покупки",
    ),
    PipelineStage(
        6,
        "ofz_spread",
        "4c_bonds_ofz_spread.py",
        "Сравнивает доходность облигации с сопоставимой ОФЗ и рассчитывает премию за риск.",
        "bond_ofz_spread_*.xlsx",
        0,
    ),
    PipelineStage(
        7,
        "analysis",
        "5_bonds_analysis.py",
        "Объединяет результаты доступных модулей и выполняет первичную рыночную оценку облигаций.",
        "bond_analysis_*.xlsx",
        0,
    ),
    PipelineStage(
        8,
        "deep_analysis",
        "6_bonds_deep_analysis.py",
        "Выполняет углублённый скоринг с учётом структуры выпуска, новостей, ликвидности и полноты данных.",
        "bond_deep_analysis_*.xlsx",
        0,
    ),
    PipelineStage(
        9,
        "credit",
        "7_bonds_credit_analysis.py",
        "Проверяет рейтинги и финансовые показатели эмитента и оценивает кредитный риск.",
        "bond_credit_analysis_*.xlsx",
        "Кредитный анализ",
    ),
    PipelineStage(
        10,
        "decision",
        "8_bonds_decision.py",
        "Формирует итоговое решение по каждой облигации на основании включённых модулей и доступных данных.",
        "bond_decisions_*.xlsx",
        "Решения",
    ),
)


def _build_module_specs() -> tuple[ModuleSpec, ...]:
    specs: list[ModuleSpec] = []
    for stage in PIPELINE_STAGES:
        specs.append(ModuleSpec(stage.key, stage.script, stage.output_pattern, stage.sheet))
        for alternative in stage.alternatives:
            specs.append(ModuleSpec(stage.key, alternative, stage.output_pattern, stage.sheet))
    return tuple(specs)


MODULES: tuple[ModuleSpec, ...] = _build_module_specs()
BY_SCRIPT: dict[str, ModuleSpec] = {item.script: item for item in MODULES}
PIPELINE_STAGE_SCRIPTS: tuple[str, ...] = tuple(stage.script for stage in PIPELINE_STAGES)
MODULE_DESCRIPTIONS: dict[str, str] = {
    stage.script: stage.description for stage in PIPELINE_STAGES
}

# Alternative implementations share the logical stage description unless they need
# a more specific one.
MODULE_DESCRIPTIONS["1_bonds_market_scanner_v2.py"] = (
    "V2: пакетная загрузка рынка, локальная фильтрация, дисковый кэш и ограниченный параллелизм."
)


def stage_by_number(number: int) -> PipelineStage:
    if number < 1 or number > len(PIPELINE_STAGES):
        raise IndexError(f"Неизвестный номер этапа: {number}")
    return PIPELINE_STAGES[number - 1]


def stage_by_key(key: str) -> PipelineStage:
    normalized = str(key).strip()
    for stage in PIPELINE_STAGES:
        if stage.key == normalized:
            return stage
    raise KeyError(f"Неизвестный модуль: {key}")


def resolve_market_script(version: str) -> str:
    normalized = str(version or "v1").strip().lower()
    if normalized == "v1":
        return stage_by_key("market_search").script
    if normalized == "v2":
        return "1_bonds_market_scanner_v2.py"
    raise ValueError("market_search.version должен быть v1 или v2")


GUI_MODULES: tuple[tuple[str, str, str], ...] = (
    ("market_search", "1. Поиск облигаций", "Общие критерии для V1 и V2; выбирается только способ сканирования"),
    ("cashflow", "2. Денежные потоки", "Купоны, оферты и погашения"),
    ("news_search", "3а. Поиск новостей", "Скачивание и обновление новостей"),
    ("news", "3б. Анализ новостей", "Риски и стоп-факторы"),
    ("liquidity", "4б. Ликвидность", "Стакан, оборот и доступный объём"),
    ("ofz_spread", "4в. Спред к ОФЗ", "Премия к сопоставимой ОФЗ"),
    ("analysis", "5. Первичный анализ", "Рыночная оценка"),
    ("deep_analysis", "6. Глубокий анализ", "Второй слой оценки"),
    ("credit", "7. Кредитный анализ", "Рейтинги и финансовые показатели"),
    ("decision", "8. Финальное решение", "Работает при любом наборе включённых модулей"),
)
