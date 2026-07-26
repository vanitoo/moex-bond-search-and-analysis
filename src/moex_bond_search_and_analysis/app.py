from datetime import datetime
import re
import threading
import time
from typing import Any

import emoji
import pandas as pd

from moex_bond_search_and_analysis.moex import MOEX
from moex_bond_search_and_analysis.news import google_search, write_to_file
from moex_bond_search_and_analysis.plugins.excel import ExcelSource
from moex_bond_search_and_analysis.plugins.html_report import (
    HtmlLiveSearchReport,
    HtmlSearchReport,
)
from moex_bond_search_and_analysis.logger import like_print_log
from moex_bond_search_and_analysis.schemas import SearchByCriteriaConditions
from moex_bond_search_and_analysis.utils import (
    create_news_folder,
    measure_method_duration,
)


class App:
    def __init__(self) -> None:
        self.log = like_print_log
        self.moex = MOEX(log=self.log)

    @staticmethod
    def _extract_live_progress(messages: list[str]) -> tuple[int, int, int, int, str]:
        """Извлекает прогресс из уже существующих сообщений лога, не меняя поисковый скрипт."""
        processed = 0
        current = 0
        current_total = 0
        found = 0
        last_message = messages[-1] if messages else "Подготовка к поиску..."

        for message in messages:
            row_match = re.search(r"Строка\s+(\d+)\s+из\s+(\d+)", message)
            if row_match:
                row_number = int(row_match.group(1))
                row_total = int(row_match.group(2))
                # При переходе к новой группе предыдущая группа уже полностью обработана.
                if row_total != current_total and current_total:
                    processed += current_total
                current = row_number
                current_total = row_total

            result_match = re.search(r"Результат №\s*(\d+)", message)
            if result_match:
                found = max(found, int(result_match.group(1)))

        processed += current
        return processed, current, current_total, found, last_message

    def _live_report_worker(
        self,
        report: HtmlLiveSearchReport,
        conditions: SearchByCriteriaConditions,
        stop_event: threading.Event,
    ) -> None:
        while not stop_event.wait(20):
            messages = list(self.log.messages)
            processed, current, current_total, found, last_message = self._extract_live_progress(messages)
            report.write(
                conditions=conditions,
                processed=processed,
                current=current,
                current_total=current_total,
                found=found,
                last_message=last_message,
            )

    @measure_method_duration
    def search_by_criteria(self, search_conditions: SearchByCriteriaConditions | None = None):
        if search_conditions is None:
            self.log.info("Критерии поиска не были переданы, используются значения по умолчанию.")
            search_conditions = SearchByCriteriaConditions()

        live_report = HtmlLiveSearchReport(filename="bond_search_live.html")
        live_report.write(conditions=search_conditions)
        self.log.info("🌐 Живой отчёт создан: bond_search_live.html")

        stop_event = threading.Event()
        live_thread = threading.Thread(
            target=self._live_report_worker,
            args=(live_report, search_conditions, stop_event),
            daemon=True,
        )
        live_thread.start()

        try:
            moex_search_bonds_result = self.moex.search_bonds(conditions=search_conditions)
        finally:
            stop_event.set()
            live_thread.join(timeout=2)

        bonds = moex_search_bonds_result or []
        report_date = datetime.now().strftime("%Y-%m-%d")
        final_html_filename = f"bond_search_{report_date}.html"

        if bonds:
            output_source = ExcelSource(filename=f"bond_search_{report_date}.xlsx")
            output_source.write_search_by_criteria(
                bonds, search_conditions, self.moex.log
            )
            self.log.info(
                f"\n💾 Результаты записаны в Excel файл: {output_source.filename}"
            )

        html_report = HtmlSearchReport(filename=final_html_filename)
        html_report.write(bonds, search_conditions)
        self.log.info(f"🌐 Финальный HTML-отчёт сформирован: {html_report.filename}")

        messages = list(self.log.messages)
        processed, current, current_total, found, last_message = self._extract_live_progress(messages)
        live_report.write(
            conditions=search_conditions,
            processed=processed,
            current=current,
            current_total=current_total,
            found=len(bonds) if bonds else found,
            last_message=last_message,
            completed=True,
            final_filename=final_html_filename,
        )
        self.log.info("✅ Живой отчёт обновлён: поиск завершён.")

    @measure_method_duration
    def search_coupons(self):
        bounds_source = ExcelSource(filename="bonds.xlsx")
        bond_sheets = bounds_source.load_bonds()
        data_iterator = bond_sheets.data.iter_rows(
            min_row=2, max_row=bond_sheets.data.max_row, values_only=True
        )
        bonds = [row for row in data_iterator if row[0] and row[1]]
        self.log.info(f"Считано {len(bonds)} облигаций для обработки.")
        cash_flow = self.moex.process_bonds(bonds=bonds)
        bounds_source.write_bonds(
            sheets=bond_sheets, cache_flow=cash_flow, log=self.log
        )

    @measure_method_duration
    def search_news(self):
        delay_between_calls = 3
        self.log.info("📂 Загружаем данные из Excel...")
        df = pd.read_excel("bonds.xlsx", sheet_name="Исходные данные")
        self.log.info(f"✅ Найдено {len(df)} записей")
        company_names = self.moex.fetch_company_names(df)
        news_folder_path = create_news_folder()
        for company in company_names:
            news = google_search(company, self.log)
            write_to_file(news_folder_path, company, news)
            self.log.info(
                emoji.emojize(f"✍️ Сохранено новостей: {len(news)} для {company}")
            )
            time.sleep(delay_between_calls)

        self.log.info("🎉 Обработка завершена!")

    @measure_method_duration
    def calc_purchase_volume(self, available_money: int = 700_000):
        self.log.info(f"💵 Доступная сумма: {available_money} руб.")
        results = self._calculate_bonds_distribution(available_money)
        if results:
            total_spent = sum(r["money_spent"] for r in results)
            self.log.info("\n📊 Итоговое распределение:")
            self.log.info(f"Всего потрачено: {total_spent:.2f} руб.")
            self.log.info(f"Остаток: {(available_money - total_spent):.2f} руб.")

    def _calculate_bonds_distribution(
        self, available_money: int
    ) -> list[dict[str, Any]]:
        """Расчет равномерного распределения средств между облигациями."""
        self.log.info("📊 Чтение списка облигаций из файла Excel...")
        df = pd.read_excel("bonds.xlsx", sheet_name="Исходные данные", usecols="A")
        bonds_list = df.iloc[:, 0].tolist()

        valid_bonds = []
        for bond in bonds_list:
            self.log.info(f"\n🔍 Получение данных для облигации {bond}...")
            price, nkd, date = self.moex.get_bond_price(bond)

            if price is not None and nkd is not None:
                valid_bonds.append(
                    {
                        "bond": bond,
                        "price": price,
                        "nkd": nkd,
                        "total_cost": price + nkd,
                        "price_date": date,
                    }
                )

        if not valid_bonds:
            self.log.info("❌ Нет доступных облигаций для покупки")
            return []

        num_bonds = len(valid_bonds)
        money_per_bond = available_money / num_bonds
        self.log.info(
            f"\n💰 Распределение {available_money} руб. между {num_bonds} облигациями"
        )
        self.log.info(f"💵 Сумма на каждую облигацию: {money_per_bond:.2f} руб.")

        results = []
        for bond_info in valid_bonds:
            num_bonds = int(money_per_bond // bond_info["total_cost"])
            actual_money = num_bonds * bond_info["total_cost"]

            results.append(
                {
                    "bond": bond_info["bond"],
                    "quantity": num_bonds,
                    "price": bond_info["price"],
                    "nkd": bond_info["nkd"],
                    "total_cost": bond_info["total_cost"],
                    "money_spent": actual_money,
                    "price_date": bond_info["price_date"],
                }
            )

            self.log.info(f"\n📈 Облигация {bond_info['bond']}:")
            self.log.info(f"   Данные актуальны на: {bond_info['price_date']}")
            self.log.info(f"   Цена: {bond_info['price']:.2f} руб.")
            self.log.info(f"   НКД: {bond_info['nkd']:.2f} руб.")
            self.log.info(
                f"   Полная стоимость одной облигации: {bond_info['total_cost']:.2f} руб."
            )
            self.log.info(f"   Количество к покупке: {num_bonds} шт.")
            self.log.info(f"   Сумма к расходу: {actual_money:.2f} руб.")

        results_df = pd.DataFrame(
            {
                "Код ценной бумаги": [r["bond"] for r in results],
                "Данные актуальны на": [r["price_date"] for r in results],
                "Цена, руб.": [r["price"] for r in results],
                "НКД, руб.": [r["nkd"] for r in results],
                "Полная стоимость одной облигации, руб.": [
                    r["total_cost"] for r in results
                ],
                "Количество к покупке, шт.": [r["quantity"] for r in results],
                "Сумма к расходу, руб.": [r["money_spent"] for r in results],
            }
        )

        self.log.info("\n📝 Запись результатов в Excel...")
        results_df.to_excel(
            "bonds_calculation purchase volume.xlsx", sheet_name="Расчет", index=False
        )
        self.log.info(
            "✅ Результаты сохранены в файл 'bonds_calculation purchase volume.xlsx'"
        )

        return results
