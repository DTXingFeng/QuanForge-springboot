#!/bin/bash
# 一次性: 预览校验新订阅 -> 备份 -> 安装 -> 重启 -> 验证
set -e
NEW_URL="https://suu.sujieok.cn/SUB_PATH?token=REDACTED"
D=/mnt/nvme/clash
TS=$(date +%Y%m%d%H%M%S)

echo "== 1) 备份 =="
cp $D/update-subscribe.sh $D/update-subscribe.sh.backup.$TS
cp $D/start-clash.sh $D/start-clash.sh.backup.$TS
cp $D/config.yaml $D/config.yaml.backup-beforesujie.$TS
echo "备份后缀: .$TS"

echo "== 2) 预览下载新订阅(经当前代理) =="
curl -sL "$NEW_URL" -H "User-Agent: clash-meta" -x http://127.0.0.1:7890 \
    --connect-timeout 20 -m 60 -o $D/config.yaml.new || true
if ! grep -qE "^(proxies|proxy-providers):" $D/config.yaml.new 2>/dev/null; then
  echo "(代理通道失败, 直连重试)"
  curl -sL "$NEW_URL" -H "User-Agent: clash-meta" --connect-timeout 20 -m 60 -o $D/config.yaml.new || true
fi
grep -qE "^(proxies|proxy-providers):" $D/config.yaml.new || {
  echo "FATAL: 新订阅不是clash格式, 原样头部:"; head -c 300 $D/config.yaml.new; exit 1; }

echo "-- 关键行(打补丁前) --"
grep -nE "^(port|socks-port|mixed-port|external-controller|mode|log-level)" $D/config.yaml.new || true
echo "-- 节点数: $(grep -cE "^\s+- (name|\{)" $D/config.yaml.new) --"
echo "-- 前6个节点名 --"
grep -oE "name: [^,}]+" $D/config.yaml.new | head -n 6 || true

echo "== 3) 补丁: 端口7890 + controller全接口 =="
if grep -q "^mixed-port:" $D/config.yaml.new; then
  sed -i "s|^mixed-port: .*|mixed-port: 7890|" $D/config.yaml.new
elif grep -q "^port:" $D/config.yaml.new; then
  sed -i "s|^port: .*|port: 7890|" $D/config.yaml.new
else
  sed -i "1i mixed-port: 7890" $D/config.yaml.new
fi
sed -i "s|external-controller: '127.0.0.1:9090'|external-controller: ':9090'|; \
        s|external-controller: 127.0.0.1:9090|external-controller: :9090|" $D/config.yaml.new
grep -nE "^(port|mixed-port|external-controller)" $D/config.yaml.new

echo "== 4) 安装脚本+配置 =="
ls -la $D/update-subscribe.sh $D/start-clash.sh | awk '{print $1, $NF}'
grep -h "^SUBSCRIBE_URL" $D/update-subscribe.sh $D/start-clash.sh
cp $D/config.yaml.new $D/config.yaml

echo "== 5) 重启 =="
sudo -n systemctl restart clash
sleep 4
echo "clash: $(systemctl is-active clash)"

echo "== 6) 验证 =="
curl -sS -o /dev/null -w "api.bybit.com经代理: %{http_code} %{time_total}s\n" \
    -m 15 -x http://127.0.0.1:7890 https://api.bybit.com/v5/market/time
curl -s -m 5 http://127.0.0.1:9090/proxies | python3 -c "
import json,sys
d=json.load(sys.stdin)['proxies']
for k,v in sorted(d.items()):
    if v.get('type') in ('Selector','URLTest','Fallback'):
        print(k,'->',v.get('now'))
print('节点总数:', sum(1 for v in d.values() if v.get('type') not in ('Selector','URLTest','Fallback','Direct','Reject')))
"
