#!/usr/bin/env python3
"""WS诊断v4: 批量订阅6币种 kline.1min, 20秒数消息; 再试逐个订阅对照"""
import websocket, json, time

SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ACEUSDT", "ZECUSDT", "SNDKUSDT"]
url = "wss://stream.bybit.com/v5/public/linear"

def listen(ws, secs, label):
    n, t0 = 0, time.time()
    syms_seen = set()
    while time.time() - t0 < secs:
        try:
            raw = ws.recv()
        except Exception as e:
            print(f"[{label}] {time.time()-t0:.0f}s 处断: {type(e).__name__}")
            return
        msg = json.loads(raw or "{}")
        if msg.get("topic"):
            n += 1
            syms_seen.add(msg["topic"].rsplit(".", 1)[-1])
        elif msg.get("op") == "subscribe":
            print(f"[{label}] 订阅回执: success={msg.get('success')} {str(msg.get('ret_msg',''))[:50]}")
    print(f"[{label}] {secs}s 收到 {n} 条数据, 覆盖 {len(syms_seen)} 币种: {sorted(syms_seen)}")

# 批量订阅
ws = websocket.WebSocket()
ws.connect(url, http_proxy_host="127.0.0.1", http_proxy_port=7890, timeout=15)
ws.settimeout(8)
ws.send(json.dumps({"op": "subscribe", "args": [f"kline.1min.{s}" for s in SYMS]}))
listen(ws, 20, "批量6币种")
ws.close()

# 逐个订阅
ws2 = websocket.WebSocket()
ws2.connect(url, http_proxy_host="127.0.0.1", http_proxy_port=7890, timeout=15)
ws2.settimeout(8)
for s in SYMS:
    ws2.send(json.dumps({"op": "subscribe", "args": [f"kline.1min.{s}"]}))
listen(ws2, 20, "逐个6币种")
ws2.close()
