"""【M1】数据导入与校验。

对应需求：2.2.1 数据输入一般性规定
    "所有导入的销售小票、库存、客户购买记录数据，系统应具备基础校验能力；
     对格式异常、缺失字段的数据给出提示，拒绝非法数据进入分析流程，
     同时保留原始输入记录，不会修改用户原始业务文件。"

对应需求：2.4.4 输入输出要求
    购物小票：CSV / TXT，字段含 商品SKU、购买数量、交易时间；数值为非负整数
    库存数据：SKU编号、现有库存数量、进货成本；数量 ≥ 0

实现原则：
    1. 只读原始文件，任何情况下都不写回（需求 2.2.1 的硬性要求）。
    2. 编码自动识别：utf-8-sig → utf-8 → gbk，覆盖 Windows Excel 导出的常见情况。
    3. 错误信息带行号，用户能直接定位到 Excel / 文本里的哪一行。
    4. 校验通过的行才进入返回值；坏行被拒绝，但不影响好行的展示。
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.paths import sample_dir

# 允许的文件编码，按顺序尝试
ENCODINGS = ("utf-8-sig", "utf-8", "gbk")

# 各文件类型必须包含的字段（列名先做小写化与去空格处理）
REQUIRED_COLUMNS = {
    "receipt": {"sku_id", "qty", "date"},
    "inventory": {"sku_id", "stock_qty"},
    "products": {"sku_id"},
}

# 标准列名集合
CANONICAL_COLUMNS = {
    "order_id",
    "sku_id",
    "sku_name",
    "category",
    "qty",
    "date",
    "unit_price",
    "stock_qty",
    "cost",
    "price",
    "snapshot_date",
}

# 同义词表：用户导出的列名千奇百怪，这里尽量覆盖
_ALIAS_GROUPS = {
    "order_id": [
        "order_id", "orderid", "order", "order_no", "orderno", "transaction_id",
        "ticket_id", "receipt_id", "订单号", "订单编号", "小票号", "小票编号",
        "交易号", "交易编号", "单据号", "流水号",
    ],
    "sku_id": [
        "sku_id", "skuid", "sku", "sku_no", "sku_code", "item_id", "item_code",
        "product_id", "product_code", "商品编号", "商品编码", "商品代码", "商品sku",
        "sku编号", "sku编码", "货号", "单品编号", "单品编码", "商品id",
    ],
    "sku_name": [
        "sku_name", "skuname", "name", "item_name", "product_name", "商品名称",
        "商品名", "品名", "名称", "单品名称",
    ],
    "category": ["category", "class", "品类", "类别", "分类", "商品分类", "商品品类"],
    "qty": [
        "qty", "quantity", "count", "num", "amount", "sales_qty", "sold_qty",
        "数量", "购买数量", "商品数量", "销售量", "销量", "件数", "个数",
    ],
    "date": [
        "date", "day", "ts", "time", "datetime", "transaction_time", "trade_time",
        "sale_time", "日期", "时间", "交易时间", "交易日期", "下单时间",
        "购买时间", "销售日期", "销售时间", "小票时间",
    ],
    "unit_price": [
        "unit_price", "unitprice", "price", "sale_price", "selling_price",
        "单价", "售价", "零售价", "销售单价", "商品单价", "成交单价",
    ],
    "stock_qty": [
        "stock_qty", "stockqty", "stock", "inventory", "inventory_qty",
        "on_hand", "库存", "库存量", "库存数", "库存数量", "现有库存",
        "现有库存数量", "当前库存", "结存数量",
    ],
    "cost": [
        "cost", "unit_cost", "purchase_cost", "cost_price", "成本", "进货成本",
        "采购成本", "单位成本", "成本价",
    ],
    "price": ["price", "retail_price", "list_price", "价格", "定价", "零售价格"],
    "snapshot_date": ["snapshot_date", "snapshot", "快照日期", "盘点日期", "统计日期"],
}

# 反向索引：规范化后的别名 → 标准列名
COLUMN_ALIASES: dict[str, str] = {}
for _standard, _aliases in _ALIAS_GROUPS.items():
    COLUMN_ALIASES[_standard] = _standard
    for _alias in _aliases:
        COLUMN_ALIASES[_alias] = _standard


@dataclass
class ValidationResult:
    """校验结果。"""

    ok: bool = True
    rows: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def reject(self, msg: str):
        self.errors.append(msg)
        self.ok = False


def _canonical_name(column: str) -> str:
    """列名规范化：去 BOM、去首尾空格、转小写、去括号单位、统一分隔符。"""
    text = str(column or "").replace("\ufeff", "").strip().lower()
    text = text.replace("　", " ").strip()
    # "购买数量（件）" → "购买数量"
    text = re.sub(r"[（(].*?[)）]", "", text).strip()
    text = text.replace(" ", "").replace("-", "_").replace("/", "_")
    text = text.rstrip(":：")
    return text


def sniff_encoding(path: str | Path) -> str:
    """自动识别文件编码。

    依次用 ENCODINGS 里的编码去读，第一个能成功解码的就是它。
    都失败就抛 ValueError，交给调用方提示用户。
    """
    target = Path(path)
    data = target.read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    for encoding in ENCODINGS:
        try:
            data.decode(encoding)
        except UnicodeDecodeError:
            continue
        return encoding
    raise ValueError(
        f"无法识别文件编码（已尝试 {', '.join(ENCODINGS)}）：{target.name}"
    )


def normalize_columns(columns: list[str]) -> dict[str, str]:
    """把用户文件里的列名映射到系统标准列名。

    返回 {原始列名: 标准列名}；没有命中同义词表的列保留规范化后的名字，
    方便用户看到"系统没认出来的是哪一列"。
    """
    mapping: dict[str, str] = {}
    for column in columns:
        key = _canonical_name(column)
        if not key:
            continue
        mapping[column] = COLUMN_ALIASES.get(key, key)
    return mapping


def _sniff_delimiter(text: str) -> str:
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        return dialect.delimiter
    except csv.Error:
        return "\t" if "\t" in sample and "," not in sample else ","


def _read_table(path: str | Path) -> tuple[list[str], list[tuple[int, dict[str, str]]]]:
    """读取 CSV/TXT，返回（表头, [(行号, 行字典)]）。

    行号用 csv.reader.line_num，带上表头计数，和编辑器里看到的行号一致。
    """
    target = Path(path)
    encoding = sniff_encoding(target)
    text = target.read_bytes().decode(encoding)
    if not text.strip():
        return [], []

    delimiter = _sniff_delimiter(text)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)

    header: list[str] | None = None
    rows: list[tuple[int, dict[str, str]]] = []
    for values in reader:
        line_no = reader.line_num
        # 跳过完全空白的行
        if not any(str(cell).strip() for cell in values):
            continue
        if header is None:
            header = [str(cell).replace("\ufeff", "").strip() for cell in values]
            continue
        record = {}
        for index, name in enumerate(header):
            record[name] = str(values[index]).strip() if index < len(values) else ""
        rows.append((line_no, record))
    return header or [], rows


def _value(row: dict[str, str], mapping: dict[str, str], canonical: str) -> str:
    for original, value in row.items():
        if mapping.get(original, original) == canonical:
            return str(value or "").strip()
    return ""


_DATE_PATTERN = re.compile(
    r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})"
    r"(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?$"
)


def parse_datetime(value: str) -> datetime | None:
    """解析常见日期写法；失败返回 None。"""
    text = str(value or "").strip()
    if not text:
        return None
    # 中文日期：2026年1月1日 10:00
    text = text.replace("年", "-").replace("月", "-").replace("日", " ").strip()
    match = _DATE_PATTERN.match(text)
    if not match:
        return None
    year, month, day, hour, minute, second = match.groups()
    try:
        return datetime(
            int(year),
            int(month),
            int(day),
            int(hour or 0),
            int(minute or 0),
            int(second or 0),
        )
    except ValueError:
        return None


def _normalize_datetime(value: datetime, original: str) -> str:
    has_time = ":" in original
    return value.strftime("%Y-%m-%d %H:%M:%S" if has_time else "%Y-%m-%d")


def _check_required(
    result: ValidationResult,
    header: list[str],
    kind: str,
) -> tuple[dict[str, str], list[str]]:
    mapping = normalize_columns(header)
    mapped = [mapping.get(column, column) for column in header]
    missing = REQUIRED_COLUMNS[kind] - set(mapped)
    if missing:
        result.reject(
            "缺少必需列：" + "、".join(sorted(missing))
            + "。请检查表头，或先用「载入示例数据」查看标准格式。"
        )
    return mapping, mapped


def validate_receipt(path: str | Path) -> ValidationResult:
    """校验并读取购物小票文件。

    校验规则（需求 2.4.4）：
        - 必须包含 sku_id、qty、date 三列
        - sku_id 不能为空
        - qty 必须是非负整数
        - date 必须能解析成日期

    返回的每一行都已经标准化，可以直接写入 schema.insert_sales()：
        {"order_id", "sku_id", "qty", "unit_price", "date", "ts"}
    """
    result = ValidationResult()
    try:
        header, raw_rows = _read_table(path)
    except FileNotFoundError:
        result.reject(f"文件不存在：{path}")
        return result
    except (ValueError, OSError, UnicodeError, csv.Error) as exc:
        result.reject(f"读取文件失败：{exc}")
        return result

    if not header:
        result.reject("文件为空或没有表头")
        return result

    mapping, mapped_header = _check_required(result, header, "receipt")
    if not result.ok:
        return result
    if not raw_rows:
        result.reject("文件只有表头，没有数据行")
        return result

    if "order_id" not in mapped_header:
        result.warnings.append("未找到订单号列，已按行生成导入批次号（同一张小票请补齐订单号）")
    if "unit_price" not in mapped_header:
        result.warnings.append("未找到单价列，销售额将按 0 计算")

    seen_orders: set[str] = set()
    for line_no, row in raw_rows:
        problems: list[str] = []

        sku = _value(row, mapping, "sku_id")
        if not sku:
            problems.append("sku_id 为空")

        qty_text = _value(row, mapping, "qty")
        qty_value = 0
        if not qty_text:
            problems.append("qty 为空")
        else:
            try:
                numeric = float(qty_text)
            except ValueError:
                problems.append(f"qty 为 {qty_text}，必须是数字")
            else:
                if numeric < 0:
                    problems.append(f"qty 为 {qty_text}，必须是非负整数")
                elif not numeric.is_integer():
                    problems.append(f"qty 为 {qty_text}，必须是非负整数")
                else:
                    qty_value = int(numeric)

        date_text = _value(row, mapping, "date")
        parsed_date = parse_datetime(date_text)
        if not date_text:
            problems.append("date 为空")
        elif parsed_date is None:
            problems.append(
                f"date 为 {date_text}，无法解析为日期（示例：2026-01-01 10:00）"
            )

        price_text = _value(row, mapping, "unit_price")
        unit_price = 0.0
        if price_text:
            try:
                unit_price = float(price_text)
            except ValueError:
                result.warnings.append(
                    f"第 {line_no} 行：unit_price 为 {price_text}，已按 0 处理"
                )
                unit_price = 0.0
            if unit_price < 0:
                problems.append(f"unit_price 为 {price_text}，不能为负数")

        if problems:
            for problem in problems:
                result.errors.append(f"第 {line_no} 行：{problem}")
            continue

        order_id = _value(row, mapping, "order_id")
        if not order_id:
            order_id = f"IMP{line_no:06d}"
        # 同一文件里同一订单号 + 同一 SKU 只保留一次，避免重复计数
        key = f"{order_id}|{sku}"
        if key in seen_orders:
            result.warnings.append(
                f"第 {line_no} 行：订单 {order_id} 的 {sku} 重复出现，已跳过"
            )
            continue
        seen_orders.add(key)

        assert parsed_date is not None
        normalized = _normalize_datetime(parsed_date, date_text)
        result.rows.append(
            {
                "order_id": order_id,
                "sku_id": sku,
                "qty": qty_value,
                "unit_price": round(unit_price, 2),
                "date": normalized,
                "ts": normalized,
            }
        )

    if not result.rows:
        result.reject("没有通过校验的数据行")

    total = len(raw_rows)
    accepted = len(result.rows)
    if result.errors and accepted:
        result.warnings.append(
            f"共 {total} 行，合格 {accepted} 行，拒绝 {total - accepted} 行；"
            "修正错误后可重新导入"
        )
    result.ok = bool(result.rows) and not result.errors
    return result


def validate_inventory(path: str | Path) -> ValidationResult:
    """校验并读取库存文件。

    校验规则：必须含 sku_id、stock_qty；stock_qty 必须 ≥ 0。
    """
    result = ValidationResult()
    try:
        header, raw_rows = _read_table(path)
    except FileNotFoundError:
        result.reject(f"文件不存在：{path}")
        return result
    except (ValueError, OSError, UnicodeError, csv.Error) as exc:
        result.reject(f"读取文件失败：{exc}")
        return result

    if not header:
        result.reject("文件为空或没有表头")
        return result

    mapping, mapped_header = _check_required(result, header, "inventory")
    if not result.ok:
        return result
    if not raw_rows:
        result.reject("文件只有表头，没有数据行")
        return result

    if "cost" not in mapped_header:
        result.warnings.append("未找到进货成本列，成本将按 0 处理")

    for line_no, row in raw_rows:
        problems: list[str] = []
        sku = _value(row, mapping, "sku_id")
        if not sku:
            problems.append("sku_id 为空")

        stock_text = _value(row, mapping, "stock_qty")
        stock_value = 0.0
        if not stock_text:
            problems.append("stock_qty 为空")
        else:
            try:
                stock_value = float(stock_text)
            except ValueError:
                problems.append(f"stock_qty 为 {stock_text}，必须是数字")
            else:
                if stock_value < 0:
                    problems.append(f"stock_qty 为 {stock_text}，必须 ≥ 0")

        cost_text = _value(row, mapping, "cost")
        cost_value = 0.0
        if cost_text:
            try:
                cost_value = float(cost_text)
            except ValueError:
                result.warnings.append(
                    f"第 {line_no} 行：cost 为 {cost_text}，已按 0 处理"
                )
                cost_value = 0.0

        if problems:
            for problem in problems:
                result.errors.append(f"第 {line_no} 行：{problem}")
            continue

        record = {
            "sku_id": sku,
            "sku_name": _value(row, mapping, "sku_name"),
            "stock_qty": stock_value,
            "cost": round(cost_value, 2),
        }
        snapshot_text = _value(row, mapping, "snapshot_date")
        if snapshot_text:
            snapshot = parse_datetime(snapshot_text)
            if snapshot is None:
                result.warnings.append(
                    f"第 {line_no} 行：snapshot_date 为 {snapshot_text}，"
                    "已改用导入日期"
                )
            else:
                record["snapshot_date"] = snapshot.strftime("%Y-%m-%d")
        result.rows.append(record)

    if not result.rows:
        result.reject("没有通过校验的数据行")

    if result.errors and result.rows:
        result.warnings.append(
            f"共 {len(raw_rows)} 行，合格 {len(result.rows)} 行，"
            f"拒绝 {len(raw_rows) - len(result.rows)} 行"
        )
    result.ok = bool(result.rows) and not result.errors
    return result


def validate_products(path: str | Path) -> ValidationResult:
    """校验并读取商品档案（sku_id 必需，其余字段可选）。"""
    result = ValidationResult()
    try:
        header, raw_rows = _read_table(path)
    except FileNotFoundError:
        result.reject(f"文件不存在：{path}")
        return result
    except (ValueError, OSError, UnicodeError, csv.Error) as exc:
        result.reject(f"读取文件失败：{exc}")
        return result

    if not header:
        result.reject("文件为空或没有表头")
        return result

    mapping, _ = _check_required(result, header, "products")
    if not result.ok:
        return result
    if not raw_rows:
        result.reject("文件只有表头，没有数据行")
        return result

    for line_no, row in raw_rows:
        sku = _value(row, mapping, "sku_id")
        if not sku:
            result.errors.append(f"第 {line_no} 行：sku_id 为空")
            continue
        record = {
            "sku_id": sku,
            "sku_name": _value(row, mapping, "sku_name"),
            "category": _value(row, mapping, "category"),
            "cost": 0.0,
            "price": 0.0,
        }
        for field_name in ("cost", "price"):
            text = _value(row, mapping, field_name)
            if text:
                try:
                    record[field_name] = max(0.0, float(text))
                except ValueError:
                    result.warnings.append(
                        f"第 {line_no} 行：{field_name} 为 {text}，已按 0 处理"
                    )
        result.rows.append(record)

    if not result.rows:
        result.reject("没有通过校验的数据行")
    result.ok = bool(result.rows) and not result.errors
    return result


def load_sample() -> tuple[list[dict], list[dict]]:
    """加载 data/sample/ 下的示例数据，方便开发时快速测试。

    返回 (小票记录, 库存记录)
    """
    directory = sample_dir()
    receipt = validate_receipt(directory / "receipts.csv")
    inventory = validate_inventory(directory / "inventory.csv")
    return receipt.rows, inventory.rows
