#!/bin/bash
# Clash订阅更新脚本 v2 (2026-08-23): 下载成功后才patch端口/controller; sudo -n; 代理失败转直连
CLASH_DIR="/mnt/nvme/clash"
SUBSCRIBE_URL="${SUBSCRIBE_URL:?环境变量缺失: export SUBSCRIBE_URL=<订阅地址>}"
CONFIG_FILE="$CLASH_DIR/config.yaml"
BACKUP_FILE="$CLASH_DIR/config.yaml.backup"
PROXY_URL="http://127.0.0.1:7890"

patch_cfg() {
  # 代理端口固定7890(交易系统依赖), controller全接口保面板
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
[ -f "$CONFIG_FILE" ] && cp "$CONFIG_FILE" "$BACKUP_FILE"

# 注意: 该机场按客户端IP地域下发入口域名, 经代理(HK出口)会拿到被污染批次
# (ddqo.blog NXDOMAIN), 必须**直连优先**下载
curl -sL "$SUBSCRIBE_URL" -H "User-Agent: clash.meta" \
    --connect-timeout 20 -m 60 -o "$CONFIG_FILE"
if ! grep -qE "^(proxies|proxy-providers):" "$CONFIG_FILE"; then
    echo "直连下载失败, 尝试经代理..."
    curl -sL "$SUBSCRIBE_URL" -H "User-Agent: clash-meta" -x "$PROXY_URL" \
        --connect-timeout 20 -m 60 -o "$CONFIG_FILE"
fi

if grep -qE "^(proxies|proxy-providers):" "$CONFIG_FILE"; then
    patch_cfg "$CONFIG_FILE"
    echo "订阅配置更新成功"
    sudo -n systemctl restart clash
    sleep 3
    echo "Clash服务已重启: $(systemctl is-active clash)"
else
    echo "订阅配置更新失败，恢复备份"
    [ -f "$BACKUP_FILE" ] && cp "$BACKUP_FILE" "$CONFIG_FILE"
    exit 1
fi
