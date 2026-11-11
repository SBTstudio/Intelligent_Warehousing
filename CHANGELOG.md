# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [1.0.2] - 2026-11-11

新增第三方 OpenAI 兼容 API，作为 Ollama 本地模型的显式可选替代。

### Added

- `app/llm/client.py` 支持两种模型来源：
  - Ollama 本地模型（默认，数据不出本机）
  - 第三方 OpenAI 兼容 API（DeepSeek / 通义千问 / OpenAI / Moonshot 等）
- 第三方 API 适配：
  - `POST {base_url}/chat/completions`，Bearer Key；
  - JSON 任务使用 `response_format`，不支持时自动去掉重试；
  - 支持 `401/403/429/404/超时/连接失败` 分类提示。
- 「参数配置」页新增模型来源、Base URL、API 模型名、API Key、请求超时、
  「测试连接」按钮和隐私提示。
- 支持环境变量 `SMARTWMS_API_KEY` 覆盖数据库中的 Key。
- `pytest` 新增 8 个第三方 API 用例，总数 61。

### Changed

- 状态栏、报告页、健康检查按当前模型来源显示"本地模型"或"第三方 API"。
- 第三方 API 只接收算法层聚合摘要，不上传原始 CSV / 数据库。
- 版本号更新到 v1.0.2。

### Security

- 默认仍为本地 Ollama，不联网；
- 第三方 API 必须由用户显式切换；
- API Key 可保存在本机 SQLite，也可用环境变量避免落盘。

## [1.0.1] - 2026-11-03

打包版本：源码功能与 1.0.0 一致，新增 Windows exe 与 macOS dmg。

### Added

- PyInstaller 打包配置：`packaging/SmartWMS.spec`、`packaging/build_windows.bat`、`packaging/build_macos.sh`
- 跨平台路径模块 `app/paths.py`：打包后数据库写入用户数据目录，示例数据从 `_MEIPASS` 读取
- 应用图标 `assets/icon.png` / `icon.ico` / `icon.icns`
- GitHub Actions `release-packages` 工作流：在 Windows / macOS runner 上构建并上传 Release 资产
- README 直接下载入口

### Changed

- 数据库默认位置：源码运行仍在 `data/app.db`；安装包改为
  `%LOCALAPPDATA%\SmartWMS\app.db` / `~/Library/Application Support/SmartWMS/app.db`
- matplotlib 缓存改为用户数据目录

### Builds

- `SmartWMS-Windows-x64.exe`（Windows 10/11 x64，单文件）
- `SmartWMS-macOS-arm64.dmg`（Apple Silicon）

## [1.0.0] - 2026-11-03

首个完整版本。五个功能页面全部接线，算法 / 数据 / LLM / 界面均有测试或手工验收覆盖。

### Added

- **数据导入（M1）**：CSV/TXT 编码自动识别（UTF-8 / GBK）、列名同义词映射、
  逐行校验、错误行号提示、原始文件只读；一键载入示例数据。
- **购物篮分析（M3）**：手写 Apriori、支持度 / 置信度 / lift、lift 热力图；
  示例数据 7 组埋入关系全部挖出。
- **补货预测（M4）**：指数平滑、需求波动、安全库存、补货点、剩余天数、
  建议补货日与建议量；紧急行标红。
- **畅销 / 滞销（M5）**：ABC × XYZ 交叉分类、周转天数、四档判定。
- **可视化（M6）**：日销量折线图、销售额 TOP10 柱状图、商品关联热力图。
- **本地 LLM（M7/M8）**：Ollama 原生 `/api/chat`、`format=json`、
  `num_predict` 限长、JSON 容错、超时 / 连接失败 / 模型缺失三层降级。
- **五类报告**：经营周报、滞销归因、陈列建议、换季推荐、热点映射。
- **参数配置（M9）**：补货周期、提前期、服务水平、最小支持度、滞销阈值、
  模型档位；落库并在重启后回填。
- **历史报告（M10）**：报告保存与下拉回看。
- **数据备份（M11）**：`VACUUM INTO` 单文件备份。
- **换季趋势（M12）**：同比、环比、趋势斜率、季节指数、换季推荐。
- **热点映射（M13）**：热点文本 → 品类映射，模型不可用时关键词兜底。
- **测试**：53 个 pytest 用例（算法 16 / 数据层 8 / 导入 11 / 季节 7 / LLM 11）。
- **文档**：需求分析、概要设计、用户手册、测试报告、开发复盘、Release Notes。

### Changed

- 界面统一为低饱和"纸张 + 墨绿"主题，统一状态胶囊、表格、图表样式。
- 分析类操作放入 `QThread`，避免 Apriori / LLM 调用阻塞主线程。
- 主窗口增加数据库规模、模型状态、页面间信号联动。
- `README` 重写为 GitHub 落地页，补充架构、算法、性能与截图。

### Fixed

- 修复大数据量下 Apriori 候选计数过慢的问题（改为枚举篮子内子集）。
- 修复重复导入导致明细膨胀的问题（唯一索引 + 幂等写入）。
- 修复 matplotlib 中文字体与 macOS 只读 HOME 缓存问题。
- 修复 SQLite 缺少统计信息时执行计划退化的问题（自动 `ANALYZE`）。

### Known limitations

- M14 客户画像未实现，需要真实会员 ID 与跨月购买记录。
- 暂未提供手动逐行录入（需求 2.4.3 的另一半）。
- 暂未打包 exe / dmg。
- 示例数据日销量波动较大，XYZ 分类多为 Z；文档中已说明。

[1.0.2]: https://github.com/SBTstudio/Intelligent_Warehousing/releases/tag/v1.0.2
[1.0.1]: https://github.com/SBTstudio/Intelligent_Warehousing/releases/tag/v1.0.1
[1.0.0]: https://github.com/SBTstudio/Intelligent_Warehousing/releases/tag/v1.0.0
