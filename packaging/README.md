# 打包说明

## Windows x64

在 Windows 上双击项目根目录的 `安装环境.bat`，然后：

```bat
packaging\build_windows.bat
```

输出：`dist\SmartWMS.exe`（单文件、无控制台窗口）。

## macOS Apple Silicon

```bash
./packaging/build_macos.sh
```

输出：

- `dist/SmartWMS.app`
- `dist/SmartWMS-macOS-arm64.dmg`

脚本会做 ad-hoc 签名，但没有 Apple Developer 证书和公证；
首次打开需要右键 App → 打开，或执行：

```bash
xattr -dr com.apple.quarantine /Applications/SmartWMS.app
```

## GitHub Actions

`.github/workflows/release.yml` 可在 `windows-latest` 和 `macos-latest` 上分别构建，
并把 exe / dmg 上传到指定 Release：

```text
Actions → release-packages → Run workflow → 输入 tag（如 v1.0.3）
```

## 数据目录

打包后不会往安装目录写文件：

| 系统 | 数据库 |
|---|---|
| Windows | `%LOCALAPPDATA%\SmartWMS\app.db` |
| macOS | `~/Library/Application Support/SmartWMS/app.db` |
| Linux | `~/.local/share/SmartWMS/app.db` |

示例数据、图标等只读资源从 PyInstaller 的 `_MEIPASS` 读取。
