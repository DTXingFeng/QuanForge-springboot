#!/usr/bin/env python3
"""WS诊断v5: 每种kline topic格式独立连接验证(收全回执+听数据)"""
import websocket, json, time

VARIANTS = ["kline.1m.BTCUSDT", "kline.1min.BTCUSDT", "kline.1.BTCUSDT",
            "kline.1M.BTCUSDT", "kline.1sec.BTCUSDT", "kline.60.BTCUSDT"]
url = "wss://stream.bybit.com/v5/public/linear"

for v in VARIANTS:
    try:
        ws = websocket.WebSocket()
        ws.connect(url, http_proxy_host="127.0.0.1", http_proxy_port=7890, timeout=15)
        ws.settimeout(3)
        ws.send(json.dumps({"op": "subscribe", "args": [v]}))
        receipts = []
        data_n = 0
        t0 = time.time()
        while time.time() - t0 < 8:
            try:
                raw = ws.recv()
            except Exception:
                continue
            msg = json.loads(raw or "{}")
            if msg.get("op") == "subscribe":
                receipts.append(f"success={msg.get('success')}:{str(msg.get('ret_msg',''))[:40]}")
            elif msg.get("topic"):
                data_n += 1
        verdict = "有数据" if data_n > 0 else ("静默" if receipts else "无回执")
        print(f"{v:<24} 回执{receipts} 数据{data_n}条 -> {verdict}")
        ws.close()
    except Exception as e:
        print(f"{v:<24} 连接失败 {type(e).__name__}: {e}")
