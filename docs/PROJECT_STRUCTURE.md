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
  core/                 # общая логика приложения
    stage_registry.py    # единый реестр этапов 1–10, GUI metadata и зависимости
    stage_arguments.py   # CLI-параметры отдельных этапов
    pipeline_architecture.py
    pipeline_common.py
    run_paths.py         # поиск/создание runs
    runtime_env.py       # единый PYTHONPATH/env для subprocess
    project_paths.py      # единые пути проекта: runs/data/reports/configs
    rating_utils.py       # единая шкала и нормализация рейтингов
    search_contract.py    # контракт колонок V1/V2 рыночного поиска
    master_dataset.py
    credit_engine.py     # чистая логика кредитного скоринга
    credit_sources.py    # рейтинги / ГИР БО / банковские нормативы
    credit_report.py     # Excel/HTML кредитного анализа
    decision_engine.py   # чистая логика финального решения
  stages/               # CLI-обвязка этапов: чтение/запись/оркестрация
  portfolio/            # виртуальный портфель, покупки, мониторинг, доходы
  gui/
    gui_app.py          # текущий Streamlit entrypoint
    features/           # смысловые модули текущего GUI

src/
  moex_bond_search_and_analysis/
                        # интеграции MOEX, новости, рейтинги, ФНС, ЦБ

configs/                # конфигурации
runs/                   # результаты полных анализов bond_YYYY_MM_DD (gitignored)\ndata/                   # кэши и постоянные локальные данные
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
- файлы из `app/gui/features` — это внутренние части текущего GUI;
- файлы из `app/core` и `app/portfolio` — это библиотеки приложения.

Legacy:
- всё в `archive/legacy/` не должно импортироваться рабочим приложением.

## GUI features

Историческая цепочка `gui_app_v2...v16` удалена из рабочего runtime.
Текущий интерфейс теперь разбит на смысловые файлы в `app/gui/features/`:
`base.py`, `today_view.py`, `portfolio_view.py`, `recommendations_view.py`,
`buy_plan_view.py`, `portfolio_workspace.py` и другие.

Их не нужно запускать вручную: сборкой управляет `app/gui/gui_app.py`, а пользователь запускает `bondlab.py gui`.

## Результаты запусков

Новые каталоги анализа создаются в `runs/bond_YYYY_MM_DD/`. Старые `bond_YYYY_MM_DD/` в корне поддерживаются только для совместимости. `reports/` и runtime-кэши — тоже результаты работы, а не исходный код.
Их не нужно воспринимать как рабочие Python-модули.


## Граница ответственности после второго рефакторинга

- `app/core/*_engine.py` — детерминированная бизнес-логика без сетевых запросов и записи отчётов.
- `app/core/credit_sources.py` — сетевые источники кредитного слоя; `credit_report.py` — только представление результатов.
- `app/stages/*.py` — загрузка входных файлов, вызов внешних источников, сохранение Excel/HTML и CLI.
- `app/core/stage_registry.py` — единственный источник правды о номерах, именах, output-pattern и описаниях этапов.
- `app/cli/pipeline.py` — только оркестрация запуска этапов и CLI-параметров.

Новые правила: не дублировать `STAGES`, описания этапов и `ModuleSpec` в разных файлах; новые scoring-правила сначала добавлять в engine и покрывать unit-тестом, а не писать непосредственно в CLI-скрипте.
## GUI после третьего рефакторинга

- `app/gui/features/current.py` — единственная композиция Streamlit-приложения и единственный `main()` в `features/`.
- Остальные `*_view.py` и `portfolio_workspace.py` — только render-функции; они больше не запускают друг друга.
- Удалены runtime-monkeypatch цепочки между `tabs`, `buy_plan`, `portfolio_workspace`, `module_state` и `runner_view`.
- Исторические alias-имена `v4`, `v10`, `_v14` и т. п. запрещены структурным тестом `tests/test_gui_structure.py`.
- Состояние модулей, запуск pipeline и кнопка копирования лога теперь находятся в общем GUI runtime (`features/base.py`).
- Кнопка обновления риск-мониторинга использует единый entrypoint `bondlab.py monitor`, а не удалённый `daily_runner.py`.


## Границы пакетов после четвёртого рефакторинга

Рабочий код больше не должен полагаться на внутренние каталоги как на отдельные import-root.

Разрешённые корни импорта:
- корень репозитория — для пакета `app.*`;
- `src/` — для пакета `moex_bond_search_and_analysis.*`.

Поэтому рабочие импорты имеют вид `app.core.*`, `app.portfolio.*`, `app.gui.*` или
`moex_bond_search_and_analysis.*`. Импорты вида `from master_dataset import ...`,
`from portfolio_store import ...` и аналогичные считаются ошибкой архитектуры.

`sys.path.insert/append` удалён из активного runtime. Подпроцессы получают только
необходимые import-root через `app/core/runtime_env.py`, а этапы pipeline запускаются
как package modules (`python -m app.stages.<stage>`).

Pytest использует те же границы:

```toml
pythonpath = [".", "src"]
```

Это специально не даёт тестам скрывать неправильные импорты. Правило дополнительно
защищает `tests/test_import_boundaries.py`.

Общие правила, которые теперь имеют один источник правды:
- пути проекта — `app/core/project_paths.py`;
- шкала/нормализация кредитных рейтингов — `app/core/rating_utils.py`;
- совместимость колонок V1/V2 поиска — `app/core/search_contract.py`.

Скрипт `src/cli.py` оставлен только как compatibility shim. Рабочая реализация находится
в `moex_bond_search_and_analysis.cli`.


## Оркестрация после пятого рефакторинга

- `app/core/process_runner.py` — единственная общая точка для запуска дочерних Python-процессов и package modules с правильным runtime environment.
- `app/cli/pipeline.py` больше не содержит собственный список `STAGES`: порядок и номера этапов берутся напрямую из `app/core/stage_registry.py`.
- Runtime module этапа строится централизованно через `runtime_module_for_script()`; pipeline больше не собирает import-path вручную.
- `app/cli/daily.py`, `app/portfolio/portfolio_daily_refresh.py` и GUI используют общий command/process builder вместо дублирования `sys.executable`, `python -m` и `PYTHONPATH`.
- GUI и daily CLI используют константы из `app/core/project_paths.py` для конфигов, runs, reports и portfolio data вместо ручной сборки путей.

Следующий рефакторинг: отделить configuration schema/defaults от Streamlit и CLI, чтобы GUI, pipeline и automation читали одну типизированную модель настроек без дублирования default-значений.
