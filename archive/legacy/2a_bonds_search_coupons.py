# 💰 Скачивание и обработка данных о денежном потоке облигаций 💰
#
# Этот Python скрипт автоматически скачивает данные о купонах и выплатах номинала
# через API Московской биржи для списка облигаций из Excel-файла bonds.xlsx и
# записывает результат обратно в этот же файл.

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cli import start


if __name__ == "__main__":
    start(2)
