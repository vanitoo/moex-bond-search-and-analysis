import pandas as pd

from moex_bond_search_and_analysis.cbr_banks import (
    _parse_f135_html,
    score_bank_metrics,
)


def test_parse_f135_html_extracts_prudential_ratios():
    html = """
    <table>
      <thead><tr><th>Краткое наименование норматива</th><th>Фактическое значение, в процентах</th></tr></thead>
      <tbody>
        <tr><td>Н1.0</td><td>12,5</td></tr>
        <tr><td>Н1.1</td><td>8,1</td></tr>
        <tr><td>Н1.2</td><td>9,2</td></tr>
        <tr><td>Н2</td><td>45,0</td></tr>
        <tr><td>Н3</td><td>95,0</td></tr>
        <tr><td>Н4</td><td>72,0</td></tr>
      </tbody>
    </table>
    """
    values = _parse_f135_html(html)
    assert values["Н1.0"] == 12.5
    assert values["Н1.1"] == 8.1
    assert values["Н1.2"] == 9.2
    assert values["Н2"] == 45.0
    assert values["Н3"] == 95.0
    assert values["Н4"] == 72.0


def test_bank_score_rewards_comfortable_ratios():
    row = pd.Series({
        "Н1.0": 13.0,
        "Н1.1": 8.0,
        "Н1.2": 10.0,
        "Н2": 50.0,
        "Н3": 100.0,
        "Н4": 70.0,
    })
    score, positives, risks, hard_stop, completeness = score_bank_metrics(row)
    assert score == 30
    assert completeness == 10
    assert hard_stop is False
    assert positives
    assert not risks


def test_bank_score_hard_stops_below_basic_norm():
    row = pd.Series({
        "Н1.0": 7.5,
        "Н1.1": 8.0,
        "Н1.2": 10.0,
        "Н2": 50.0,
        "Н3": 100.0,
        "Н4": 70.0,
    })
    _, _, risks, hard_stop, _ = score_bank_metrics(row)
    assert hard_stop is True
    assert any("Н1.0" in risk for risk in risks)
