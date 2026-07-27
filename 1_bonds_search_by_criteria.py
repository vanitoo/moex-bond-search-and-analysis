# 🕵️ Поиск ликвидных облигаций Мосбиржи по заданным критериям 🕵️
#
# Этот Python скрипт автоматически выполняет поиск облигаций, соответствующих заданным
# критериям доходности, цены, дюрации и ликвидности, используя API Московской биржи.
# Результаты поиска, включающие информацию об облигациях и лог действий,
# записываются в Excel-файл.
#
# Установка зависимостей перед использованием: pip install requests openpyxl humanize
#
# Автор: Михаил Шардин https://shardin.name/
# Дата создания: 14.02.2025
# Дата изменения: 27.07.2026
# Версия: 1.4
#
# Актуальная версия скрипта всегда здесь: https://github.com/empenoso/moex-bond-search-and-analysis
#

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.append(str(PROJECT_ROOT / "src"))

from cli import start
from moex_bond_search_and_analysis.schemas import SearchByCriteriaConditions


if __name__ == "__main__":
    # --- НАСТРОЙКА КРИТЕРИЕВ ПОИСКА ---
    # Здесь вы можете изменить значения для поиска облигаций.
    # Просто поменяйте цифры или значение "ДА"/"НЕТ" на нужные.
    search_conditions = SearchByCriteriaConditions(
        yield_more=15,          # Доходность ОТ, %
        yield_less=40,          # Доходность ДО, %
        price_more=70,          # Цена ОТ, % от номинала
        price_less=120,         # Цена ДО, % от номинала
        duration_more=3,        # Дюрация ОТ, месяцев
        duration_less=18,       # Дюрация ДО, месяцев
        volume_more=2000,       # Объем сделок в каждый из последних 15 дней должен быть больше, шт.
        bond_volume_more=60000, # Совокупный объем сделок за 15 дней должен быть больше, шт.
        offer_yes_no="ДА"       # Учитывать только облигации с известными купонами до погашения ("ДА" или "НЕТ")
    )
    # --- КОНЕЦ НАСТРОЙКИ ---

    start(1, search_conditions=search_conditions)
