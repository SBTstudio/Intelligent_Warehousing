"""算法测试 —— 写完 app/core 里的算法后，这些测试应该全部通过。

现在跑会全红（NotImplementedError），这是正常的，把它当成任务清单用。

运行：
    .venv/Scripts/python.exe -m pytest tests/test_algorithms.py -v
"""

from datetime import date
from pathlib import Path

import pytest

from app.core import basket, classify, replenish

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"


# =====================================================================
# M3 购物篮分析
# =====================================================================
def test_build_baskets_groups_by_order():
    records = [
        {"order_id": "T1", "sku_id": "A", "qty": 1},
        {"order_id": "T1", "sku_id": "B", "qty": 2},
        {"order_id": "T1", "sku_id": "A", "qty": 3},  # 同一张票里 A 出现两次
        {"order_id": "T2", "sku_id": "B", "qty": 1},
    ]
    baskets = basket.build_baskets(records)
    assert len(baskets) == 2, "应该按 order_id 分成 2 个篮子"
    assert baskets[0] == {"A", "B"}, "同一张票里重复的 SKU 只算一次"
    assert baskets[1] == {"B"}


def test_support_of_single_item():
    baskets = [{"A", "B"}, {"A"}, {"B"}, {"A", "B"}]
    # A 出现在 3/4 个篮子里
    assert basket.count_support(baskets, frozenset({"A"})) == pytest.approx(0.75)


def test_frequent_itemsets_respects_min_support():
    baskets = [{"A", "B"}, {"A", "B"}, {"A", "C"}, {"A"}]
    freq = basket.find_frequent_itemsets(baskets, min_support=0.5)
    assert frozenset({"A"}) in freq      # 4/4
    assert frozenset({"B"}) in freq      # 2/4
    assert frozenset({"C"}) not in freq  # 1/4，被剪掉
    assert frozenset({"A", "B"}) in freq # 2/4


def test_lift_formula():
    """手工构造：A 和 B 完全同现，lift 应该明显大于 1。"""
    baskets = [{"A", "B"}] * 8 + [{"A"}] * 2 + [{"B"}] * 2 + [{"C"}] * 8
    rules = basket.mine_rules(baskets, min_support=0.05, min_confidence=0.1)
    ab = [r for r in rules if r.antecedent == "A" and r.consequent == "B"]
    assert ab, "应该挖出 A → B 这条规则"

    r = ab[0]
    p_a = 10 / 20
    p_b = 10 / 20
    p_ab = 8 / 20
    assert r.support == pytest.approx(p_ab, abs=1e-3)
    assert r.confidence == pytest.approx(p_ab / p_a, abs=1e-3)
    assert r.lift == pytest.approx(p_ab / (p_a * p_b), abs=1e-3)
    assert r.lift > 1.0


def test_rules_sorted_by_lift_desc():
    baskets = [{"A", "B"}] * 8 + [{"C", "D"}] * 8 + [{"A", "C"}] * 2
    rules = basket.mine_rules(baskets, min_support=0.05, min_confidence=0.05)
    lifts = [r.lift for r in rules]
    assert lifts == sorted(lifts, reverse=True), "规则应按 lift 从高到低排序"


def test_positive_only_filter():
    baskets = [{"A", "B"}] * 8 + [{"A", "C"}] * 1 + [{"C"}] * 9
    rules = basket.mine_rules(baskets, min_support=0.05, min_confidence=0.05, only_positive=True)
    assert all(r.lift > 1.0 for r in rules)


@pytest.mark.slow
def test_finds_injected_affinities_in_sample_data():
    """用生成好的假数据跑，应该能挖出脚本里埋的那几组连带关系。"""
    from app.core import ingest

    records, _ = ingest.load_sample()
    if not records:
        pytest.skip("示例数据未就绪，请先运行 tools/make_fake_data.py")

    baskets = basket.build_baskets(records)
    rules = basket.mine_rules(baskets, min_support=0.01, min_confidence=0.3)

    found = {(r.antecedent, r.consequent) for r in rules}
    expected = [("S001", "S002"), ("S003", "S004"), ("S005", "S006")]
    for pair in expected:
        assert pair in found, f"没有挖出埋入的关联关系 {pair}，算法可能有问题"


# =====================================================================
# M4 补货预测
# =====================================================================
def test_exponential_smoothing_reacts_to_recent_change():
    flat = replenish.exponential_smoothing([10.0] * 20, alpha=0.3)
    assert flat == pytest.approx(10.0, abs=0.5)

    rising = replenish.exponential_smoothing([5.0] * 10 + [20.0] * 10, alpha=0.3)
    assert rising > flat, "近期销量上升，平滑值应该更高"


def test_z_for_known_service_levels():
    assert replenish.z_for(0.95) == pytest.approx(1.65, abs=0.02)
    assert replenish.z_for(0.99) == pytest.approx(2.33, abs=0.02)


def test_moving_average_handles_empty():
    assert replenish.moving_average([], window=7) is None
    assert replenish.moving_average([3.0, 4.0], window=7) is None


def test_suggestion_math():
    """日均销量 10、波动很小、提前期 3 天，手算一遍验证。"""
    values = [10.0] * 30
    s = replenish.build_suggestion(
        sku_id="X1",
        sku_name="测试",
        stock_qty=20.0,
        values=values,
        lead_time_days=3,
        service_level=0.95,
        today=date(2026, 6, 1),
    )
    assert s.daily_sales == pytest.approx(10.0, abs=0.5)
    assert s.demand_std == pytest.approx(0.0, abs=0.01)
    assert s.safety_stock == pytest.approx(0.0, abs=0.1)
    assert s.reorder_point == pytest.approx(30.0, abs=0.5)
    # 库存 20，日均 10，够卖 2 天；提前期 3 天，所以现在就该补货
    assert s.urgent is True


def test_suggestion_not_urgent_when_stock_is_high():
    s = replenish.build_suggestion(
        sku_id="X2",
        sku_name="测试",
        stock_qty=500.0,
        values=[10.0] * 30,
        lead_time_days=3,
    )
    assert s.urgent is False
    assert s.days_left > 30


# =====================================================================
# M5 畅销滞销
# =====================================================================
def test_abc_classification_buckets():
    profiles = [
        classify.SkuProfile(sku_id=f"S{i}", sales_amount=float(v))
        for i, v in enumerate([500, 300, 100, 50, 30, 20])
    ]
    result = classify.abc_classify(profiles)
    by_id = {p.sku_id: p for p in result}
    assert by_id["S0"].abc_class == "A"      # 500/1000 = 50%
    assert by_id["S5"].abc_class == "C"      # 长尾
    assert result[0].sales_amount >= result[-1].sales_amount, "结果应按销售额降序"


def test_xyz_classification():
    cv_x, cls_x = classify.xyz_classify([10.0] * 30)
    assert cls_x == "X" and cv_x == pytest.approx(0.0, abs=0.01)

    cv_z, cls_z = classify.xyz_classify([0.0, 0.0, 50.0, 0.0, 0.0, 40.0])
    assert cls_z == "Z" and cv_z > 0.5


def test_judge_slow_mover():
    p = classify.SkuProfile(
        sku_id="S9", abc_class="C", xyz_class="Z", turnover_days=90.0
    )
    assert classify.judge(p, slow_turnover_days=45) in ("滞销", "呆滞")


def test_judge_best_seller():
    p = classify.SkuProfile(
        sku_id="S1", abc_class="A", xyz_class="X", turnover_days=5.0
    )
    assert classify.judge(p, slow_turnover_days=45) == "畅销"
