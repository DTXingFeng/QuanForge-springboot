#!/bin/bash
# 经旧代理查新机场域名: 原始输出诊断 + 更长超时
P=http://127.0.0.1:7890
echo "== 原始返回诊断 (a-node.ddqo.blog) =="
for u in "https://1.1.1.1/resolve?name=a-node.ddqo.blog&type=A" \
         "https://cloudflare-dns.com/resolve?name=a-node.ddqo.blog&type=A" \
         "https://dns.google/resolve?name=a-node.ddqo.blog&type=A"; do
  echo "--- $u"
  curl -s -m 30 -x $P "$u" -w "\n[http=%{http_code} t=%{time_total}s]\n" | head -c 400
  echo
done

echo "== 两域名解析结果(成功通道) =="
for T in a-node.ddqo.blog b-node.ddqo.blog; do
  R=$(curl -s -m 30 -x $P "https://cloudflare-dns.com/resolve?name=$T&type=A" 2>/dev/null)
  echo "$T -> $(echo "$R" | head -c 300)"
  echo
done
