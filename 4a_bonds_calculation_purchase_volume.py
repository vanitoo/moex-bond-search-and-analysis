# 💰 Расчет оптимального объема покупки облигаций 💰
#
# Читает список облигаций из bonds.xlsx, получает цену и НКД через MOEX ISS,
# равномерно распределяет доступную сумму и сохраняет расчет в Excel.

import os
import sys

sys.path.append(f"{os.getcwd()}/src")

from cli import start


if __name__ == "__main__":
    start(4)
