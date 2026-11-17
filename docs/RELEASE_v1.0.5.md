# v1.0.5 — 收银台改进 + 应用内更新

> 发布日期：2026-11-17
> 收银台可以像收银机一样从商品列表选货加入小票，软件内也能直接检查并下载新版本。

## ✨ 本版本重点

### 1. 收银台手动选商品

- 商品列表新增「操作」列，每行有「加入」按钮；
- 单击商品行选中后，点「加入选中商品」；
- 双击商品行仍然可以直接加入；
- 同一 SKU 自动合并数量，结账时生成一张完整订单。

### 2. 应用内检查更新

首页新增「检查更新」按钮：

1. 查询 GitHub 最新 Release；
2. 比较当前版本与最新版本；
3. 发现新版本时显示更新说明；
4. 确认后下载当前平台的 exe / dmg；
5. 下载完成自动打开安装包，按系统提示覆盖安装。

### 3. 其他

- 首页提示显示当前版本号；
- 更新失败、网络不可用时会显示具体错误，不影响正常营业；
- 安装包保存在用户数据目录的 `updates/` 下。

## 📦 下载

| 平台 | 文件 | 说明 |
|---|---|---|
| Windows 10/11 x64 | `SmartWMS-Windows-x64.exe` | 免安装单文件 |
| macOS Apple Silicon | `SmartWMS-macOS-arm64.dmg` | 打开后拖进 Applications |

### Windows

1. 双击 `SmartWMS-Windows-x64.exe`；
2. SmartScreen 提示时选择「更多信息 → 仍要运行」；
3. 数据保存在 `%LOCALAPPDATA%\SmartWMS\app.db`。

### macOS

1. 双击 dmg，把 `SmartWMS` 拖进 `Applications`；
2. 首次打开若提示无法验证开发者，右键 App →「打开」，或执行：

```bash
xattr -dr com.apple.quarantine /Applications/SmartWMS.app
open /Applications/SmartWMS.app
```

3. 数据保存在 `~/Library/Application Support/SmartWMS/app.db`。

## ✅ 验证

- `pytest`：**78 passed**
- 新增 5 个更新模块测试
- GitHub Actions：Python 3.10 / 3.12 均通过
- Windows / macOS 安装包由 Actions 构建并上传

## ⚠️ 已知限制

- 应用内更新需要能访问 GitHub API；公司网络限制时可手动到 Release 下载；
- 更新下载的是安装包，macOS 仍需把 App 拖进 Applications 覆盖旧版本；
- 安装包未做商业代码签名，首次打开有系统提示；
- macOS dmg 为 Apple Silicon（arm64）版本。

## 📚 相关链接

- [README](https://github.com/SBTstudio/Intelligent_Warehousing/blob/main/README.md)
- [用户手册](https://github.com/SBTstudio/Intelligent_Warehousing/blob/main/docs/用户手册.md)
- [CHANGELOG](https://github.com/SBTstudio/Intelligent_Warehousing/blob/main/CHANGELOG.md)
