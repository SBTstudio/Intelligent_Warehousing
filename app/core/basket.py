"""【M3】购物篮分析 —— Apriori 关联规则挖掘。

对应需求：2.1 输入量 1
    "多次购物小票的商品购买种类，经过购物篮分析算法挖掘商品潜在关联度，
     输出两件商品有正向连带购买关系 lift。"

------------------------------------------------------------
公式
------------------------------------------------------------
    support(A→B)    = |同时含 A 和 B 的交易数| / 总交易数
    confidence(A→B) = support(A∪B) / support(A)
    lift(A→B)       = confidence(A→B) / support(B)
                    = P(A∩B) / (P(A) · P(B))

    lift > 1  → 正向连带（买了 A 的人比普通人更可能买 B）
    lift = 1  → 相互独立
    lift < 1  → 负相关

------------------------------------------------------------
实现说明
------------------------------------------------------------
    1. 按 order_id 把明细聚合成购物篮（list[set]），同一张小票里重复出现的
       SKU 只算一次。
    2. 从 1-项集开始逐层生成候选，利用 Apriori 性质剪枝：
       频繁项集的所有子集必然也是频繁的。剪枝能显著减少候选数量。
    3. 用「枚举每个篮子里的 k 元子集」的方式计数，而不是拿每个候选去扫
       全部篮子。两种写法结果一样，但前者在真实数据上快一个数量级。
    4. 对频繁项集枚举所有非空真子集作为前件，生成 A→B 规则。

    本模块只用标准库，不依赖 numpy / pandas / 界面库，可以脱离 GUI 单独测试
    和压测（项目铁律：app/core 不允许 import PySide6）。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import combinations


@dataclass
class Rule:
    """一条关联规则 A → B。"""

    antecedent: str  # 前件
    consequent: str  # 后件
    support: float  # 支持度
    confidence: float  # 置信度
    lift: float  # 提升度

    def __str__(self) -> str:
        return (
            f"{self.antecedent} → {self.consequent}  "
            f"support={self.support:.3f}  "
            f"confidence={self.confidence:.3f}  "
            f"lift={self.lift:.3f}"
        )


def build_baskets(records: list[dict]) -> list[set[str]]:
    """第 1 步：把交易明细整理成购物篮列表。

    参数
        records: 每条形如 {"order_id": "T001", "sku_id": "S003", "qty": 2}
    返回
        [{"S001", "S005"}, ...]，每个集合代表一张小票里出现的 SKU 集合
        （同一 SKU 买了多件只算一次）

    实现：用 dict 按 order_id 分组。Python 3.7+ 的 dict 保持插入顺序，
    所以返回顺序和第一次出现顺序一致，方便测试与复现。
    """
    grouped: dict[str, set[str]] = {}
    for row in records:
        order_id = row.get("order_id")
        sku_id = row.get("sku_id")
        if order_id is None or sku_id is None:
            continue
        sku = str(sku_id).strip()
        if not sku:
            continue
        grouped.setdefault(str(order_id), set()).add(sku)
    return [basket for basket in grouped.values() if basket]


def count_support(baskets: list[set[str]], itemset: frozenset[str]) -> float:
    """计算某个项集的支持度 = 包含该项集的篮子数 / 篮子总数。"""
    if not baskets:
        return 0.0
    hit = sum(1 for basket in baskets if itemset <= basket)
    return hit / len(baskets)


def _candidate_pairs(items: list[frozenset[str]]) -> set[frozenset[str]]:
    """由频繁 k-项集生成 (k+1)-项集候选，并按 Apriori 性质剪枝。"""
    candidates: set[frozenset[str]] = set()
    current = set(items)
    n = len(items)
    for i in range(n):
        for j in range(i + 1, n):
            union = items[i] | items[j]
            if len(union) != len(items[i]) + 1:
                continue
            # 剪枝：所有 k-子集都必须是频繁的，否则这个候选不可能频繁
            if all(frozenset(sub) in current for sub in combinations(union, len(union) - 1)):
                candidates.add(union)
    return candidates


def find_frequent_itemsets(
    baskets: list[set[str]],
    min_support: float,
    max_len: int = 2,
) -> dict[frozenset[str], float]:
    """逐层找出所有频繁项集。

    参数
        baskets:     购物篮列表
        min_support: 最小支持度阈值，低于它的项集会被剪掉
        max_len:     最大项集长度。本项目只需要两两关联，默认 2 即可
    返回
        {frozenset({"S001", "S005"}): 0.032, ...}
    """
    if not baskets or max_len < 1:
        return {}

    total = len(baskets)
    # 阈值做一点浮点容差，避免 0.1 这类边界值因为二进制误差被判掉
    threshold = max(0.0, float(min_support)) - 1e-12

    # ---- L1：单品支持度 ----
    counts: Counter[str] = Counter()
    for basket in baskets:
        counts.update(basket)
    frequent: dict[frozenset[str], float] = {}
    current: set[frozenset[str]] = set()
    for sku, count in counts.items():
        support = count / total
        if support >= threshold:
            itemset = frozenset((sku,))
            frequent[itemset] = support
            current.add(itemset)

    # ---- L2..Lk：逐层生成候选 + 计数 ----
    k = 2
    while current and k <= max_len:
        candidates = _candidate_pairs(sorted(current, key=lambda s: sorted(s)))
        if not candidates:
            break

        counts_k: Counter[frozenset[str]] = Counter()
        for basket in baskets:
            if len(basket) < k:
                continue
            # 枚举篮子里的 k 元子集，只统计在候选集合里的组合。
            # 数据量大时这比"每个候选扫一遍全部篮子"快得多。
            for combo in combinations(basket, k):
                candidate = frozenset(combo)
                if candidate in candidates:
                    counts_k[candidate] += 1

        next_level: set[frozenset[str]] = set()
        for itemset, count in counts_k.items():
            support = count / total
            if support >= threshold:
                frequent[itemset] = support
                next_level.add(itemset)

        current = next_level
        k += 1

    return frequent


def mine_rules(
    baskets: list[set[str]],
    min_support: float = 0.01,
    min_confidence: float = 0.3,
    only_positive: bool = False,
) -> list[Rule]:
    """主入口：挖掘关联规则。

    参数
        baskets:        购物篮列表
        min_support:    最小支持度
        min_confidence: 最小置信度，低于它的规则不输出（滤掉噪声）
        only_positive:  为 True 时只保留 lift > 1 的正向连带关系
    返回
        list[Rule]，按 lift 从高到低排序

    说明：数值保留完整精度，界面展示时再按需求 2.4.1 格式化为 3 位小数。
    这样排序不会因为提前四舍五入而出现"看起来乱序"的问题。
    """
    if not baskets:
        return []

    frequent = find_frequent_itemsets(baskets, min_support=min_support, max_len=2)
    if not frequent:
        return []

    rules: list[Rule] = []
    for itemset, support_union in frequent.items():
        if len(itemset) < 2:
            continue
        for size in range(1, len(itemset)):
            for antecedent_tuple in combinations(itemset, size):
                antecedent = frozenset(antecedent_tuple)
                consequent = itemset - antecedent
                support_a = frequent.get(antecedent)
                support_b = frequent.get(consequent)
                if not support_a or not support_b:
                    continue
                confidence = support_union / support_a
                if confidence < min_confidence:
                    continue
                lift = confidence / support_b
                if only_positive and lift <= 1.0:
                    continue
                rules.append(
                    Rule(
                        antecedent=" + ".join(sorted(antecedent)),
                        consequent=" + ".join(sorted(consequent)),
                        support=support_union,
                        confidence=confidence,
                        lift=lift,
                    )
                )

    # lift 相同时按 confidence 降序，保证结果稳定、可复现
    rules.sort(key=lambda r: (r.lift, r.confidence, r.support), reverse=True)
    return rules


def lif_matrix(rules: list[Rule], top_n: int = 15):
    """把规则整理成 lift 矩阵，供前端画热力图。

    返回
        (labels: list[str], matrix: list[list[float]])
        其中 labels 是参与的商品列表，matrix[i][j] 是 i → j 的 lift，
        没有对应规则的位置填 1.0（表示无关联）

    实现：按商品在规则里出现的次数取 top_n 个作为行列标签。
    """
    if not rules:
        return [], []

    counter: Counter[str] = Counter()
    for rule in rules:
        counter[rule.antecedent] += 1
        counter[rule.consequent] += 1

    labels = [name for name, _ in counter.most_common(max(1, top_n))]
    index = {name: i for i, name in enumerate(labels)}
    matrix = [[1.0 for _ in labels] for _ in labels]
    for rule in rules:
        i = index.get(rule.antecedent)
        j = index.get(rule.consequent)
        if i is not None and j is not None:
            matrix[i][j] = rule.lift
    return labels, matrix
