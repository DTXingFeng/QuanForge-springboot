#!/usr/bin/env python3
"""WS诊断v2: 打印每条消息; 分别测 http代理/socks5/直连"""
import websocket, json, time

def probe(label, **kw):
    url = "wss://stream.bybit.com/v5/public/linear"
    try:
        ws = websocket.WebSocket()
        ws.connect(url, timeout=15, **kw)
        ws.settimeout(8)
        ws.send(json.dumps({"op": "subscribe", "args": ["kline.1m.BTCUSDT"]}))
        n, t0 = 0, time.time()
        while time.time() - t0 < 20:
            try:
                raw = ws.recv()
            except Exception as e:
                print(f"[{label}] recv停: {type(e).__name__} {e} (存活{time.time()-t0:.0f}s, {n}条)")
                return
            n += 1
            msg = json.loads(raw or "{}")
            print(f"[{label}] #{n} topic={msg.get('topic','?')} op={msg.get('op','')} "
                  f"ret={msg.get('success','')} {str(raw)[:150]}")
        print(f"[{label}] 20s存活, 共{n}条")
    except Exception as e:
        print(f"[{label}] 连接失败: {type(e).__name__}: {e}")

print("--- http代理 7890 ---")
probe("http", http_proxy_host="127.0.0.1", http_proxy_port=7890)
print("--- socks5 7891 ---")
probe("socks", proxy_type="socks5", http_proxy_host="127.0.0.1", http_proxy_port=7891)
print("--- 直连 ---")
probe("direct")
