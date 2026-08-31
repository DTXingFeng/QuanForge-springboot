#!/bin/bash
# Clash启动脚本 v2 (2026-08-23): 下载到tmp校验成功才替换(失败沿用现有配置, 不会回退到坏文件)
CLASH_DIR="/mnt/nvme/clash"
SUBSCRIBE_URL="${SUBSCRIBE_URL:?环境变量缺失: export SUBSCRIBE_URL=<订阅地址>}"
CONFIG_FILE="$CLASH_DIR/config.yaml"
LOCAL_PROXY="http://127.0.0.1:7890"

patch_cfg() {
  if grep -q "^mixed-port:" "$1"; then
    sed -i "s|^mixed-port: .*|mixed-port: 7890|" "$1"
  elif grep -q "^port:" "$1"; then
    sed -i "s|^port: .*|port: 7890|" "$1"
  else
    sed -i "1i mixed-port: 7890" "$1"
  fi
  sed -i "s|external-controller: '127.0.0.1:9090'|external-controller: ':9090'|; \
          s|external-controller: 127.0.0.1:9090|external-controller: :9090|" "$1"
}

echo "正在更新订阅配置..."
# 直连优先: 该机场按客户端IP地域下发入口域名, 经代理(HK出口)会拿到被污染批次
curl -sL "$SUBSCRIBE_URL" -H "User-Agent: clash.meta" \
    --connect-timeout 20 -m 60 -o "$CONFIG_FILE.tmp"
if ! grep -qE "^(proxies|proxy-providers):" "$CONFIG_FILE.tmp" 2>/dev/null; then
    curl -sL "$SUBSCRIBE_URL" -H "User-Agent: clash-meta" -x "$LOCAL_PROXY" \
        --connect-timeout 20 -m 60 -o "$CONFIG_FILE.tmp"
fi

if grep -qE "^(proxies|proxy-providers):" "$CONFIG_FILE.tmp" 2>/dev/null; then
    patch_cfg "$CONFIG_FILE.tmp"
    mv "$CONFIG_FILE.tmp" "$CONFIG_FILE"
    echo "订阅配置更新成功"
else
    rm -f "$CONFIG_FILE.tmp"
    patch_cfg "$CONFIG_FILE"
    echo "订阅下载失败，使用现有配置"
fi

echo "正在启动Clash..."
exec /mnt/nvme/clash/clash -d /mnt/nvme/clash -f /mnt/nvme/clash/config.yaml
