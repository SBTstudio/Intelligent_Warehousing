"""matplotlib 图表嵌入 Qt 的封装。

三张图分别对应需求 2.2.2 的可视化要求：
    · 销量折线图（单 SKU 近期走势）
    · 畅销 / 滞销柱状图
    · 商品关联 lift 热力图

中文字体在 Windows / macOS 上都要能正常显示，所以按常见字体族依次回退。
"""

from __future__ import annotations

import contextlib
import os

from app.paths import mpl_cache_dir

# 沙箱 / 只读 HOME 环境下 matplotlib 无法写 ~/.matplotlib，指定可写缓存目录
_CACHE = mpl_cache_dir()
os.environ.setdefault("MPLCONFIGDIR", str(_CACHE))

import matplotlib  # noqa: E402

matplotlib.use("QtAgg")

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from app.ui.theme import COLORS  # noqa: E402

# 中文字体配置：Windows 优先微软雅黑，macOS 优先苹方，Linux 用 Noto
matplotlib.rcParams["font.sans-serif"] = [
    "PingFang SC",
    "Hiragino Sans GB",
    "Arial Unicode MS",
    "Microsoft YaHei",
    "SimHei",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "DejaVu Sans",
]
matplotlib.rcParams["axes.unicode_minus"] = False
matplotlib.rcParams["font.size"] = 9


class ChartCanvas(FigureCanvas):
    """可直接 addWidget 到布局里的图表画布。"""

    def __init__(self, parent=None, width=6.0, height=3.6, dpi=100):
        self.figure = Figure(figsize=(width, height), dpi=dpi, facecolor="#FFFFFF")
        super().__init__(self.figure)
        self.setParent(parent)
        self.axes = self.figure.add_subplot(111)
        self._colorbar = None
        self._style_axes()

    def _style_axes(self) -> None:
        self.axes.set_facecolor("#FFFFFF")
        for spine in self.axes.spines.values():
            spine.set_color(COLORS["border"])
        self.axes.tick_params(colors=COLORS["muted"], labelsize=8)
        self.axes.title.set_color(COLORS["ink"])

    def _clear(self, title: str = ""):
        if self._colorbar is not None:
            with contextlib.suppress(Exception):
                self._colorbar.remove()
            self._colorbar = None
        self.axes.clear()
        self._style_axes()
        if title:
            self.axes.set_title(title, fontsize=11, pad=10, loc="left")

    def draw_empty(self, message: str = "暂无数据") -> None:
        """没有数据时也不要留一块空白画布。"""
        self._clear("")
        self.axes.text(
            0.5,
            0.5,
            message,
            ha="center",
            va="center",
            fontsize=11,
            color=COLORS["muted"],
            transform=self.axes.transAxes,
        )
        self.axes.set_xticks([])
        self.axes.set_yticks([])
        for spine in self.axes.spines.values():
            spine.set_visible(False)
        self.draw()

    def draw_line(self, x, y, title="销量趋势", xlabel="日期", ylabel="销量"):
        """画折线图 —— 用于 SKU 销量走势（需求 2.1 输入量 2）。"""
        self._clear(title)
        if len(x) == 0:
            self.draw_empty("暂无销售数据")
            return
        self.axes.plot(
            x,
            y,
            marker="o",
            markersize=2.5,
            linewidth=1.4,
            color=COLORS["green"],
            markerfacecolor=COLORS["green"],
        )
        self.axes.fill_between(x, y, color=COLORS["green"], alpha=0.08)
        self.axes.set_xlabel(xlabel, fontsize=9, color=COLORS["muted"])
        self.axes.set_ylabel(ylabel, fontsize=9, color=COLORS["muted"])
        self.axes.grid(True, axis="y", alpha=0.25, linewidth=0.6)
        if len(x) > 2:
            self.figure.autofmt_xdate(rotation=30)
        self.figure.tight_layout()
        self.draw()

    def draw_bar(self, labels, values, title="畅销 / 滞销对比", color="#378ADD"):
        """画柱状图 —— 用于畅销滞销商品对比。"""
        self._clear(title)
        if not labels:
            self.draw_empty("暂无商品数据")
            return
        self.axes.bar(range(len(labels)), values, color=color, width=0.62)
        self.axes.set_xticks(range(len(labels)))
        self.axes.set_xticklabels(labels, rotation=32, ha="right", fontsize=8)
        self.axes.set_ylabel("销售额（元）", fontsize=9, color=COLORS["muted"])
        self.axes.grid(True, axis="y", alpha=0.25, linewidth=0.6)
        self.figure.tight_layout()
        self.draw()

    def draw_bar_colors(self, labels, values, colors, title="畅销 / 滞销对比"):
        """带颜色的柱状图：畅销绿、正常蓝、滞销橙、呆滞红。"""
        self._clear(title)
        if not labels:
            self.draw_empty("暂无商品数据")
            return
        bars = self.axes.bar(range(len(labels)), values, width=0.62)
        for bar, color in zip(bars, colors):
            bar.set_color(color)
        self.axes.set_xticks(range(len(labels)))
        self.axes.set_xticklabels(labels, rotation=32, ha="right", fontsize=8)
        self.axes.set_ylabel("销售额（元）", fontsize=9, color=COLORS["muted"])
        self.axes.grid(True, axis="y", alpha=0.25, linewidth=0.6)
        self.figure.tight_layout()
        self.draw()

    def draw_heatmap(self, matrix, labels, title="商品关联度（lift）", cmap="YlGn"):
        """画热力图 —— 用于展示 lift 矩阵。"""
        self._clear(title)
        if not matrix or not labels:
            self.draw_empty("暂无关联规则")
            return
        im = self.axes.imshow(matrix, cmap=cmap, aspect="auto", vmin=0.5, vmax=max(2.0, max(max(row) for row in matrix)))
        self.axes.set_xticks(range(len(labels)))
        self.axes.set_xticklabels(labels, rotation=40, ha="right", fontsize=8)
        self.axes.set_yticks(range(len(labels)))
        self.axes.set_yticklabels(labels, fontsize=8)
        self._colorbar = self.figure.colorbar(im, ax=self.axes, shrink=0.86, pad=0.02)
        self._colorbar.ax.tick_params(labelsize=8, colors=COLORS["muted"])
        self._colorbar.outline.set_edgecolor(COLORS["border"])
        self.figure.tight_layout()
        self.draw()
