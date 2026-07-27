# 💰 Расчет оптимального объема покупки облигаций 💰
#
# Читает список облигаций из bonds.xlsx, получает цену и НКД через MOEX ISS,
# равномерно распределяет доступную сумму и сохраняет расчет в Excel.
# Некорректные или неполные котировки пропускаются без остановки всего расчета.

import os
import sys

sys.path.append(f"{os.getcwd()}/src")

from moex_bond_search_and_analysis.app import App
from moex_bond_search_and_analysis.utils import setup_encoding


def main() -> None:
    setup_encoding()
    app = App()
    original_get_bond_price = app.moex.get_bond_price

    def safe_get_bond_price(security_code: str):
        try:
            return original_get_bond_price(security_code)
        except Exception as exc:
            app.log.info(
                f"⚠️ {security_code}: котировка MOEX неполная или некорректная ({exc}). "
                "Бумага пропущена, расчет продолжается."
            )
            return None, None, None

    app.moex.get_bond_price = safe_get_bond_price
    app.calc_purchase_volume()
    print("\nМихаил Шардин https://shardin.name/\n")
    input("Нажмите Enter для выхода...")


if __name__ == "__main__":
    main()
