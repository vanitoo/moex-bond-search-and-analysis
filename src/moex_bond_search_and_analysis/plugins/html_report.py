from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path

from moex_bond_search_and_analysis.schemas import Bond, SearchByCriteriaConditions


class HtmlSearchReport:
    """Создаёт автономный HTML-отчёт по результатам поиска облигаций."""

    def __init__(self, filename: str) -> None:
        self.filename = filename

    @staticmethod
    def _number(value: float | int, digits: int = 2) -> str:
        return f"{value:,.{digits}f}".replace(",", " ").replace(".", ",")

    @staticmethod
    def _risk_label(bond: Bond) -> tuple[str, str]:
        """Простая визуальная пометка, не являющаяся инвестиционной рекомендацией."""
        if bond.yield_ >= 30:
            return "Повышенное внимание", "danger"
        if bond.yield_ >= 22:
            return "Проверить эмитента", "warning"
        return "Базовая проверка", "ok"

    def write(self, data: list[Bond], conditions: SearchByCriteriaConditions) -> None:
        generated_at = datetime.now().strftime("%d.%m.%Y в %H:%M:%S")
        bonds = sorted(data, key=lambda item: item.yield_, reverse=True)

        if bonds:
            avg_yield = sum(item.yield_ for item in bonds) / len(bonds)
            avg_duration = sum(item.duration for item in bonds) / len(bonds)
            total_volume = sum(item.volume for item in bonds)
        else:
            avg_yield = 0.0
            avg_duration = 0.0
            total_volume = 0

        rows: list[str] = []
        for bond in bonds:
            risk_text, risk_class = self._risk_label(bond)
            moex_url = f"https://www.moex.com/ru/issue.aspx?board=TQCB&code={escape(bond.secid)}"
            rows.append(
                "<tr>"
                f"<td class='name'>{escape(bond.name)}</td>"
                f"<td><a href='{moex_url}' target='_blank' rel='noopener'>{escape(bond.secid)}</a></td>"
                f"<td>{escape(str(bond.is_qualified_investors))}</td>"
                f"<td>{self._number(bond.price)}%</td>"
                f"<td>{self._number(bond.volume, 0)}</td>"
                f"<td class='strong'>{self._number(bond.yield_)}%</td>"
                f"<td>{self._number(bond.duration, 1)}</td>"
                f"<td><span class='badge {risk_class}'>{risk_text}</span></td>"
                "</tr>"
            )

        empty_state = ""
        if not rows:
            empty_state = (
                "<div class='empty'>По заданным условиям облигации не найдены. "
                "Попробуйте изменить критерии поиска.</div>"
            )

        conditions_html = "<br>".join(escape(conditions.as_string).splitlines())

        html = f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Отчёт по поиску облигаций</title>
  <style>
    :root {{
      --bg: #f4f6f8;
      --card: #ffffff;
      --text: #17202a;
      --muted: #667085;
      --line: #e4e7ec;
      --accent: #175cd3;
      --ok-bg: #ecfdf3;
      --ok-text: #027a48;
      --warning-bg: #fffaeb;
      --warning-text: #b54708;
      --danger-bg: #fef3f2;
      --danger-text: #b42318;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      background: var(--bg);
      color: var(--text);
    }}
    .container {{ max-width: 1500px; margin: 0 auto; padding: 28px; }}
    h1 {{ margin: 0 0 8px; font-size: 30px; }}
    h2 {{ margin: 0 0 16px; font-size: 21px; }}
    .subtitle {{ color: var(--muted); margin-bottom: 24px; }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(4, minmax(180px, 1fr));
      gap: 14px;
      margin-bottom: 20px;
    }}
    .card, .panel {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 14px;
      box-shadow: 0 1px 2px rgba(16, 24, 40, 0.05);
    }}
    .card {{ padding: 18px; }}
    .card .label {{ color: var(--muted); font-size: 13px; margin-bottom: 8px; }}
    .card .value {{ font-size: 25px; font-weight: 700; }}
    .panel {{ padding: 20px; margin-bottom: 20px; }}
    .conditions {{ line-height: 1.65; color: #344054; }}
    .notice {{
      background: #eff8ff;
      border: 1px solid #b2ddff;
      color: #175cd3;
      border-radius: 10px;
      padding: 12px 14px;
      margin-bottom: 18px;
      line-height: 1.45;
    }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; min-width: 1000px; }}
    th {{
      text-align: left;
      font-size: 12px;
      color: var(--muted);
      background: #f9fafb;
      border-bottom: 1px solid var(--line);
      padding: 12px 10px;
      position: sticky;
      top: 0;
    }}
    td {{ border-bottom: 1px solid var(--line); padding: 12px 10px; font-size: 14px; }}
    tr:hover td {{ background: #f9fafb; }}
    td.name {{ min-width: 260px; }}
    td.strong {{ font-weight: 700; }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .badge {{ display: inline-block; padding: 5px 9px; border-radius: 999px; font-size: 12px; font-weight: 700; white-space: nowrap; }}
    .badge.ok {{ background: var(--ok-bg); color: var(--ok-text); }}
    .badge.warning {{ background: var(--warning-bg); color: var(--warning-text); }}
    .badge.danger {{ background: var(--danger-bg); color: var(--danger-text); }}
    .empty {{ padding: 36px; text-align: center; color: var(--muted); }}
    .footer {{ color: var(--muted); font-size: 12px; padding: 4px 2px 20px; }}
    @media (max-width: 900px) {{
      .container {{ padding: 16px; }}
      .cards {{ grid-template-columns: repeat(2, 1fr); }}
      h1 {{ font-size: 25px; }}
    }}
    @media (max-width: 520px) {{
      .cards {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main class="container">
    <h1>Поиск ликвидных облигаций</h1>
    <div class="subtitle">Отчёт сформирован {generated_at}</div>

    <section class="cards">
      <div class="card"><div class="label">Найдено облигаций</div><div class="value">{len(bonds)}</div></div>
      <div class="card"><div class="label">Средняя доходность</div><div class="value">{self._number(avg_yield)}%</div></div>
      <div class="card"><div class="label">Средняя дюрация</div><div class="value">{self._number(avg_duration, 1)} мес.</div></div>
      <div class="card"><div class="label">Общий объём за 15 дней</div><div class="value">{self._number(total_volume, 0)}</div></div>
    </section>

    <section class="panel">
      <h2>Условия поиска</h2>
      <div class="conditions">{conditions_html}</div>
    </section>

    <section class="panel">
      <h2>Результаты</h2>
      <div class="notice">
        Пометки в колонке «Внимание» основаны только на уровне доходности и служат сигналом для дополнительной проверки.
        Они не являются оценкой надёжности эмитента и не являются рекомендацией купить облигацию.
      </div>
      {empty_state}
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Наименование</th>
              <th>Код</th>
              <th>Для квал. инвестора</th>
              <th>Цена</th>
              <th>Объём за 15 дней</th>
              <th>Доходность</th>
              <th>Дюрация</th>
              <th>Внимание</th>
            </tr>
          </thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </div>
    </section>

    <div class="footer">
      Источник рыночных данных: Московская биржа. Перед покупкой необходимо отдельно проверить эмитента, условия выпуска, оферту, амортизацию и кредитный риск.
    </div>
  </main>
</body>
</html>
"""

        output_path = Path(self.filename)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding="utf-8")
