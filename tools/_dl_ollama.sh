#!/bin/bash
# 带 断点续传 + 无限重试 的下载循环，直到文件完整
URL="https://gh-proxy.com/https://github.com/ollama/ollama/releases/latest/download/OllamaSetup.exe"
TARGET="/c/Users/awrzs/Downloads/OllamaSetup.exe"
EXPECTED=1581967176

for i in $(seq 1 60); do
  size=$(stat -c%s "$TARGET" 2>/dev/null || echo 0)
  if [ "$size" -ge "$EXPECTED" ]; then
    echo "DOWNLOAD_COMPLETE size=$size"
    exit 0
  fi
  echo "attempt $i : 已有 $size / $EXPECTED 字节，续传中..."
  curl -sL -C - --max-time 240 -o "$TARGET" "$URL"
  rc=$?
  size=$(stat -c%s "$TARGET" 2>/dev/null || echo 0)
  echo "attempt $i 结束 rc=$rc size=$size"
  if [ "$size" -ge "$EXPECTED" ]; then
    echo "DOWNLOAD_COMPLETE size=$size"
    exit 0
  fi
  sleep 2
done
echo "DOWNLOAD_FAILED"
exit 1
