#!/bin/bash
cd "$(dirname "$0")/../.."
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
echo "Установка завершена. Нажмите Enter для выхода."
read
