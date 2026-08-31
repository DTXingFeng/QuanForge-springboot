#!/usr/bin/env python3
"""
v5-mech: 1h EMA排列翻转趋势纸面臂(无LLM机械对照).

设计依据(tools/v5_trigger_study.py, 208天x5币):
  - 触发: 1h EMA20/60/200 全多(UP)/全空(DOWN)排列翻转, 仅alts(主流币增量~0)
  - 事件后边际前置: 4-24h +0.3~0.5pp vs 随机基线, 48h转负 -> TTL硬顶24h
  - 信号密度 ~2/周/币 -> LLM延迟无关, REST 60s轮询即可(无需WS/看门狗)
规则: 翻转bar收盘入场; SL=1.2xATR14(1h); 无TP; 24根bar TTL平仓;
      反向翻转先平后开; 仓位=风险平价(RISK_PCT=1%, 名义上限5x).
账本: 同twins schema(ai_advice_track OPEN行 + equity_snap).
"""
import calendar, json, os, sqlite3, time, urllib.request

import pandas as pd

SYMBOLS = [s.strip() for s in os.environ.get(
    "V5_SYMBOLS", "ACEUSDT,ZECUSDT,SNDKUSDT").split(",") if s.strip()]
SL_ATR_MULT = 1.2
TTL_BARS = 24
RISK_PCT = 1.0
EQUITY0 = 200.0
POLL_S = 60
WARMUP = 220
DB = os.environ.get("V5_DB", "/mnt/nvme/quanforge/data/paper_v5mech.db")
SYS_VERSION = "v5.0-mech-1hflip-atrsl1.2-ttl24-risk1"
PROXY = {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}
opener_px = urllib.request.build_opener(urllib.request.ProxyHandler(PROXY))
opener_direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))

equity = EQUITY0
pos = {}            # sym -> dict(action, entry, sl, rowid, entry_ts, risk0)
last_state = {}     # sym -> "UP"/"DOWN"/"MIXED" (最近一根已收盘bar的排列)
last_bar = {}       # sym -> 最近处理过的已收盘bar ts


def log(msg):
    print(f"{time.strftime('%m-%d %H:%M:%S')} {msg}", flush=True)


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


def restore(con):
    global equity
    r = con.execute("select equity from equity_snap order by ts desc limit 1").fetchone()
    if r:
        equity = r[0]
        log(f"[restore] equity={equity:.1f}")
    for row in con.execute(
            "select id, symbol, action, entry, stop_loss, created_at from ai_advice_track "
            "where status='OPEN'").fetchall():
        rid, sym, act, entry, sl, ca = row
        try:
            entry_ms = calendar.timegm(time.strptime(ca, "%Y-%m-%d %H:%M:%S")) * 1000
        except Exception:
            entry_ms = 0
        pos[sym] = {"action": act, "entry": entry, "sl": sl, "rowid": rid,
                    "entry_ms": entry_ms, "risk0": abs(entry - sl) / entry * 100}
        log(f"[restore] {sym} {act} @{entry} sl={sl}")


def fmt(ms):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ms / 1000))


def open_row(con, sym, action, entry, sl, ts_ms, note):
    cur = con.execute(
        "insert into ai_advice_track(symbol,action,entry,stop_loss,take_profit,"
        "status,result_pct,note,sys_version,created_at,entered_at,settled_at,llm_ms) "
        "values(?,?,?,?,?,?,?,?,?,?,?,null,0)",
        (sym, action, entry, sl, None, "OPEN", None, note, SYS_VERSION,
         fmt(ts_ms), fmt(ts_ms)))
    con.commit()
    return cur.lastrowid


def settle(con, sym, p, status, pct, ts_ms, note=""):
    global equity
    sl_pct = p["risk0"] if p["risk0"] > 0.01 else abs(p["entry"] - p["sl"]) / p["entry"] * 100
    base = min(equity * RISK_PCT / sl_pct, equity * 5.0) if sl_pct > 0.01 else equity * 5.0
    equity += base * pct / 100
    con.execute("update ai_advice_track set status=?, result_pct=?, settled_at=? where id=?",
                (status, round(pct, 3), fmt(ts_ms), p["rowid"]))
    con.execute("insert into equity_snap values(?,?,?,?)",
                (fmt(ts_ms), "risk", round(equity, 2), round(equity, 2)))
    con.commit()
    log(f"[settle] {fmt(ts_ms)} {sym} {p['action']} -> {status} {pct:+.3f}% eq={equity:.1f} {note}")


def rest_klines(sym):
    url = (f"https://api.bybit.com/v5/market/kline?category=linear&symbol={sym}"
           f"&interval=60&limit=600")
    err = None
    for op in (opener_direct, opener_px):
        try:
            d = json.load(op.open(url, timeout=15))
            return [(int(x[0]), float(x[1]), float(x[2]), float(x[3]),
                     float(x[4]), float(x[5])) for x in sorted(d["result"]["list"])]
        except Exception as e:
            err = e
    raise RuntimeError(f"rest kline {sym}: {err}")


def classify(closes):
    e20 = closes.ewm(span=20, adjust=False).mean().iloc[-1]
    e60 = closes.ewm(span=60, adjust=False).mean().iloc[-1]
    e200 = closes.ewm(span=200, adjust=False).mean().iloc[-1]
    if e20 > e60 > e200:
        return "UP"
    if e20 < e60 < e200:
        return "DOWN"
    return "MIXED"


def atr14(bars):
    df = pd.DataFrame({"h": [b[2] for b in bars], "l": [b[3] for b in bars],
                       "c": [b[4] for b in bars]})
    pc = df["c"].shift(1)
    tr = pd.concat([df["h"] - df["l"], (df["h"] - pc).abs(),
                    (df["l"] - pc).abs()], axis=1).max(axis=1)
    return float(tr.ewm(alpha=1 / 14, adjust=False).mean().iloc[-1])


def enter(con, sym, action, price, a, ts_ms):
    sl_d = a * SL_ATR_MULT
    sl = price - sl_d if action == "BUY" else price + sl_d
    risk0 = abs(price - sl) / price * 100
    rid = open_row(con, sym, action, price, sl, ts_ms,
                   f"1h翻转->{'UP' if action=='BUY' else 'DOWN'}")
    pos[sym] = {"action": action, "entry": price, "sl": sl, "rowid": rid,
                "entry_ms": ts_ms, "risk0": risk0}
    log(f"[entry] {fmt(ts_ms)} {sym} {action} @{price:.6g} sl={sl:.6g} risk0={risk0:.2f}%")


def tick(con, sym, now_ms):
    bars = rest_klines(sym)
    closed = [b for b in bars if b[0] + 3600_000 <= now_ms]
    if len(closed) < WARMUP:
        return
    ts, o, h, l, c, v = closed[-1]
    if last_bar.get(sym) == ts:
        # 无新bar: 仍刷新beat由外部做, 这里跳过
        return
    last_bar[sym] = ts
    closes = pd.Series([b[4] for b in closed])
    st = classify(closes)

    # ---- 持仓结算(先于新开仓, 同bar反向翻转=先平后开) ----
    if sym in pos:
        p = pos[sym]
        buy = p["action"] == "BUY"
        bars_held = int((ts - p["entry_ms"]) / 3600_000)
        if (buy and l <= p["sl"]) or (not buy and h >= p["sl"]):
            pct = (p["sl"] - p["entry"]) / p["entry"] * (100 if buy else -100)
            settle(con, sym, p, "LOSS", pct, ts, "SL")
            pos.pop(sym)
        elif bars_held >= TTL_BARS:
            pct = (c - p["entry"]) / p["entry"] * (100 if buy else -100)
            settle(con, sym, p, "WIN" if pct >= 0 else "LOSS", pct, ts, "TTL24h")
            pos.pop(sym)

    # ---- 翻转触发 ----
    prev = last_state.get(sym)
    if prev is None:
        last_state[sym] = st
        return
    if st in ("UP", "DOWN") and st != prev:
        action = "BUY" if st == "UP" else "SELL"
        log(f"[flip] {fmt(ts)} {sym} {prev}->{st} @{c:.6g}")
        if sym in pos and pos[sym]["action"] != action:
            # 反向: 先平(按本bar收盘)
            p = pos.pop(sym)
            buy = p["action"] == "BUY"
            pct = (c - p["entry"]) / p["entry"] * (100 if buy else -100)
            settle(con, sym, p, "WIN" if pct >= 0 else "LOSS", pct, ts, "反向翻转平仓")
        if sym not in pos:
            a = atr14(closed[-30:])
            enter(con, sym, action, c, a, ts)
    last_state[sym] = st


def main():
    con = init_db()
    restore(con)
    log(f"[paper] {SYS_VERSION} symbols={SYMBOLS} db={DB}")
    beat = 0
    while True:
        now_ms = int(time.time() * 1000)
        for sym in SYMBOLS:
            try:
                tick(con, sym, now_ms)
            except Exception as e:
                log(f"[err] {sym}: {e}")
        if time.time() - beat > 1800:
            beat = time.time()
            ages = {s: round((now_ms - last_bar.get(s, 0)) / 60000, 1) for s in SYMBOLS}
            log(f"[beat] equity={equity:.1f} pos={list(pos.keys())} bar_age_min={ages}")
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
