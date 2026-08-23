#!/bin/bash
# DNS探针: 节点域名枚举 + 多resolver交叉验证
echo "== 节点server域名分布 =="
grep -oE "server: [^,}]+" /mnt/nvme/clash/config.yaml | sort | uniq -c | sort -rn | head -n 15

DOMAINS=$(grep -oE "server: [^,}]+" /mnt/nvme/clash/config.yaml | awk '{print $2}' | sort -u)
echo; echo "== 各域名经 阿里DoH(223.5.5.5) 解析 =="
for d in $DOMAINS; do
  R=$(curl -s -m 5 "https://223.5.5.5/resolve?name=$d&type=A" | \
      python3 -c "import json,sys
d=json.load(sys.stdin)
ips=[a['data'] for a in d.get('Answer',[]) if a.get('type')==1]
print(d.get('Status'), ips[:2])" 2>/dev/null)
  echo "$d -> $R"
done

T=b-node.ddqo.blog
echo; echo "== $T 经境外DoH交叉 =="
for u in "https://9.9.9.9/resolve" "https://dns.adguard-dns.com/resolve" "https://1.1.1.1/resolve" "https://dns.google/resolve"; do
  R=$(curl -s -m 6 "$u?name=$T&type=A" | head -c 260)
  echo "[$u] -> ${R:-TIMEOUT/FAIL}"
  echo
done
