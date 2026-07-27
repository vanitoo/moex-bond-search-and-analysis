# 📊 Поиск информации об эмитентах и новостей о компаниях 📊
#
# Загружает данные об облигациях из bonds.xlsx, получает названия эмитентов
# через API Московской биржи, ищет новости и сохраняет их в локальные файлы.

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cli import start


if __name__ == "__main__":
    start(3)
