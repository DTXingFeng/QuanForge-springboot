#!/usr/bin/env python3
"""WS诊断v3: 批量试topic格式, 找出有效订阅"""
import websocket, json, time

TOPICS = [
    "kline.1m.BTCUSDT",
    "kline.1.BTCUSDT",
    "kline.1min.BTCUSDT",
    "tickers.BTCUSDT",
    "publicTrade.BTCUSDT",
    "orderbook.1.BTCUSDT",
]
url = "wss://stream.bybit.com/v5/public/linear"
ws = websocket.WebSocket()
ws.connect(url, http_proxy_host="127.0.0.1", http_proxy_port=7890, timeout=15)
ws.settimeout(6)
# 逐个订阅, 每个等确认
for t in TOPICS:
    ws.send(json.dumps({"op": "subscribe", "args": [t]}))
    try:
        raw = ws.recv()
        msg = json.loads(raw)
        ok = msg.get("success")
        print(f"{t:<28} -> {'OK' if ok else 'REJECT: ' + str(msg.get('ret_msg',''))[:60]}")
    except Exception as e:
        print(f"{t:<28} -> 无响应({type(e).__name__})")
        break
# 对成功的topic收10秒数据看是否有push
print("\n收流10秒...")
t0 = time.time(); n = 0; topics_seen = set()
while time.time() - t0 < 10:
    try:
        raw = ws.recv()
    except Exception:
        break
    msg = json.loads(raw or "{}")
    if msg.get("topic"):
        n += 1
        topics_seen.add(msg["topic"].split(".")[0])
print(f"数据消息 {n} 条, topic前缀: {topics_seen}")
