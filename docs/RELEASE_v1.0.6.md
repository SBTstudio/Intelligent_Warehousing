# v1.0.6 — SKU 删除 / 恢复

> 发布日期：2026-11-17
> 现在可以在「实时库存」里直接删除不再使用的 SKU，同时保留历史销售数据。

## ✨ 本版本重点

### 1. 删除 SKU

- 打开「实时库存」；
- 在「当前库存」表格找到要删除的商品；
- 点该行「删除」，确认即可；
- 删除后商品从库存、收银台、补货页隐藏。

### 2. 历史不丢

删除采用软删除：

- `transaction_items` 里的历史销售保留；
- `inventory_events` 里的库存流水保留；
- 历史报表仍然能显示商品名称；
- 不会因为删除商品导致旧订单变成空名称。

### 3. 可以恢复

以后重新在「实时库存」保存同一个商品编号：

- 商品会重新启用；
- 可以重新填写名称、进价、售价、库存；
- 历史数据和新的营业数据继续累计。

### 4. 其他

- `products` 新增 `is_active` 字段，旧数据库启动时自动迁移；
- 商品列表、收银台、补货页只显示未删除商品；
- 新增删除/恢复测试，总计 **79 passed**。

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

- `pytest`：**79 passed**
- 新增 1 个删除/恢复测试
- GitHub Actions：Python 3.10 / 3.12 均通过
- Windows / macOS 安装包由 Actions 构建并上传

## ⚠️ 说明

- 删除是软删除，不会物理删除数据库行；
- 如果需要彻底清理，可在备份后手动执行 SQL；
- 安装包未做商业代码签名，首次打开有系统提示；
- macOS dmg 为 Apple Silicon（arm64）版本。

## 📚 相关链接

- [README](https://github.com/SBTstudio/Intelligent_Warehousing/blob/main/README.md)
- [用户手册](https://github.com/SBTstudio/Intelligent_Warehousing/blob/main/docs/用户手册.md)
- [CHANGELOG](https://github.com/SBTstudio/Intelligent_Warehousing/blob/main/CHANGELOG.md)
