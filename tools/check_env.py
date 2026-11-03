"""环境自检脚本 —— 一次性确认这台机器能不能跑起本项目。

双击 run_check.bat 或执行：
    .venv\\Scripts\\python.exe tools\\check_env.py

它会逐项检查并给出明确的 ✅ / ❌ 和修复建议。
环境出问题时先跑这个，比逐个试要快得多。
"""

from __future__ import annotations

import importlib
import json
import platform
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

OK = "[OK]  "
BAD = "[!!]  "
WARN = "[?]   "

OLLAMA_HOST = "http://127.0.0.1:11434"

# 依赖包 -> 用途说明
REQUIRED = {
    "PySide6": "桌面界面（Qt 的 Python 版）",
    "pandas": "读 CSV、做数据清洗与透视",
    "numpy": "数值计算（均值、标准差、矩阵）",
    "matplotlib": "图表绘制，嵌入界面显示",
    "requests": "调用本地大模型的 HTTP 接口",
    "pytest": "单元测试框架",
}


def line(title: str) -> None:
    print("\n" + "-" * 60)
    print(title)
    print("-" * 60)


def check_python() -> bool:
    line("1. Python 解释器")
    print(f"  版本    : {sys.version.split()[0]}")
    print(f"  路径    : {sys.executable}")
    print(f"  虚拟环境: {sys.prefix != sys.base_prefix}")

    ok = True
    if sys.version_info < (3, 10):
        print(BAD + "版本过低，本项目需要 Python 3.10 以上（推荐 3.12）")
        ok = False
    elif sys.version_info >= (3, 14):
        print(WARN + "版本过新，部分第三方库可能还没有对应的安装包，建议用 3.12")
    else:
        print(OK + "版本合适")

    if sys.prefix == sys.base_prefix:
        print(WARN + "当前不在虚拟环境里。建议用项目内的 .venv（依赖已装好）")
    else:
        print(OK + "运行在虚拟环境中")
    return ok


def check_packages() -> bool:
    line("2. 依赖包")
    all_ok = True
    for mod, purpose in REQUIRED.items():
        try:
            m = importlib.import_module(mod)
            ver = getattr(m, "__version__", "?")
            print(f"  {OK}{mod:<12s} {ver:<12s} {purpose}")
        except ImportError:
            print(f"  {BAD}{mod:<12s} {'未安装':<12s} {purpose}")
            all_ok = False
    if not all_ok:
        print("\n  修复：pip install -r requirements.txt")
    return all_ok


def check_ollama_installed() -> str | None:
    line("3. Ollama 是否安装")
    exe = shutil.which("ollama")
    if exe:
        print(f"  {OK}已安装，命令位置：{exe}")
        try:
            out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10)
            print(f"      {out.stdout.strip() or out.stderr.strip()}")
        except Exception as e:
            print(f"      （读取版本失败：{e}）")
        return exe

    candidates = [
        Path("/Applications/Ollama.app/Contents/Resources/ollama"),
        Path.home() / "Applications" / "Ollama.app" / "Contents" / "Resources" / "ollama",
        Path("/usr/local/bin/ollama"),
        Path("/opt/homebrew/bin/ollama"),
        Path("/usr/bin/ollama"),
        Path.home() / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe",
        Path("C:/Program Files/Ollama/ollama.exe"),
    ]
    for c in candidates:
        if c.exists():
            print(f"  {OK}已安装在 {c}（只是没加进 PATH，不影响使用）")
            return str(c)

    print(WARN + "没有找到 Ollama（不影响统计功能，只影响智能报告）")
    if platform.system() == "Windows":
        print("      到 https://ollama.com 下载安装包，装完执行 ollama pull qwen3:4b")
    elif platform.system() == "Darwin":
        print("      到 https://ollama.com 下载 macOS 安装包，或执行 brew install ollama")
    else:
        print("      执行 curl -fsSL https://ollama.com/install.sh | sh")
    return None


def check_ollama_service() -> bool:
    line("4. Ollama 服务")
    try:
        with urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
        models = data.get("models", [])
        if not models:
            print(WARN + "服务在跑，但一个模型都没有")
            print("      下一步：ollama pull qwen3:4b")
            return True
        print(f"  {OK}服务正常，已装 {len(models)} 个模型：")
        for m in models:
            size_gb = m.get("size", 0) / 1024**3
            print(f"      - {m.get('name', '?'):<20s} {size_gb:5.2f} GB")
        return True
    except urllib.error.URLError:
        print(BAD + "连不上 " + OLLAMA_HOST)
        print("      原因通常有两个：① Ollama 没安装；② 装了但服务没启动")
        print("      修复：开始菜单里打开 Ollama，或命令行执行 ollama serve")
        return False
    except Exception as e:
        print(BAD + f"请求出错：{e}")
        return False


def check_model_ready(model: str = "qwen3:4b") -> None:
    line("5. 模型能否真正调用")
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": "只回复两个字：正常"}],
            "stream": False,
            "format": "json",
            "options": {"num_predict": 40, "temperature": 0.1},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/chat", data=payload, headers={"Content-Type": "application/json"}
    )
    import time

    try:
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read().decode("utf-8"))
        dt = time.perf_counter() - t0
        answer = str(resp.get("message", {}).get("content", "")).strip()
        print(f"  {OK}模型响应正常，耗时 {dt:.1f} 秒")
        print(f"      模型回答：{answer[:120]}")
        print("      这组数字就是设计「超时与降级」的真实依据")
    except Exception as e:
        print(f"  {WARN}调用未成功：{e}")
        print(f"      先确认已经执行过：ollama pull {model}")


def check_data_and_db() -> None:
    line("6. 项目数据")
    for name in ("receipts.csv", "products.csv", "inventory.csv", "receipts_dirty.csv"):
        p = ROOT / "data" / "sample" / name
        print(f"  {OK if p.exists() else BAD}{name}")

    db = ROOT / "data" / "app.db"
    if db.exists():
        try:
            sys.path.insert(0, str(ROOT))
            from app.db import schema

            st = schema.db_stats()
            print(f"  {OK}数据库可打开  {st['size_mb']} MB，"
                  f"明细 {st['transaction_items']} 行，跨度 {st['span_days']} 天")
        except Exception as e:
            print(f"  {WARN}数据库打开出错：{e}")
    else:
        print(f"  {WARN}数据库还没建，首次启动程序时会自动创建")


def main() -> int:
    print("=" * 60)
    print("  智能仓储管理系统 —— 环境自检")
    print("=" * 60)

    results = [check_python(), check_packages()]
    exe = check_ollama_installed()
    if exe:
        check_ollama_service()
        check_model_ready()
    check_data_and_db()

    line("总结")
    if all(results):
        print(OK + "环境正常，统计与补货功能可以直接使用。")
        print("      下一步：python -m pytest -q && python main.py")
        print("      首次运行请在「数据导入」页点击「一键载入示例数据」。")
    else:
        print(BAD + "还有项目没配好，按上面的提示逐个处理。")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
