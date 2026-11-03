#!/usr/bin/env bash
# 在 macOS 上构建 SmartWMS.app 和 dmg
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -x ".venv/bin/python" ]; then
  echo "缺少 .venv，请先创建并安装依赖"
  exit 1
fi

if ! .venv/bin/pyinstaller --version >/dev/null 2>&1; then
  .venv/bin/python -m pip install -r requirements-build.txt
fi
rm -rf build dist
.venv/bin/pyinstaller --noconfirm --clean packaging/SmartWMS.spec

# 临时签名，减少“已损坏”提示；正式发布可换成开发者证书
codesign --force --deep --sign - "dist/SmartWMS.app" 2>/dev/null || true

# 制作带 Applications 快捷方式的 dmg
rm -rf dist/dmg
mkdir -p dist/dmg
cp -R "dist/SmartWMS.app" "dist/dmg/"
ln -s /Applications "dist/dmg/Applications"
hdiutil create -volname "SmartWMS" -srcfolder "dist/dmg" -ov -format UDZO \
  "dist/SmartWMS-macOS-arm64.dmg"
echo "完成：dist/SmartWMS.app  dist/SmartWMS-macOS-arm64.dmg"
