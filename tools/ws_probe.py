#!/usr/bin/env python3
"""30秒受控WS连通性测试: 经代理连 Bybit public WS, 数消息/错误"""
import websocket, json, time, sys

url = "wss://stream.bybit.com/v5/public/linear"
ws = websocket.WebSocket()
t0 = time.time()
ws.connect(url, http_proxy_host="127.0.0.1", http_proxy_port=7890, timeout=15)
print(f"connect ok in {time.time()-t0:.1f}s")
ws.settimeout(10)
ws.send(json.dumps({"op": "subscribe", "args": ["kline.1m.BTCUSDT"]}))
n, errs, t0 = 0, 0, time.time()
last = t0
while time.time() - t0 < 30:
    try:
        raw = ws.recv()
        n += 1
        last = time.time()
    except websocket.WebSocketTimeoutException:
        print(f"recv timeout after {time.time()-last:.0f}s silence")
        errs += 1
        break
    except Exception as e:
        print(f"recv err: {type(e).__name__}: {e}")
        errs += 1
        break
print(f"RESULT msgs={n} errs={errs} survived={time.time()-t0:.0f}s")
