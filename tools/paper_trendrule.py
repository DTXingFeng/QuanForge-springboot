#!/usr/bin/env python3
"""
QuanForge v4.8 trend-rule PAPER trader (模拟盘, 前向验证).

策略与 tools/backtest.py --arm trend-rule 完全一致(逐字复刻触发/趋势/熔断/
止损/止盈/TTL 规则), 以便模拟盘结果与回测直接对比:
  - 触发: |1m|>=0.35% / |5m|>=0.8% / 30分钟扫描(|15m|>=0.5% 或 RSI 极值)
  - 方向: EMA20>EMA60 且 EMA60>EMA200 -> BUY; 双下 -> SELL; 不一致不交易
  - 入场: 触发bar收盘价挂限价单(被动成交), 120min 超时
  - 止损: 1.2xATR(主币钳制2.2%), 止盈: TP_R x R (默认3R)
  - 熔断: 2h动量逆势>=1.2% / 90分钟内同向2亏 -> 拦截
  - TTL: 主币240min / 山寨120min 按收盘价平
  - 仓位: SIZING=eq 权益5%x100x(默认) / fixed $1000
不碰任何真实订单; 数据源 Bybit 公共 WS kline.1m(confirmed bar), 启动时 REST 热身.
账本: /mnt/nvme/quanforge/data/paper_trendrule.db (ai_advice_track 同构 + equity_snap)
"""
import json, os, sqlite3, threading, time, urllib.request
from collections import deque

import numpy as np
import pandas as pd

# ---------------- 参数(与 backtest.py 一致) ----------------
SYMBOLS = [s.strip() for s in os.environ.get(
    "PAPER_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT,ACEUSDT,ZECUSDT,SNDKUSDT").split(",") if s.strip()]
MAJORS = {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
SHOCK_1M, IMPULSE_5M, COOLDOWN_S = 0.35, 0.80, 300
SCAN_PCT15M, SCAN_RSI_X = 0.5, 25.0
BREAKER_2H = 1.2
CLAMP_MAJORS = 2.2
TTL_ALTS, TTL_MAJORS = 120, 240
SL_MULT = 1.2
TP_R = float(os.environ.get("TP_R", "3"))
SIZING = os.environ.get("SIZING", "eq")     # eq | fixed
EQUITY0 = 200.0
NOTIONAL = 1000.0
SLIP_LIMIT = 0.0003
PENDING_TTL_MIN = 120
WARMUP_BARS = 900                            # EMA200 热身
DB = os.environ.get("PAPER_DB", "/mnt/nvme/quanforge/data/paper_trendrule.db")
SYS_VERSION = f"v4.8-trendrule-paper-tp{TP_R:g}R-{SIZING}"
PROXY = {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}

opener_px = urllib.request.build_opener(urllib.request.ProxyHandler(PROXY))
opener_direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# ---------------- 指标(与 backtest.py 同公式) ----------------
def rsi(s, period=14):
    d = s.diff()
    g = d.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
    return (100 - 100/(1 + g/l.replace(0, np.nan))).fillna(50)

def atr(df, period=14):
    pc = df["close"].shift()
    tr = pd.concat([df["high"]-df["low"], (df["high"]-pc).abs(),
                    (df["low"]-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()

# ---------------- 状态 ----------------
lock = threading.Lock()
bars = {s: deque(maxlen=1600) for s in SYMBOLS}   # symbol -> deque[(ts_ms,o,h,l,c,v)]
pos = {}          # symbol -> dict(position)
pending = {}      # symbol -> dict(pending limit)
last_trig = {}    # symbol -> ts_ms
losses_90 = {}    # "sym|dir" -> [ts_ms,...]
equity = EQUITY0
fixed_equity = EQUITY0

def init_db():
    con = sqlite3.connect(DB)
    con.execute("""create table if not exists ai_advice_track(
        id integer primary key autoincrement, symbol text, action text,
        entry real, stop_loss real, take_profit real, status text,
        result_pct real, note text, sys_version text,
        created_at text, entered_at text, settled_at text, llm_ms integer)""")
    con.execute("""create table if not exists equity_snap(
        ts text, eq_sizing text, equity real, fixed_equity real)""")
    con.commit()
    return con

def fmt(ts_ms):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts_ms / 1000))

def record(con, sym, action, entry, sl, tp, status, pct, note,
           created_ms, entered_ms=None, settled_ms=None):
    con.execute("insert into ai_advice_track(symbol,action,entry,stop_loss,"
                "take_profit,status,result_pct,note,sys_version,"
                "created_at,entered_at,settled_at,llm_ms) values(?,?,?,?,?,?,?,?,?,?,?,?,0)",
                (sym, action, entry, sl, tp, status,
                 round(pct, 3) if pct is not None else None, note, SYS_VERSION,
                 fmt(created_ms), fmt(entered_ms) if entered_ms else None,
                 fmt(settled_ms) if settled_ms else None))
    con.commit()

def snap_equity(con, ts_ms):
    global equity, fixed_equity
    con.execute("insert into equity_snap(ts,eq_sizing,equity,fixed_equity) values(?,?,?,?)",
                (fmt(ts_ms), SIZING, round(equity, 2), round(fixed_equity, 2)))
    con.commit()

def settle(con, sym, p, status, pct, ts_ms, note=""):
    global equity, fixed_equity
    base = NOTIONAL if SIZING == "fixed" else max(equity * 5.0, 0.0)
    equity += base * pct / 100
    fixed_equity += NOTIONAL * pct / 100
    record(con, sym, p["action"], p["entry"], p["sl"], p["tp"], status, pct, note,
           p["plan_ms"], p["fill_ms"], ts_ms)
    snap_equity(con, ts_ms)
    if status == "LOSS":
        losses_90.setdefault(sym + "|" + p["action"], []).append(ts_ms)
    print(f"[settle] {fmt(ts_ms)} {sym} {p['action']} -> {status} {pct:+.3f}% "
          f"eq={equity:.1f} note={note}", flush=True)

# ---------------- 单bar推进(与 backtest 主循环同构) ----------------
def on_bar(con, sym, ts_ms, o, h, l, c, v):
    global equity, fixed_equity
    dq = bars[sym]
    if dq and ts_ms <= dq[-1][0]:
        return                      # 重复bar
    dq.append((ts_ms, o, h, l, c, v))
    if len(dq) < 420:               # EMA200 热身不足
        return

    # ---- 1) 持仓结算 ----
    if sym in pos:
        p = pos[sym]
        buy = p["action"] == "BUY"
        hit_sl = l <= p["sl"] if buy else h >= p["sl"]
        hit_tp = h >= p["tp"] if buy else l <= p["tp"]
        if hit_sl and hit_tp:
            settle(con, sym, p, "LOSS",
                   (p["sl"] - p["entry"]) / p["entry"] * (100 if buy else -100),
                   ts_ms, "同根双触发保守判损"); pos.pop(sym); return
        if hit_sl:
            settle(con, sym, p, "LOSS",
                   (p["sl"] - p["entry"]) / p["entry"] * (100 if buy else -100),
                   ts_ms); pos.pop(sym); return
        if hit_tp:
            settle(con, sym, p, "WIN",
                   (p["tp"] - p["entry"]) / p["entry"] * (100 if buy else -100),
                   ts_ms); pos.pop(sym); return
        if (ts_ms - p["fill_ms"]) / 60000 > (TTL_MAJORS if sym in MAJORS else TTL_ALTS):
            pct = (c - p["entry"]) / p["entry"] * (100 if buy else -100)
            settle(con, sym, p, "WIN" if pct >= 0 else "LOSS", pct, ts_ms, "TTL平仓")
            pos.pop(sym); return
        return

    # ---- 2) 限价单成交/超时 ----
    if sym in pending:
        q = pending[sym]
        buy = q["action"] == "BUY"
        touched = h >= q["entry"] if buy else l <= q["entry"]
        if touched:
            q["entry"] = q["entry"] * (1 + (SLIP_LIMIT if buy else -SLIP_LIMIT))
            q["fill_ms"] = ts_ms
            pos[sym] = q
            pending.pop(sym)
            print(f"[fill] {fmt(ts_ms)} {sym} {q['action']} @{q['entry']:.6g} "
                  f"sl={q['sl']:.6g} tp={q['tp']:.6g}", flush=True)
        elif (ts_ms - q["plan_ms"]) / 60000 > PENDING_TTL_MIN:
            record(con, sym, q["action"], q["entry"], q["sl"], q["tp"], "EXPIRED",
                   None, "等入场超时", q["plan_ms"], None, ts_ms)
            pending.pop(sym)
        return

    # ---- 3) 触发检测 ----
    cl = pd.Series([b[4] for b in dq])
    ts_minute = time.gmtime(ts_ms / 1000).tm_min
    n = len(cl) - 1
    pct1m = (cl.iloc[n] / cl.iloc[n-1] - 1) * 100
    pct5m = (cl.iloc[n] / cl.iloc[n-5] - 1) * 100
    pct15m = (cl.iloc[n] / cl.iloc[n-15] - 1) * 100
    r = float(rsi(cl).iloc[n])
    why = None
    if abs(pct1m) >= SHOCK_1M:
        why = f"急动 1m {pct1m:+.2f}%"
    elif abs(pct5m) >= IMPULSE_5M:
        why = f"冲量 5m {pct5m:+.2f}%"
    elif ts_minute % 30 == 0 and (abs(pct15m) >= SCAN_PCT15M or
                                  r <= SCAN_RSI_X or r >= 100 - SCAN_RSI_X):
        why = f"扫描 15m {pct15m:+.2f}% RSI {r:.0f}"
    if why is None:
        return
    if (ts_ms - last_trig.get(sym, 0)) / 1000 < COOLDOWN_S:
        return
    last_trig[sym] = ts_ms

    # ---- 4) 趋势一致才做 ----
    ema20 = cl.ewm(span=20).mean().iloc[n]
    ema60 = cl.ewm(span=60).mean().iloc[n]
    ema200 = cl.ewm(span=200).mean().iloc[n]
    t15 = "UP" if ema20 > ema60 else "DOWN"
    t1h = "UP" if ema60 > ema200 else "DOWN"
    if t15 != t1h:
        return
    action = "BUY" if t15 == "UP" else "SELL"

    # ---- 5) 熔断 ----
    if len(dq) > 120:
        m2h = (cl.iloc[n] / cl.iloc[n-120] - 1) * 100
        if (m2h >= BREAKER_2H and action == "SELL") or (m2h <= -BREAKER_2H and action == "BUY"):
            record(con, sym, action, c, 0, 0, "BLOCKED", None,
                   f"breaker:2h {m2h:+.2f}%", ts_ms)
            return
    key = sym + "|" + action
    recent = [t for t in losses_90.get(key, []) if (ts_ms - t) / 1000 <= 5400]
    losses_90[key] = recent
    if len(recent) >= 2:
        record(con, sym, action, c, 0, 0, "BLOCKED", None, "breaker:2连亏冷却", ts_ms)
        return

    # ---- 6) 挂限价单 ----
    df_last = pd.DataFrame({"high": [b[2] for b in dq], "low": [b[3] for b in dq],
                            "close": cl})
    a = float(atr(df_last).iloc[n])
    sl_d = a * SL_MULT
    if sl_d <= 0:
        return
    sl = c - sl_d if action == "BUY" else c + sl_d
    if sym in MAJORS and sl_d / c * 100 > CLAMP_MAJORS:
        sl = c - c * CLAMP_MAJORS / 100 if action == "BUY" else c + c * CLAMP_MAJORS / 100
    tp = c + TP_R * (c - sl) if action == "BUY" else c - TP_R * (sl - c)
    pending[sym] = {"action": action, "entry": c, "sl": sl, "tp": tp,
                    "plan_ms": ts_ms, "fill_ms": None}
    print(f"[plan] {fmt(ts_ms)} {sym} {action} LIMIT@{c:.6g} sl={sl:.6g} "
          f"tp={tp:.6g} ({why})", flush=True)

# ---------------- 数据层 ----------------
def rest_klines(sym, limit=1000, end_ms=None):
    url = (f"https://api.bybit.com/v5/market/kline?category=linear&symbol={sym}"
           f"&interval=1&limit={limit}" + (f"&end={int(end_ms)}" if end_ms else ""))
    for op in (opener_direct, opener_px):
        try:
            d = json.load(op.open(url, timeout=15))
            rows = d["result"]["list"]          # [start,o,h,l,c,v,turnover] 倒序
            return [(int(x[0]), float(x[1]), float(x[2]), float(x[3]),
                     float(x[4]), float(x[5])) for x in rows]
        except Exception as e:
            err = e
    raise RuntimeError(f"rest kline {sym}: {err}")

def warmup(con):
    for sym in SYMBOLS:
        for attempt in range(5):
            try:
                rows = rest_klines(sym, limit=1000)
                dq = bars[sym]
                for b in sorted(rows):
                    if not dq or b[0] > dq[-1][0]:
                        dq.append(b)
                print(f"[warmup] {sym} {len(dq)} bars", flush=True)
                break
            except Exception as e:
                print(f"[warmup err] {sym} {e} retry", flush=True)
                time.sleep(5)

def ws_run(con):
    import websocket
    url = "wss://stream.bybit.com/v5/public/linear"
    ws = websocket.WebSocket()
    ws.connect(url, http_proxy_host="127.0.0.1", http_proxy_port=7890, timeout=15)
    ws.settimeout(120)   # 静默容忍 2 分钟(20s ping 保活); 15s 会误杀安静时段
    ws.send(json.dumps({"op": "subscribe",
                        "args": [f"kline.1m.{s}" for s in SYMBOLS]}))
    print(f"[ws] subscribed {len(SYMBOLS)} symbols", flush=True)
    last_ping = time.time()
    last_beat = time.time()
    while True:
        raw = ws.recv()
        if time.time() - last_ping > 20:
            ws.send(json.dumps({"op": "ping"}))
            last_ping = time.time()
        if time.time() - last_beat > 1800:
            with lock:
                snap_equity(con, int(time.time() * 1000))
            print(f"[beat] equity={equity:.1f} fixed={fixed_equity:.1f} "
                  f"pos={list(pos)} pending={list(pending)}", flush=True)
            last_beat = time.time()
        msg = json.loads(raw or "{}")
        if not msg.get("topic", "").startswith("kline"):
            continue
        for item in msg.get("data", []):
            if not item.get("confirm", False):
                continue
            sym = item.get("symbol")
            if sym not in bars:
                continue
            b = (int(item["start"]), float(item["open"]), float(item["high"]),
                 float(item["low"]), float(item["close"]), float(item["volume"]))
            with lock:
                on_bar(con, sym, *b)

def main():
    con = init_db()
    print(f"[paper] {SYS_VERSION} symbols={SYMBOLS} db={DB}", flush=True)
    with lock:
        warmup(con)
    while True:
        try:
            ws_run(con)
        except Exception as e:
            print(f"[ws err] {e} -> reconnect+warmup in 10s", flush=True)
            time.sleep(10)
            with lock:
                warmup(con)

if __name__ == "__main__":
    main()
