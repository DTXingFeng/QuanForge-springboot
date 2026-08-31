#!/bin/bash
# 一次性: 订阅切换到 smallstrawberry + 两个脚本注入 controller 补丁
set -e
NEW_URL="${SUBSCRIBE_URL:?环境变量缺失: export SUBSCRIBE_URL=<订阅地址>}"
D=/mnt/nvme/clash

# 1) update-subscribe.sh 换URL(整行替换, 避免特殊字符匹配问题)
sed -i "s|^SUBSCRIBE_URL=.*|SUBSCRIBE_URL=\"$NEW_URL\"|" $D/update-subscribe.sh
# start-clash.sh 已换过, 校验一下
grep -q smallstrawberry $D/start-clash.sh || \
  sed -i "s|^SUBSCRIBE_URL=.*|SUBSCRIBE_URL=\"$NEW_URL\"|" $D/start-clash.sh

# 2) 两个脚本注入 controller 补丁(下载后把 127.0.0.1:9090 改回 :9090, 保面板LAN可用)
PATCH='sed -i "s|external-controller: \x27127.0.0.1:9090\x27|external-controller: \x27:9090\x27|" "$CONFIG_FILE"'
for F in $D/update-subscribe.sh $D/start-clash.sh; do
  grep -q "external-controller" $F || sed -i "\|# 使用局域网代理下载订阅配置|i\\# 保面板可用: 订阅默认绑127.0.0.1, 改回全接口\n$PATCH" $F
done

# 3) 启用已打好补丁的新配置
cp $D/config.yaml.new $D/config.yaml

# 4) 重启
sudo -n systemctl restart clash
sleep 3
systemctl is-active clash
echo "--- URL检查 ---"
grep -h "^SUBSCRIBE_URL" $D/update-subscribe.sh $D/start-clash.sh
echo "--- 补丁注入检查 ---"
grep -c "external-controller" $D/update-subscribe.sh $D/start-clash.sh
echo "--- 生效节点 ---"
curl -sS -m 5 http://127.0.0.1:9090/proxies | python3 -c "
import json,sys
d=json.load(sys.stdin)['proxies']
for k,v in d.items():
    if v.get('type') in ('Selector','URLTest','Fallback'):
        print(k,'->',v.get('now'))
"
