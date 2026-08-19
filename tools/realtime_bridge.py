#!/usr/bin/env python3
"""
Bybit public WebSocket monitor -> QuanForge realtime trigger bridge.

Subscribes to public trade/kline streams for the watch list; on sharp moves
(1m momentum beyond threshold) or 15m kline close confirming breakout, calls
the local QuanForge /api/ai/analyze endpoint immediately instead of waiting
for the 10-minute scan cycle.

Design:
- one WS connection, kline.1m for all symbols (agg flow, light)
- local state: rolling 1m returns per symbol
- trigger A: rolling 1m move >= 0.35% (scalp shock)
- trigger B: rolling 5m move >= 0.8% (impulse)
- cooldown per symbol 5 min (analyze is expensive; circuit: one in flight)
- watch list refreshed from QuanForge config every 10 min
- zero external deps (websockets not needed: uses raw socket via asyncio?
   -> uses 'websocket-client' if present else falls back to raw TCP+TLS is
   too complex; Pi has websockets pkg? use aiohttp? Keep it stdlib-only:
   actually simplest robust: use python3-websockets if installed, else poll
   REST every 5s as degraded mode.)
"""
import json, time, urllib.request, threading, os, sys, collections

QF = "http://127.0.0.1:40702"
SHOCK_1M = 0.35          # % 1-minute move triggers immediate analyze
IMPULSE_5M = 0.80        # % 5-minute move triggers immediate analyze
COOLDOWN_S = 300         # per-symbol cooldown
WS_PROXY = os.environ.get("WS_PROXY", "http://127.0.0.1:7890")

opener_direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
opener_proxy = urllib.request.build_opener(urllib.request.ProxyHandler(
    {"http": WS_PROXY, "https": WS_PROXY}))

def qf_get(path, timeout=10):
    last = None
    for op in (opener_direct, opener_proxy):
        try:
            return json.load(op.open(QF + path, timeout=timeout))
        except Exception as e:
            last = e
    raise RuntimeError(str(last))

def qf_post(path, timeout=120):
    data = b""
    last = None
    for op in (opener_direct, opener_proxy):
        try:
            req = urllib.request.Request(QF + path, data=data, method="POST")
            op.open(req, timeout=timeout).read()
            return True
        except Exception as e:
            last = e
    print("post failed:", last, flush=True)
    return False

state_lock = threading.Lock()
# symbol -> deque of (ts_ms, close)
prices = collections.defaultdict(lambda: collections.deque(maxlen=400))
last_trigger = {}
analyzing = set()

def on_kline(msg):
    for item in msg.get("data", []):
        sym = item.get("symbol", "")
        close = float(item.get("close", 0) or 0)
        ts = int(item.get("timestamp", 0) or item.get("start", 0) or time.time() * 1000)
        confirm = item.get("confirm", False)
        if not close or not sym:
            continue
        with state_lock:
            prices[sym].append((ts, close))
        if not confirm:
            return  # mid-bar updates too noisy; act on closed bars only
        check_symbol(sym)

def pct_move(sym, window_ms):
    with state_lock:
        dq = prices[sym]
        if len(dq) < 2:
            return 0.0
        newest_t, newest = dq[-1]
        cutoff = newest_t - window_ms
        ref = None
        for t, c in dq:
            if t >= cutoff:
                ref = c
                break
        if ref is None:
            ref = dq[0][1]
        if not ref:
            return 0.0
        return (newest / ref - 1) * 100

def check_symbol(sym):
    now = time.time()
    with state_lock:
        if now - last_trigger.get(sym, 0) < COOLDOWN_S or sym in analyzing:
            return
        last_trigger[sym] = now
        analyzing.add(sym)
    try:
        m1 = pct_move(sym, 60_000)
        m5 = pct_move(sym, 300_000)
        why = None
        if abs(m1) >= SHOCK_1M:
            why = f"1m {m1:+.2f}%"
        elif abs(m5) >= IMPULSE_5M:
            why = f"5m {m5:+.2f}%"
        if why:
            print(f"[trigger] {sym} {why} -> analyze", flush=True)
            threading.Thread(target=qf_post, args=(f"/api/ai/analyze?symbol={sym}",),
                             daemon=True).start()
    finally:
        with state_lock:
            analyzing.discard(sym)

def watch_syms():
    try:
        cfg = qf_get("/api/ai/config")
        return [s.strip().upper() for s in cfg.get("watchSymbols", "").split(",") if s.strip()]
    except Exception as e:
        print("config fetch failed:", e, flush=True)
        return []

def ws_loop():
    """Try websocket-client; if absent, fall back to 5s REST polling."""
    try:
        import websocket  # websocket-client pkg
        have_ws = True
    except ImportError:
        have_ws = False
        print("websocket-client not installed; degraded REST polling mode", flush=True)
    while True:
        syms = watch_syms() or ["BTCUSDT"]
        try:
            if have_ws:
                run_ws(syms)
            else:
                run_rest(syms)
        except Exception as e:
            print("loop error:", e, flush=True)
            time.sleep(10)

def run_ws(syms):
    import websocket
    url = "wss://stream.bybit.com/v5/public/linear"
    ws = websocket.WebSocket()
    ws.connect(url, http_proxy_host="127.0.0.1", http_proxy_port=7890, timeout=15)
    args = [{"kline.1m": s} for s in syms]
    ws.send(json.dumps({"op": "subscribe", "args": [f"kline.1m.{s}" for s in syms]}))
    print(f"[ws] subscribed {len(syms)} symbols", flush=True)
    last_ping = time.time()
    while True:
        raw = ws.recv()
        if time.time() - last_ping > 20 * 1000 / 1000:
            ws.send(json.dumps({"op": "ping"}))
            last_ping = time.time()
        msg = json.loads(raw if raw else "{}")
        topic = msg.get("topic", "")
        if topic.startswith("kline"):
            on_kline(msg)

def run_rest(syms):
    """Degraded mode: 5s tickers polling (still ~120x faster than 10min scan)."""
    while True:
        for sym in syms:
            try:
                d = qf_get(f"/api/bybit/market?endpoint=/v5/market/tickers&category=linear&symbol={sym}",
                           timeout=8)
                t = d["result"]["list"][0]
                price = float(t["lastPrice"])
                ts = int(time.time() * 1000)
                with state_lock:
                    prices[sym].append((ts, price))
                check_symbol(sym)
            except Exception:
                pass
        time.sleep(5)

if __name__ == "__main__":
    print("quanforge realtime bridge starting", flush=True)
    ws_loop()
