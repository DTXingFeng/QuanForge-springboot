#!/bin/bash
# 新批次域名解析验证 -> 可解析则装机切换
set -e
SRC=/tmp/ua/clash_meta.yaml
D=/mnt/nvme/clash

echo "== 1) 新域名解析(阿里DoH) =="
OK=0
for d in fffppp.f1eb10ae-1d82-4c6a-b4dd-bd9525520956.com kkkhhh.f1eb10ae-1d82-4c6a-b4dd-bd9525520956.com kkkhhh.xs-us.net; do
  R=$(curl -s -m 6 "https://223.5.5.5/resolve?name=$d&type=A" | python3 -c "
import json,sys
d=json.load(sys.stdin)
ips=[a['data'] for a in d.get('Answer',[]) if a.get('type')==1]
print(d.get('Status'), ips[:2])" 2>/dev/null || echo "FAIL")
  echo "$d -> $R"
  echo "$R" | grep -q "\[" && echo "$R" | grep -qv "\[\]" && OK=1 || true
done
[ $OK -eq 1 ] || { echo "FATAL: 新批次域名也不可解析"; exit 1; }

echo "== 2) 装配新配置(直连版clash.meta UA) =="
cp $SRC $D/config.yaml.new
grep -cE "^\s+- \{ name" $D/config.yaml.new | xargs echo "节点数:"
if grep -q "^mixed-port:" $D/config.yaml.new; then
  sed -i "s|^mixed-port: .*|mixed-port: 7890|" $D/config.yaml.new
elif grep -q "^port:" $D/config.yaml.new; then
  sed -i "s|^port: .*|port: 7890|" $D/config.yaml.new
else
  sed -i "1i mixed-port: 7890" $D/config.yaml.new
fi
sed -i "s|external-controller: '127.0.0.1:9090'|external-controller: ':9090'|; \
        s|external-controller: 127.0.0.1:9090|external-controller: :9090|" $D/config.yaml.new
grep -nE "^(port|socks-port|mixed-port|external-controller)" $D/config.yaml.new

echo "== 3) 生效 =="
cp $D/config.yaml.new $D/config.yaml
sudo -n systemctl restart clash
sleep 5
echo "clash: $(systemctl is-active clash)"

echo "== 4) 验证 =="
curl -sS -o /dev/null -w "api.bybit.com: %{http_code} %{time_total}s\n" -m 20 \
    -x http://127.0.0.1:7890 https://api.bybit.com/v5/market/time
curl -sS -o /dev/null -w "stream.bybit.com: %{http_code} %{time_total}s\n" -m 20 \
    -x http://127.0.0.1:7890 https://stream.bybit.com/v5/public/time
curl -s -m 5 http://127.0.0.1:9090/proxies | python3 -c "
import json,sys
d=json.load(sys.stdin)['proxies']
for k,v in sorted(d.items()):
    if v.get('type') in ('Selector','URLTest','Fallback'):
        print(' ',k,'->',v.get('now'))
"
