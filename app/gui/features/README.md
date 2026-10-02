# GUI features

Текущий GUI собран из смысловых модулей, а не из версий `gui_app_vN.py`.

- `base.py` — общая Streamlit-логика, конфигурация, чтение результатов;
- `portfolio_impact_view.py` — сценарий влияния покупки;
- `portfolio_view.py` — управление виртуальным портфелем;
- `recommendations_view.py` — рекомендации и сравнение кандидатов;
- `module_state.py` — состояние и ошибки модулей;
- `runner_view.py` — запуск/лог pipeline;
- `today_view.py` — экран «Сегодня»;
- `tabs.py` — структура вкладок;
- `allocation_view.py` — распределение новых денег;
- `bond_journey_view.py` — маршрут бумаги по этапам анализа;
- `portfolio_charts_view.py` — графики портфеля;
- `buy_plan_view.py` — план покупки и добавление в виртуальный портфель;
- `portfolio_workspace.py` — portfolio-first, ручные позиции, доходы;
- `current.py` — сборка текущего GUI.

Напрямую эти файлы запускать не нужно. Пользовательский запуск: `python bondlab.py gui`.
