@echo off
setlocal
cd /d "%~dp0\..\.."
python bondlab.py gui
if errorlevel 1 (
  echo.
  echo GUI не запустился. Установите зависимости:
  echo python -m pip install -r requirements-gui.txt
  pause
)
