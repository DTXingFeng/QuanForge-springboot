import json, time, sys, websocket
out = []
def log(s):
    out.append(s)
    print(s, flush=True)
for host in ("stream.bybit.com", "stream.bytick.com"):
    try:
        ws = websocket.WebSocket()
        ws.connect(f"wss://{host}/v5/public/linear",
                   http_proxy_host="127.0.0.1", http_proxy_port=7890, timeout=12)
        log(f"{host}: connected")
        ws.send(json.dumps({"op": "subscribe", "args": ["kline.1.ACEUSDT"]}))
        log(f"{host}: subscribe sent")
        ws.settimeout(75)
        t0 = time.time(); k = 0; sresp = None
        while time.time() - t0 < 65:
            m = ws.recv()
            if isinstance(m, bytes):
                continue
            msg = json.loads(m)
            if msg.get("op") == "subscribe":
                sresp = msg
                log(f"{host}: SUB RESP {json.dumps(msg)[:160]}")
                continue
            if msg.get("topic", "").startswith("kline"):
                k += 1
                if k <= 2:
                    log(f"{host}: KLINE {json.dumps(msg)[:260]}")
        log(f"{host}: kline msgs in 65s = {k}, subscribe_resp={sresp is not None}")
        ws.close()
    except Exception as e:
        log(f"{host}: FAIL {repr(e)[:150]}")
with open("/tmp/ws_probe_result.txt", "w") as f:
    f.write("\n".join(out))
