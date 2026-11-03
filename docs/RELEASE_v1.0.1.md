# v1.0.1 — Windows / macOS 安装包

> 发布日期：2026-11-03
> 这是 v1.0.0 的打包版本：源码功能不变，新增 Windows 单文件 exe 与 macOS dmg。

## 📦 下载

| 平台 | 文件 | 说明 |
|---|---|---|
| Windows 10/11 x64 | `SmartWMS-Windows-x64.exe` | 免安装单文件，双击运行 |
| macOS Apple Silicon | `SmartWMS-macOS-arm64.dmg` | 打开后把 SmartWMS 拖进 Applications |

> 安装包不需要另外安装 Python。示例数据已内置，首次打开点「一键载入示例数据」即可。
> Ollama / qwen3:4b 仍然是可选项，不装也能使用全部统计与图表功能。

## 🖥 Windows 使用说明

1. 下载 `SmartWMS-Windows-x64.exe`；
2. 双击运行。若 SmartScreen 提示"未知发布者"，选择 **更多信息 → 仍要运行**；
3. 数据保存在 `%LOCALAPPDATA%\SmartWMS\app.db`；
4. 首次打开到「数据导入」页点「一键载入示例数据」。

## 🍎 macOS 使用说明

1. 下载 `SmartWMS-macOS-arm64.dmg`；
2. 双击打开，把 `SmartWMS` 拖进 `Applications`；
3. 首次打开如果提示"无法验证开发者"，右键 App → **打开**；
   或在终端执行：

```bash
xattr -dr com.apple.quarantine /Applications/SmartWMS.app
open /Applications/SmartWMS.app
```

4. 数据保存在 `~/Library/Application Support/SmartWMS/app.db`；
5. 当前 dmg 为 **Apple Silicon（arm64）** 版本；Intel Mac 请使用源码运行。

## 🔧 本版本改动

- 新增 PyInstaller 打包配置：`packaging/SmartWMS.spec`、`packaging/build_windows.bat`、`packaging/build_macos.sh`
- 新增跨平台路径模块 `app/paths.py`：
  - 打包后数据库写入用户数据目录，不写安装目录；
  - 示例数据和图标从 PyInstaller 资源目录读取；
  - matplotlib 缓存写入用户数据目录。
- 新增应用图标 `assets/icon.png` / `icon.ico` / `icon.icns`
- 新增 `.github/workflows/release.yml`，在 GitHub Actions 上构建并上传安装包
- README 增加下载入口

## ✅ 验证

- 源码测试：`53 passed`
- macOS 本机构建：`SmartWMS.app` 启动成功，自动创建 `app.db`，DMG 校验通过
- Windows 构建：由 GitHub Actions `windows-latest` 生成
- macOS 构建：由 GitHub Actions `macos-latest` 生成

## ⚠️ 已知限制

- Windows exe 未做代码签名，可能出现 SmartScreen 提示；
- macOS dmg 未做 Apple Developer 签名/公证，首次打开需右键打开；
- 当前只提供 Windows x64 与 macOS arm64，未提供 Linux 包；
- 应用内数据默认保存在用户目录，卸载程序不会自动删除数据。

## 📚 相关链接

- [README](https://github.com/SBTstudio/Intelligent_Warehousing/blob/main/README.md)
- [用户手册](https://github.com/SBTstudio/Intelligent_Warehousing/blob/main/docs/用户手册.md)
- [CHANGELOG](https://github.com/SBTstudio/Intelligent_Warehousing/blob/main/CHANGELOG.md)
