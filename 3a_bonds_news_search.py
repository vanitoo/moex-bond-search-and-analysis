# 📊 Поиск информации об эмитентах и новостей о компаниях 📊
#
# Загружает данные об облигациях из bonds.xlsx, получает названия эмитентов
# через API Московской биржи, ищет новости и сохраняет их в локальные файлы.

import os
import sys

sys.path.append(f"{os.getcwd()}/src")

from cli import start


if __name__ == "__main__":
    start(3)
