"""换季趋势分析测试（M12）。

对应测试补齐要求：monthly_series / yoy / mom / trend_slope /
seasonal_index / recommend，共 6 个函数。
"""

from __future__ import annotations

import pytest

from app.core import seasonal


def _record(sku: str, qty: float, day: str) -> dict:
    return {"sku_id": sku, "qty": qty, "date": day, "unit_price": 1.0}


def test_monthly_series_aggregates_by_month():
    records = [
        _record("S1", 2, "2026-01-03"),
        _record("S1", 3, "2026-01-20"),
        _record("S1", 5, "2026-02-01"),
        _record("S2", 9, "2026-01-01"),
    ]
    assert seasonal.monthly_series(records, "S1") == {"2026-01": 5.0, "2026-02": 5.0}
    assert seasonal.monthly_series(records) == {"2026-01": 14.0, "2026-02": 5.0}


def test_yoy_needs_last_year_data():
    series = {"2025-07": 100.0, "2026-07": 150.0}
    assert seasonal.yoy(series, "2026-07") == pytest.approx(0.5)
    assert seasonal.yoy(series, "2026-08") is None
    assert seasonal.yoy({"2026-07": 10.0}, "2026-07") is None


def test_mom_handles_year_rollover():
    series = {"2025-12": 100.0, "2026-01": 120.0}
    assert seasonal.mom(series, "2026-01") == pytest.approx(0.2)
    assert seasonal.mom(series, "2026-02") is None


def test_trend_slope_positive_and_flat():
    rising = {"2026-01": 10.0, "2026-02": 20.0, "2026-03": 30.0}
    assert seasonal.trend_slope(rising) == pytest.approx(10.0)
    assert seasonal.trend_slope({"2026-01": 5.0, "2026-02": 5.0}) == pytest.approx(0.0)
    assert seasonal.trend_slope({"2026-01": 5.0}) == 0.0


def test_seasonal_index_across_two_years():
    series = {
        "2025-01": 100.0,
        "2025-07": 200.0,
        "2026-01": 100.0,
        "2026-07": 200.0,
    }
    index = seasonal.seasonal_index(series)
    assert index[1] == pytest.approx(0.6667, abs=1e-3)
    assert index[7] == pytest.approx(1.3333, abs=1e-3)
    assert index[12] == 1.0


def test_recommend_returns_explainable_items():
    records = []
    for month, qty in [(1, 10), (2, 10), (3, 12), (4, 15), (5, 20), (6, 30), (7, 60)]:
        records.append(_record("S1", qty, f"2026-{month:02d}-15"))
    result = seasonal.recommend(records, current_month=6)
    assert result
    item = result[0]
    assert item["sku_id"] == "S1"
    assert item["action"] in ("加大备货", "小幅增加备货", "维持现状", "控制进货")
    assert "季节" in item["reason"] or "环比" in item["reason"] or "趋势" in item["reason"]


def test_recommend_empty_records():
    assert seasonal.recommend([], 6) == []
