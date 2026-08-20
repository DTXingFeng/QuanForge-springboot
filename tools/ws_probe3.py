import json, time, websocket

def run(args, label):
    ws = websocket.WebSocket()
    ws.connect("wss://stream.bybit.com/v5/public/linear",
               http_proxy_host="127.0.0.1", http_proxy_port=7890, timeout=12)
    ws.send(json.dumps({"op": "subscribe", "args": args}))
    ws.settimeout(100)
    t0 = time.time()
    k = {}; sub = None; errs = []
    while time.time() - t0 < 90:
        m = ws.recv()
        msg = json.loads(m if isinstance(m, str) else "{}")
        if msg.get("op") == "subscribe":
            sub = msg
            continue
        if msg.get("success") is False:
            errs.append(json.dumps(msg)[:200])
            continue
        if msg.get("topic", "").startswith("kline"):
            for it in msg.get("data", []):
                if it.get("confirm"):
                    k[it.get("symbol")] = k.get(it.get("symbol"), 0) + 1
    print(f"{label}: subscribe={json.dumps(sub)[:120]} confirmed_klines={k} errs={errs}", flush=True)
    ws.close()

run(["kline.1.ACEUSDT", "kline.1.ZECUSDT", "kline.1.SNDKUSDT"], "3-symbol")
run(["kline.1.SNDKUSDT"], "SNDK-only")
