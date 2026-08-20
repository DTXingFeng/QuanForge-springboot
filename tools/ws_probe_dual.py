import json, time, websocket
for host in ("stream.bybit.com", "stream.bytick.com"):
    try:
        ws = websocket.WebSocket()
        ws.connect(f"wss://{host}/v5/public/linear",
                   http_proxy_host="127.0.0.1", http_proxy_port=7890, timeout=12)
        ws.send(json.dumps({"op": "subscribe", "args": ["kline.1.ACEUSDT"]}))
        ws.settimeout(45)
        t0 = time.time(); k = 0; first = None
        while time.time() - t0 < 40:
            m = ws.recv()
            msg = json.loads(m if isinstance(m, str) else "{}")
            if msg.get("topic", "").startswith("kline"):
                k += 1
                if first is None:
                    first = round(time.time() - t0, 1)
        print(f"{host}: kline msgs={k} in 40s first_after={first}s", flush=True)
        ws.close()
    except Exception as e:
        print(f"{host}: FAIL {repr(e)[:110]}", flush=True)
