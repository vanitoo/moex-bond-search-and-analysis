# Структура проекта

После рефакторинга у проекта одна пользовательская точка входа:

`bondlab.py`

В корне больше не должно быть рабочих `run_*.py` / `daily_runner.py`. Внутренние runner-ы находятся в `app/cli/`.

## Что запускать

GUI:

```powershell
.\.venv\Scripts\python.exe .\bondlab.py gui
```

Полный pipeline без GUI:

```powershell
.\.venv\Scripts\python.exe .\bondlab.py pipeline `
  --from-stage 1 `
  --to-stage 10 `
  --config .\configs\gui_active.json
```

Полный месячный запуск с портфелем:

```powershell
.\.venv\Scripts\python.exe .\bondlab.py full `
  --portfolio "Название_портфеля" `
  --config .\configs\gui_active.json
```

Ежедневный мониторинг портфеля:

```powershell
.\.venv\Scripts\python.exe .\bondlab.py monitor `
  --portfolio "Название_портфеля" `
  --config .\configs\gui_active.json
```

## Активная структура

```text
bondlab.py              # единственная пользовательская точка входа

app/
  cli/
    pipeline.py         # оркестратор этапов 1-10
    daily.py            # full / monitor для портфеля
    gui.py              # запуск Streamlit
  core/                 # общая логика pipeline и master dataset
  stages/               # рабочие этапы полного анализа
  portfolio/            # виртуальный портфель, покупки, мониторинг, доходы
  gui/
    gui_app.py          # текущий Streamlit entrypoint
    layers/             # внутренние runtime-слои GUI

src/
  moex_bond_search_and_analysis/
                        # интеграции MOEX, новости, рейтинги, ФНС, ЦБ

configs/                # конфигурации
data/                   # кэши и постоянные локальные данные
scripts/                # установка/планировщик
tools/                  # отдельные сервисные утилиты
tests/                  # тесты
docs/                   # документация
archive/legacy/         # старый код, не используемый runtime
```

## Что рабочее, а что нет

Рабочий runtime:
- `bondlab.py`;
- всё в `app/cli`, `app/core`, `app/stages`, `app/portfolio`, `app/gui`;
- пакет `src/moex_bond_search_and_analysis`.

Не запускать вручную:
- файлы из `app/stages` — их запускает pipeline;
- файлы из `app/gui/layers` — это внутренние части текущего GUI;
- файлы из `app/core` и `app/portfolio` — это библиотеки приложения.

Legacy:
- всё в `archive/legacy/` не должно импортироваться рабочим приложением.

## GUI layers

`app/gui/layers/gui_app_v*.py` пока остаются единственным некрасивым историческим участком.
Они **всё ещё используются** текущим GUI, поэтому удалить их просто так нельзя. Это не мусор.

Следующий безопасный этап — заменить цепочку `v2...v16` смысловыми модулями
(`dashboard.py`, `portfolio_view.py`, `recommendations_view.py`, `runner_view.py`)
и после этого перенести versioned-файлы в `archive/legacy/gui`.

## Результаты запусков

Каталоги `bond_YYYY_MM_DD/`, `reports/` и runtime-кэши — это результаты работы, а не исходный код.
Их не нужно воспринимать как рабочие Python-модули.
