#!/bin/bash
D=/mnt/nvme/clash
PATCH='sed -i "s|external-controller: \x27127.0.0.1:9090\x27|external-controller: \x27:9090\x27|" "$CONFIG_FILE"'
sed -i "\|^CLASH_DIR=|i\\# 保面板可用: 订阅默认绑127.0.0.1, 改回全接口\n$PATCH" $D/update-subscribe.sh
grep -n "external-controller" $D/update-subscribe.sh && echo PATCH_OK

echo "--- Bybit连通性(经新节点) ---"
curl -sS -o /dev/null -w "api.bybit.com: %{http_code} %{time_total}s\n" -m 12 -x http://127.0.0.1:7890 https://api.bybit.com/v5/market/time
curl -sS -o /dev/null -w "stream.bybit.com: %{http_code} %{time_total}s\n" -m 12 -x http://127.0.0.1:7890 https://stream.bybit.com/v5/public/time

echo "--- 模拟盘重连状态 ---"
tail -3 /mnt/nvme/quanforge/logs/paper.log
echo ---
tail -3 /mnt/nvme/quanforge/logs/paper5.log
