"""【M2】SQLite 数据层 —— 建表与读写。

对应需求：2.5 数据管理能力要求
    "系统管理销售小票记录、SKU商品档案、库存记录、分析报告四类数据"
    "预估支持保存至少3年店铺销售历史数据"

这个模块已经写完整了，可以直接用。
SQLite 是 Python 标准库自带的，不需要安装任何数据库软件。

三年数据实测（tools/benchmark_scale.py，300 SKU / 日均100张小票 / 1095天）：
    77 万行数据 → 数据库文件 54 MB，远低于 2 GB 上限。
    全部典型查询在 1 秒内返回，满足需求 1.1「较大数据集≤15s」。

用法：
    from app.db.schema import init_db, get_conn
    init_db()                     # 程序启动时调一次
    with get_conn() as conn:      # 之后这样拿连接
        ...
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "app.db"

# ---------------------------------------------------------------
# 建表语句
# ---------------------------------------------------------------
SCHEMA = """
-- SKU 商品档案
CREATE TABLE IF NOT EXISTS products (
    sku_id     TEXT PRIMARY KEY,
    sku_name   TEXT NOT NULL DEFAULT '',
    category   TEXT NOT NULL DEFAULT '',
    cost       REAL NOT NULL DEFAULT 0,      -- 进货成本
    price      REAL NOT NULL DEFAULT 0       -- 零售价
);

-- 交易头：一张小票一行
CREATE TABLE IF NOT EXISTS transactions (
    order_id     TEXT PRIMARY KEY,
    ts           TEXT NOT NULL,              -- 交易时间 ISO 格式
    total_amount REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_tx_ts ON transactions(ts);

-- 交易明细：一张小票里的每个商品一行
CREATE TABLE IF NOT EXISTS transaction_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id   TEXT NOT NULL,
    sku_id     TEXT NOT NULL,
    qty        INTEGER NOT NULL,
    unit_price REAL NOT NULL DEFAULT 0,
    FOREIGN KEY (order_id) REFERENCES transactions(order_id),
    FOREIGN KEY (sku_id)   REFERENCES products(sku_id)
);
CREATE INDEX IF NOT EXISTS idx_item_order ON transaction_items(order_id);
CREATE INDEX IF NOT EXISTS idx_item_sku   ON transaction_items(sku_id);

-- 库存快照：按日期留痕，可以看库存变化趋势
CREATE TABLE IF NOT EXISTS inventory (
    sku_id        TEXT NOT NULL,
    snapshot_date TEXT NOT NULL,
    stock_qty     REAL NOT NULL DEFAULT 0,
    cost          REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (sku_id, snapshot_date)
);
-- 覆盖索引：三年数据的库存快照有几十万行，逐行回表取 stock_qty 很慢。
-- 把 stock_qty 直接放进索引，聚合查询就不用回表了（实测 2174ms → 36ms）。
CREATE INDEX IF NOT EXISTS idx_inv_sku_stock ON inventory(sku_id, stock_qty);

-- 历史分析报告
CREATE TABLE IF NOT EXISTS reports (
    report_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    report_type  TEXT NOT NULL,              -- weekly / seasonal / trend
    generated_at TEXT NOT NULL,
    sample_size  INTEGER NOT NULL DEFAULT 0,
    content      TEXT NOT NULL DEFAULT '',
    params       TEXT NOT NULL DEFAULT ''    -- JSON 字符串，记录生成参数
);

-- 业务参数配置
CREATE TABLE IF NOT EXISTS config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@contextmanager
def get_conn():
    """获取数据库连接（上下文管理器，用完自动提交并关闭）。"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # 性能相关设置：WAL 让读写互不阻塞，NORMAL 同步在单机场景足够安全。
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """初始化数据库，建好所有表。重复调用是安全的。"""
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """对已有数据库做兼容性修补。

    早期版本的 insert_sales 对明细表用的是普通 INSERT，同一个订单重复导入
    会积累重复明细 —— 三年数据量下这会让库凭空膨胀。这里先清掉历史重复行，
    再建唯一索引，保证后续重复导入是幂等的（同一订单同一 SKU 只留一行）。
    """
    conn.execute(
        "DELETE FROM transaction_items WHERE id NOT IN ("
        "    SELECT MIN(id) FROM transaction_items GROUP BY order_id, sku_id)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_item_order_sku "
        "ON transaction_items(order_id, sku_id)"
    )


def analyze() -> None:
    """更新查询优化器的统计信息。

    这一步**很关键**，尤其是数据量大到三年量级以后：
    SQLite 没有统计信息时会选错执行计划。实测 ABC 销售额汇总查询
    在缺少统计信息时耗时 6640ms，执行过 ANALYZE 后降到 112ms（快 59 倍）。
    所以大批量导入数据后一定要调一次这个函数。
    """
    with get_conn() as conn:
        conn.execute("ANALYZE")


# ---------------------------------------------------------------
# 写入
# ---------------------------------------------------------------
def insert_products(rows: list[dict]) -> int:
    """批量写入 SKU 档案。rows 每项含 sku_id / sku_name / category / cost / price。"""
    if not rows:
        return 0
    sql = (
        "INSERT OR REPLACE INTO products (sku_id, sku_name, category, cost, price) "
        "VALUES (:sku_id, :sku_name, :category, :cost, :price)"
    )
    with get_conn() as conn:
        conn.executemany(sql, rows)
    return len(rows)


def ensure_products(sku_ids: list[str], names: dict[str, str] | None = None) -> int:
    """确保这些 SKU 在商品档案里存在，但不覆盖已有档案。

    小票导入通常只带 SKU 编号，没有商品名称。这里先补一条占位档案，
    让表格 join 时至少能显示编号；之后再导入完整的 products.csv 时，
    `insert_products()` 会用真实名称覆盖占位记录。
    """
    if not sku_ids:
        return 0
    names = names or {}
    payload = [
        {
            "sku_id": str(sku),
            "sku_name": names.get(str(sku), ""),
            "category": "",
            "cost": 0.0,
            "price": 0.0,
        }
        for sku in sku_ids
    ]
    with get_conn() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO products (sku_id, sku_name, category, cost, price) "
            "VALUES (:sku_id, :sku_name, :category, :cost, :price)",
            payload,
        )
    return len(payload)


def insert_sales(rows: list[dict]) -> int:
    """批量写入销售数据。

    参数 rows 每项形如：
        {"order_id": "T0001", "ts": "2026-01-01 10:23", "sku_id": "S001",
         "qty": 2, "unit_price": 3.5}
    会自动补建不存在的交易头。
    """
    if not rows:
        return 0

    headers: dict[str, dict] = {}
    for r in rows:
        oid = r["order_id"]
        if oid not in headers:
            headers[oid] = {"order_id": oid, "ts": r["ts"], "total_amount": 0.0}
        headers[oid]["total_amount"] += r["qty"] * r["unit_price"]

    items = [
        {
            "order_id": r["order_id"],
            "sku_id": r["sku_id"],
            "qty": int(r["qty"]),
            "unit_price": float(r["unit_price"]),
        }
        for r in rows
    ]
    # 同一订单里同一个 SKU 只保留一行（重复导入或文件内重复都按覆盖处理）
    dedup = {(it["order_id"], it["sku_id"]): it for it in items}
    items = list(dedup.values())

    with get_conn() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO transactions (order_id, ts, total_amount) "
            "VALUES (:order_id, :ts, :total_amount)",
            list(headers.values()),
        )
        conn.executemany(
            "INSERT OR REPLACE INTO transaction_items (order_id, sku_id, qty, unit_price) "
            "VALUES (:order_id, :sku_id, :qty, :unit_price)",
            items,
        )
        # 大批量导入会改变数据分布，顺手刷新一下统计信息，
        # 否则后面的分析查询可能选到很差的执行计划（详见 analyze() 的说明）。
        if len(items) >= 2000:
            conn.execute("ANALYZE")
    return len(items)


def insert_inventory(rows: list[dict]) -> int:
    """批量写入库存快照。

    rows 每项含 sku_id / stock_qty，可选 snapshot_date、cost。
    snapshot_date 不传则用今天。
    """
    if not rows:
        return 0
    today = datetime.now().strftime("%Y-%m-%d")
    payload = [
        {
            "sku_id": r["sku_id"],
            "snapshot_date": r.get("snapshot_date", today),
            "stock_qty": float(r["stock_qty"]),
            "cost": float(r.get("cost", 0)),
        }
        for r in rows
    ]
    with get_conn() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO inventory (sku_id, snapshot_date, stock_qty, cost) "
            "VALUES (:sku_id, :snapshot_date, :stock_qty, :cost)",
            payload,
        )
    return len(payload)


def save_report(report_type: str, content: str, sample_size: int = 0, params: str = "") -> int:
    """保存一份分析报告，返回报告 ID。"""
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO reports (report_type, generated_at, sample_size, content, params) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                report_type,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                sample_size,
                content,
                params,
            ),
        )
        return int(cur.lastrowid)


# ---------------------------------------------------------------
# 读取
# ---------------------------------------------------------------
def fetch_sales(since: str | None = None) -> list[dict]:
    """读取销售明细。since 传 "2026-01-01" 可只取该日期之后的记录。"""
    sql = (
        "SELECT i.order_id, t.ts, i.sku_id, p.sku_name, p.category, "
        "       i.qty, i.unit_price "
        "FROM transaction_items i "
        "JOIN transactions t ON t.order_id = i.order_id "
        "LEFT JOIN products p ON p.sku_id = i.sku_id "
    )
    args: tuple = ()
    if since:
        sql += "WHERE t.ts >= ? "
        args = (since,)
    sql += "ORDER BY t.ts"

    with get_conn() as conn:
        return [dict(row) for row in conn.execute(sql, args)]


def fetch_inventory() -> list[dict]:
    """读取每个 SKU 的最新一条库存快照。"""
    sql = (
        "SELECT i.sku_id, p.sku_name, p.category, i.stock_qty, i.cost, i.snapshot_date "
        "FROM inventory i "
        "LEFT JOIN products p ON p.sku_id = i.sku_id "
        "WHERE i.snapshot_date = ("
        "    SELECT MAX(snapshot_date) FROM inventory WHERE sku_id = i.sku_id"
        ")"
    )
    with get_conn() as conn:
        return [dict(row) for row in conn.execute(sql)]


def fetch_reports(limit: int = 30) -> list[dict]:
    """读取历史报告列表，最新的在前。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT report_id, report_type, generated_at, sample_size, content "
            "FROM reports ORDER BY report_id DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in rows]


def fetch_products() -> list[dict]:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM products ORDER BY sku_id")]


# ---------------------------------------------------------------
# 配置
# ---------------------------------------------------------------
DEFAULT_CONFIG = {
    "replenish_days": "7",
    "lead_time_days": "3",
    "service_level": "0.95",
    "min_support": "0.010",
    "slow_turnover_days": "45",
    "model": "qwen3:4b",
}


def get_config() -> dict[str, str]:
    """读取全部配置，缺失的键用默认值补齐。"""
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM config").fetchall()
    cfg = dict(DEFAULT_CONFIG)
    cfg.update({r["key"]: r["value"] for r in rows})
    return cfg


def set_config(key: str, value: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, str(value))
        )


def set_configs(items: dict[str, str]) -> None:
    payload = [(k, str(v)) for k, v in items.items()]
    with get_conn() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", payload
        )


# ---------------------------------------------------------------
# 备份（对应需求 2.5「支持导出历史数据备份」）
# ---------------------------------------------------------------
def db_stats() -> dict:
    """统计当前数据库规模，用于界面展示与容量评估。

    返回形如：
        {"size_mb": 53.9, "transactions": 124476, "transaction_items": 319494,
         "inventory": 328500, "products": 300, "span_days": 1095, "total_rows": 772770}
    """
    result: dict = {}
    tables = ("products", "transactions", "transaction_items", "inventory", "reports")
    with get_conn() as conn:
        for t in tables:
            try:
                result[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except sqlite3.OperationalError:
                result[t] = 0
        row = conn.execute("SELECT MIN(ts), MAX(ts) FROM transactions").fetchone()
    if row and row[0] and row[1]:
        start = datetime.strptime(row[0][:10], "%Y-%m-%d")
        end = datetime.strptime(row[1][:10], "%Y-%m-%d")
        result["span_days"] = (end - start).days + 1
    else:
        result["span_days"] = 0
    result["total_rows"] = result["transactions"] + result["transaction_items"] + result["inventory"]
    result["size_mb"] = round(DB_PATH.stat().st_size / 1024 / 1024, 1) if DB_PATH.exists() else 0.0
    return result


def backup_to(target: Path) -> Path:
    """把整个数据库备份成一个文件。SQLite 官方推荐用 VACUUM INTO，安全且不锁库。"""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.execute("VACUUM INTO ?", (str(target),))
    return target


if __name__ == "__main__":
    init_db()
    print(f"数据库已初始化：{DB_PATH}")
