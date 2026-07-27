# 💰 Расчет оптимального объема покупки облигаций 💰
#
# Читает список облигаций из bonds.xlsx, получает цену и НКД через MOEX ISS,
# равномерно распределяет доступную сумму и сохраняет расчет в Excel.
# Некорректные или неполные котировки пропускаются без остановки всего расчета.

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

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


if __name__ == "__main__":
    main()
