#!/bin/bash
# 重新生效新订阅: 重装两个v3脚本(直连优先+新URL) + 好域名配置 + 重启 + 验证
set -e
D=/mnt/nvme/clash

echo "== 1) 校验v3脚本内容 =="
grep -h "^SUBSCRIBE_URL" $D/update-subscribe.sh $D/start-clash.sh | sed 's|/wm4.*|/wm4***|'
grep -c "直连优先\|直连" $D/update-subscribe.sh $D/start-clash.sh || true

echo "== 2) 重装好域名配置 =="
cp $D/config.yaml.new $D/config.yaml
grep -nE "^(mixed-port|external-controller)" $D/config.yaml
grep -oE "server: [^,}]+" $D/config.yaml | awk '{print $2}' | sort -u | head -n 5

echo "== 3) 重启 =="
sudo -n systemctl restart clash
sleep 6
echo "clash: $(systemctl is-active clash)"

echo "== 4) 验证 =="
sleep 4
curl -s -m 5 http://127.0.0.1:9090/proxies | python3 -c "
import json,sys
d=json.load(sys.stdin)['proxies']
for k,v in sorted(d.items()):
    if v.get('type') in ('Selector','URLTest','Fallback'):
        print(' ',k,'->',v.get('now'))
"
for i in 1 2 3; do
  curl -sS -o /dev/null -w "api#$i: %{http_code} %{time_total}s | " -m 15 -x http://127.0.0.1:7890 https://api.bybit.com/v5/market/time || echo -n "api#$i FAIL | "
  curl -sS -o /dev/null -w "stream#$i: %{http_code} %{time_total}s\n" -m 15 -x http://127.0.0.1:7890 https://stream.bybit.com/v5/public/time || echo "stream#$i FAIL"
done
echo "== 5) 交易臂 =="
tail -n 2 /mnt/nvme/quanforge/logs/paper.log
echo ---
tail -n 2 /mnt/nvme/quanforge/logs/paper5.log
