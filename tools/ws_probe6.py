#!/usr/bin/env python3
"""验证 kline.1 的 payload 结构(确认 confirm/start 字段)"""
import websocket, json, time
url = "wss://stream.bybit.com/v5/public/linear"
ws = websocket.WebSocket()
ws.connect(url, http_proxy_host="127.0.0.1", http_proxy_port=7890, timeout=15)
ws.settimeout(6)
ws.send(json.dumps({"op": "subscribe", "args": ["kline.1.BTCUSDT"]}))
t0 = time.time()
shown = 0
while time.time() - t0 < 70 and shown < 3:
    try:
        raw = ws.recv()
    except Exception:
        continue
    msg = json.loads(raw or "{}")
    if msg.get("topic") and msg.get("data"):
        item = msg["data"][0] if isinstance(msg["data"], list) else msg["data"]
        print("样本:", json.dumps(item, ensure_ascii=False)[:260])
        shown += 1
        if item.get("confirm"):
            break
