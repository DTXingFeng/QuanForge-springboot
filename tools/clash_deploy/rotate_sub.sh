#!/bin/bash
# 订阅token轮换: 换URL -> 直连预览校验 -> 装配 -> 重启 -> 验证
set -e
NEW_URL="${SUBSCRIBE_URL:?需要环境变量 SUBSCRIBE_URL(真实token只存Pi, 不入库)}"
D=/mnt/nvme/clash
TS=$(date +%Y%m%d%H%M%S)

echo "== 1) 换脚本URL =="
sed -i "s|^SUBSCRIBE_URL=.*|SUBSCRIBE_URL=\"$NEW_URL\"|" $D/update-subscribe.sh $D/start-clash.sh
grep -h "^SUBSCRIBE_URL" $D/update-subscribe.sh $D/start-clash.sh | sed 's|token=.*|token=***|'

echo "== 2) 直连预览下载(不经代理, 拿正确地域批次) =="
curl -sL "$NEW_URL" -H "User-Agent: clash.meta" --connect-timeout 20 -m 60 -o $D/config.yaml.new
grep -qE "^(proxies|proxy-providers):" $D/config.yaml.new || {
  echo "FATAL: 非clash格式"; head -c 200 $D/config.yaml.new; exit 1; }
echo "节点数: $(grep -cE "^\s+- \{ name" $D/config.yaml.new)"

echo "== 3) 节点域名解析校验(阿里DoH) =="
DOMAINS=$(grep -oE "server: [a-z0-9.\-]+" $D/config.yaml.new | awk '{print $2}' | sort -u)
OK=0
for d in $DOMAINS; do
  R=$(curl -s -m 6 "https://223.5.5.5/resolve?name=$d&type=A" | python3 -c "
import json,sys
try:
  j=json.load(sys.stdin)
  ips=[a['data'] for a in j.get('Answer',[]) if a.get('type')==1]
  print(j.get('Status'), ips[:1])
except: print('FAIL')" 2>/dev/null)
  echo "  $d -> $R"
  echo "$R" | grep -q "0 \[" && echo "$R" | grep -qv "\[\]" && OK=1 || true
done
[ $OK -eq 1 ] || { echo "FATAL: 全部域名不可解析, 放弃切换(现行配置未动)"; exit 1; }

echo "== 4) 补丁+装配 =="
cp $D/config.yaml $D/config.yaml.backup-rotate.$TS
if grep -q "^mixed-port:" $D/config.yaml.new; then
  sed -i "s|^mixed-port: .*|mixed-port: 7890|" $D/config.yaml.new
elif grep -q "^port:" $D/config.yaml.new; then
  sed -i "s|^port: .*|port: 7890|" $D/config.yaml.new
else
  sed -i "1i mixed-port: 7890" $D/config.yaml.new
fi
sed -i "s|external-controller: '127.0.0.1:9090'|external-controller: ':9090'|; \
        s|external-controller: 127.0.0.1:9090|external-controller: :9090|" $D/config.yaml.new
grep -nE "^(mixed-port|external-controller)" $D/config.yaml.new
cp $D/config.yaml.new $D/config.yaml

echo "== 5) 重启 =="
sudo -n systemctl restart clash
sleep 30   # start-clash 直连下载需时
systemctl is-active clash
ss -tln | grep -cE "7890|9090" | xargs echo "监听端口数:"

echo "== 6) 验证 =="
for i in 1 2 3; do
  A=$(curl -sS -o /dev/null -w "%{http_code} %{time_total}s" -m 15 -x http://127.0.0.1:7890 https://api.bybit.com/v5/market/time 2>/dev/null || echo FAIL)
  echo "api#$i: $A"
done
curl -s -m 5 http://127.0.0.1:9090/proxies | python3 -c "
import json,sys
d=json.load(sys.stdin)['proxies']
for k,v in sorted(d.items()):
    if v.get('type') in ('Selector','URLTest','Fallback'):
        print(' ',k,'->',v.get('now'))
" 2>/dev/null | head -n 8
echo "== 7) 交易臂 =="
sleep 30
for f in paper.log paper5.log paper5c.log bridge.log; do echo "-- $f"; tail -n 1 /mnt/nvme/quanforge/logs/$f; done
