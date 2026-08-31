#!/bin/bash
# 回滚到旧订阅恢复代理 -> 借旧代理境外DoH解析新机场入口域名
set -e
D=/mnt/nvme/clash
OLD_URL="${SUBSCRIBE_URL:?环境变量缺失: export SUBSCRIBE_URL=<订阅地址>}"

echo "== 1) 恢复旧订阅配置 =="
cp $D/config.yaml.backup-beforesujie.20260823131056 $D/config.yaml
grep -nE "^(port|mixed-port|external-controller)" $D/config.yaml || true

echo "== 2) 脚本URL切回旧订阅(保留v2脚本逻辑) =="
sed -i "s|^SUBSCRIBE_URL=.*|SUBSCRIBE_URL=\"$OLD_URL\"|" $D/update-subscribe.sh $D/start-clash.sh
grep -h "^SUBSCRIBE_URL" $D/update-subscribe.sh $D/start-clash.sh | sed 's/token=.*/token=***/'

echo "== 3) 重启 =="
sudo -n systemctl restart clash
sleep 6
echo "clash: $(systemctl is-active clash)"
curl -sS -o /dev/null -w "api.bybit.com经旧代理: %{http_code} %{time_total}s\n" \
    -m 20 -x http://127.0.0.1:7890 https://api.bybit.com/v5/market/time || true

echo "== 4) 经旧代理查新机场入口域名(境外DoH) =="
for T in a-node.ddqo.blog b-node.ddqo.blog; do
  for u in "https://1.1.1.1/resolve" "https://dns.google/resolve" "https://9.9.9.9/resolve"; do
    R=$(curl -s -m 12 -x http://127.0.0.1:7890 "$u?name=$T&type=A" 2>/dev/null | \
        python3 -c "import json,sys
try:
  d=json.load(sys.stdin)
  ips=[a['data'] for a in d.get('Answer',[]) if a.get('type')==1]
  print(d.get('Status'), ips)
except Exception as e:
  print('parse-fail')" 2>/dev/null)
    echo "$T @ $u -> ${R:-FAIL}"
  done
done

echo "== 5) 交易臂恢复情况 =="
tail -n 2 /mnt/nvme/quanforge/logs/paper.log
tail -n 2 /mnt/nvme/quanforge/logs/paper5.log
