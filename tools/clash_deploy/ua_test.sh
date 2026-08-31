#!/bin/bash
# 不同UA拉订阅对比入口域名 + 交易臂恢复检查
NEW_URL="${SUBSCRIBE_URL:?环境变量缺失: export SUBSCRIBE_URL=<订阅地址>}"
mkdir -p /tmp/ua
for ua in "clash.meta" "clash-verge/v2.0.0" "ClashforWindows/0.20.39" "v2rayN/6.0" "sing-box" "Shadowrocket/2100"; do
  fn="/tmp/ua/$(echo $ua | tr '/.' '__').yaml"
  curl -sL -m 25 "$NEW_URL" -H "User-Agent: $ua" -o "$fn" || true
  sz=$(stat -c %s "$fn" 2>/dev/null || echo 0)
  servers=$(grep -oE "server: [^,}]+" "$fn" 2>/dev/null | awk '{print $2}' | sort -u | tr '\n' ' ')
  echo "UA=$ua size=$sz"
  echo "  servers: $servers"
done
echo
echo "== 交易臂恢复 =="
tail -n 3 /mnt/nvme/quanforge/logs/paper.log
echo ---
tail -n 3 /mnt/nvme/quanforge/logs/paper5.log
echo ---
tail -n 2 /mnt/nvme/quanforge/logs/bridge.log
