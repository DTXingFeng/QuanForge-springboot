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
import calendar, copy, json, math, os, sqlite3, time, urllib.request

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
SYS_VERSION = "v5.0.1-mech-ledger-recovery"
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
    con.execute("""create table if not exists paper_runtime(
        symbol text primary key, last_bar integer, last_state text, position_json text)""")
    con.commit()
    return con


def restore(con):
    global equity
    r = con.execute("select equity from equity_snap order by rowid desc limit 1").fetchone()
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
    for sym, ts, state, encoded in con.execute(
            "select symbol,last_bar,last_state,position_json from paper_runtime"):
        last_bar[sym], last_state[sym] = ts, state
        if encoded and sym in pos:
            saved = json.loads(encoded)
            if saved["rowid"] == pos[sym]["rowid"]:
                pos[sym].update(saved)
    for sym, p in pos.items():
        if "notional" not in p:
            # A legacy OPEN row has no entry-size evidence. Do not invent an equity P&L.
            log(f"[audit-required] {sym} legacy OPEN has no entry notional; settlement blocked")


def save_runtime(con, sym):
    con.execute("insert into paper_runtime values(?,?,?,?) on conflict(symbol) do update "
                "set last_bar=excluded.last_bar,last_state=excluded.last_state,"
                "position_json=excluded.position_json",
                (sym, last_bar[sym], last_state[sym],
                 json.dumps(pos[sym]) if sym in pos else None))


def fmt(ms):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ms / 1000))


def open_row(con, sym, action, entry, sl, ts_ms, note):
    cur = con.execute(
        "insert into ai_advice_track(symbol,action,entry,stop_loss,take_profit,"
        "status,result_pct,note,sys_version,created_at,entered_at,settled_at,llm_ms) "
        "values(?,?,?,?,?,?,?,?,?,?,?,null,0)",
        (sym, action, entry, sl, None, "OPEN", None, note, SYS_VERSION,
         fmt(ts_ms), fmt(ts_ms)))
    return cur.lastrowid


def settle(con, sym, p, status, pct, ts_ms, note=""):
    global equity
    base = p.get("notional")
    if base is None:
        raise RuntimeError(f"{sym}: legacy position missing entry notional; reconcile before resuming")
    updated = con.execute("update ai_advice_track set status=?, result_pct=?, settled_at=?, "
                          "note=coalesce(note,'') || ? where id=? and status='OPEN'",
                          (status, round(pct, 3), fmt(ts_ms), " | exit=" + note, p["rowid"]))
    if updated.rowcount != 1:
        raise RuntimeError(f"{sym}: position already settled or missing")
    equity += base * pct / 100
    con.execute("insert into equity_snap values(?,?,?,?)",
                (fmt(ts_ms), "risk", equity, equity))
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
    if not all(math.isfinite(x) and x > 0 for x in (price, a, equity, risk0, sl)):
        raise ValueError("invalid entry/ATR/equity")
    notional = min(equity * RISK_PCT / risk0, equity * 5.0) if risk0 > 0.01 else equity * 5.0
    rid = open_row(con, sym, action, price, sl, ts_ms,
                   f"1h翻转->{'UP' if action=='BUY' else 'DOWN'}")
    pos[sym] = {"action": action, "entry": price, "sl": sl, "rowid": rid,
                "entry_ms": ts_ms, "risk0": risk0, "notional": notional}
    log(f"[entry] {fmt(ts_ms)} {sym} {action} @{price:.6g} sl={sl:.6g} risk0={risk0:.2f}%")


def process_bar(con, sym, closed):
    """One confirmed hour, at its close time. Caller commits ledger and cursor together."""
    ts, o, h, l, c, v = closed[-1]
    close_ms = ts + 3600_000
    closes = pd.Series([b[4] for b in closed])
    st = classify(closes)

    # ---- 持仓结算(先于新开仓, 同bar反向翻转=先平后开) ----
    if sym in pos:
        p = pos[sym]
        buy = p["action"] == "BUY"
        bars_held = int((close_ms - p["entry_ms"]) / 3600_000)
        if (buy and l <= p["sl"]) or (not buy and h >= p["sl"]):
            # A gap through a stop cannot execute at a price better than the open.
            exit_price = min(o, p["sl"]) if buy else max(o, p["sl"])
            pct = (exit_price - p["entry"]) / p["entry"] * (100 if buy else -100)
            settle(con, sym, p, "LOSS", pct, close_ms, "SL")
            pos.pop(sym)
        elif bars_held >= TTL_BARS:
            pct = (c - p["entry"]) / p["entry"] * (100 if buy else -100)
            settle(con, sym, p, "WIN" if pct >= 0 else "LOSS", pct, close_ms, "TTL24h")
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
            settle(con, sym, p, "WIN" if pct >= 0 else "LOSS", pct, close_ms, "反向翻转平仓")
        if sym not in pos:
            a = atr14(closed[-30:])
            enter(con, sym, action, c, a, close_ms)
    last_state[sym] = st


def tick(con, sym, now_ms):
    """Replay every unseen closed bar, reject holes, never trade a future REST candle."""
    global equity
    unique = {}
    for b in rest_klines(sym):
        ts = b[0]
        if ts + 3600_000 > now_ms:
            continue
        if ts in unique and unique[ts] != b:
            raise ValueError(f"{sym}: conflicting duplicate {ts}")
        if not all(math.isfinite(x) for x in b) or min(b[1:5]) <= 0 or b[2] < max(b[1], b[3], b[4]) or b[3] > min(b[1], b[2], b[4]):
            raise ValueError(f"{sym}: invalid OHLC {ts}")
        unique[ts] = b
    closed = [unique[ts] for ts in sorted(unique)]
    if len(closed) < WARMUP:
        return
    cursor = last_bar.get(sym)
    if cursor is None:
        if sym in pos:
            raise RuntimeError(f"{sym}: legacy OPEN has no processing cursor; offline reconciliation required")
        # Fresh installation warms history without fabricating historical entries.
        last_state[sym] = classify(pd.Series([b[4] for b in closed[:-1]]))
        cursor = closed[-2][0]
    unseen = [i for i, b in enumerate(closed) if b[0] > cursor]
    if unseen and (closed[unseen[0]][0] != cursor + 3600_000 or any(
            closed[i][0] - closed[i-1][0] != 3600_000 for i in range(1, len(closed)))):
        raise RuntimeError(f"{sym}: incomplete hour history; keep cursor {cursor}")
    for i in unseen:
        before = (equity, copy.deepcopy(pos), dict(last_bar), dict(last_state))
        try:
            with con:
                process_bar(con, sym, closed[:i+1])
                last_bar[sym] = closed[i][0]
                save_runtime(con, sym)
        except Exception:
            equity, saved_pos, saved_bar, saved_state = before
            pos.clear(); pos.update(saved_pos)
            last_bar.clear(); last_bar.update(saved_bar)
            last_state.clear(); last_state.update(saved_state)
            raise


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
