#!/usr/bin/env python3
"""
QuanForge S1 daily-trend PAPER worker (日线趋势跟踪, 前向验证).

冻结协议: docs/trend-daily-20261115/REPORT.md §7(运行规格) + §9(复核).
  - S1: 日线 EMA20/EMA60 收盘判定, 上穿做多/下穿做空, 每品种始终在场
  - 池: MAIN5 = BTC,ETH,SOL,XRP,DOGE 等权 1/5 (严禁按历史赢亏改池)
  - T+1: D 日收盘判定 -> D+1 日开盘调仓
  - 成本: taker+滑点 0.105%/边 (开/平各一次; 翻向=平旧+开新)
  - 资金费: 持仓期间每次已结算费率入账 (空腿收正费, 多腿付正费)
  - 权益: 200U 起, 每槽 20%, L=1 纸面 (20U 实盘杠杆分层另行, 不在本 worker)
  - 90 天验收: 净值>BTC持有; 含费含资金费每笔净bp>0; 期间不改参数
数据: Bybit REST 公开日线K线+资金费历史 (无需凭证). 单次执行, systemd timer
每日 UTC 00:05 触发; 漏跑由 last_day 状态自动补齐(幂等重放).
账本: ai_advice_track 同构(开仓=TRACKING 行, 平仓回填 WIN/LOSS+result_pct)
      + equity_snap(含 btc_hold) + s1_state; 与 tools/paper_*.py 惯例兼容.
"""
import json, os, sqlite3, sys, time, urllib.request

SYMBOLS = [s.strip() for s in os.environ.get(
    "PAPER_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,DOGEUSDT").split(",") if s.strip()]
DB = os.environ.get("PAPER_DB", "/mnt/nvme/quanforge/data/paper_s1trend.db")
EQUITY0 = float(os.environ.get("EQUITY0", "200"))
COST_SIDE = float(os.environ.get("COST_SIDE", "0.00105"))  # taker+滑点 每边
SYS_VERSION = "s1-daily-ema20-60-taker0.21rt-L1-fwd20261115"
PROXY = os.environ.get("PAPER_PROXY", "")  # 默认直连, 失败自动回退本机 7890

def log(m): print(f"{time.strftime('%m-%d %H:%M:%S')} {m}", flush=True)

_opener = [None]
def get(url, tries=3):
    for attempt in range(tries):
        try:
            if _opener[0] is None:
                _opener[0] = urllib.request.build_opener(urllib.request.ProxyHandler(
                    {"http": PROXY, "https": PROXY} if PROXY else {}))
            req = urllib.request.Request(url, headers={"User-Agent": "qfs-paper/1.0"})
            return json.loads(_opener[0].open(req, timeout=25).read())
        except Exception:
            _opener[0] = urllib.request.build_opener(urllib.request.ProxyHandler(
                {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}))
            if attempt == tries - 1:
                raise
            time.sleep(2)

def ema_series(closes, n):
    out, sma = [], 0.0
    for i, v in enumerate(closes):
        if i < n:
            sma += v
            out.append(None if i < n - 1 else sma / n)
        else:
            out.append(out[-1] + (v - out[-1]) * 2.0 / (n + 1))
    return out

def signals(closes):
    """sig[i]=基于截至 i 收盘的 EMA 状态方向; None=热身中. S1 始终在场."""
    e20, e60 = ema_series(closes, 20), ema_series(closes, 60)
    sig = [None] * len(closes)
    for i in range(1, len(closes)):
        if None in (e20[i], e60[i], e20[i - 1], e60[i - 1]):
            continue
        sig[i] = 1 if e20[i] > e60[i] else -1
    return sig

def fetch_daily(sym):
    r = get(f"https://api.bybit.com/v5/market/kline?category=linear&symbol={sym}&interval=D&limit=400")
    return sorted((int(x[0]), float(x[1]), float(x[4])) for x in r["result"]["list"])

def fetch_funding(sym, since_ms):
    out, end = [], int(time.time() * 1000)
    for _ in range(6):
        r = get(f"https://api.bybit.com/v5/market/funding/history?category=linear"
                f"&symbol={sym}&limit=200&endTime={end}")
        lst = r.get("result", {}).get("list", [])
        if not lst:
            break
        out += lst
        oldest = min(int(x["fundingRateTimestamp"]) for x in lst)
        if oldest <= since_ms:
            break
        end = oldest - 1
    return sorted((int(x["fundingRateTimestamp"]), float(x["fundingRate"]))
                  for x in out if int(x["fundingRateTimestamp"]) > since_ms)

def fmt(ms): return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ms / 1000))

def main():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute("""create table if not exists ai_advice_track(
        id integer primary key autoincrement, symbol text, action text,
        entry real, stop_loss real, take_profit real, status text,
        result_pct real, note text, sys_version text,
        created_at text, entered_at text, settled_at text, llm_ms integer)""")
    con.execute("""create table if not exists equity_snap(
        ts text, eq_sizing text, equity real, fixed_equity real, btc_hold real)""")
    con.execute("create table if not exists s1_state(k text primary key, v text)")
    st = {k: v for k, v in con.execute("select k,v from s1_state")}
    equity = float(st.get("equity", EQUITY0))
    last_day = int(st.get("last_day", "0"))
    btc0 = float(st.get("btc0", "0"))
    positions = json.loads(st.get("positions", "{}"))  # sym -> {side,entry,fund_acc,track_id,t0}

    data = {s: fetch_daily(s) for s in SYMBOLS}
    sig = {s: signals([c for _, _, c in data[s]]) for s in SYMBOLS}
    idx = {s: {t: i for i, (t, _, _) in enumerate(data[s])} for s in SYMBOLS}
    common = sorted(set.intersection(*[set(idx[s]) for s in SYMBOLS]))
    if not common:
        log("no common days"); return 1
    today = common[-1]            # 当前未收蜡烛(执行边界)
    last_close = common[-2] if len(common) >= 2 else common[-1]
    if last_day == 0:             # 首跑: 历史仅热身, 前向自今日始
        last_day = last_close
        btc0 = data["BTCUSDT"][idx["BTCUSDT"][today]][1]
        log(f"inception: equity={equity} btc0={btc0} day={fmt(today)[:10]}")

    funding = {s: fetch_funding(s, last_day) for s in SYMBOLS}
    W = 1.0 / len(SYMBOLS)

    def open_track(sym, side, px, t):
        cur = con.execute(
            "insert into ai_advice_track(symbol,action,entry,stop_loss,take_profit,"
            "status,result_pct,note,sys_version,created_at,entered_at,settled_at,llm_ms)"
            " values(?,?,?,null,null,'TRACKING',null,?,?,?,?,null,0)",
            (sym, "BUY" if side > 0 else "SELL", px, "s1-open", SYS_VERSION, fmt(t), fmt(t)))
        con.commit()
        return cur.lastrowid

    def close_track(sym, p, px, t):
        gross = (px / p["entry"] - 1) * p["side"] * 100        # 价格%
        fund_pp = -p["side"] * p["fund_acc"] * 100             # 空腿收正费=+
        fees_pp = 2 * COST_SIDE * 100                          # 本腿开+平
        net = gross + fund_pp - fees_pp
        con.execute("update ai_advice_track set status=?, result_pct=?, settled_at=?,"
                    " note=note||? where id=?",
                    ("WIN" if net > 0 else "LOSS", round(net, 3), fmt(t),
                     f"|close;gross={gross:.3f}fund={fund_pp:.3f}fee=-{fees_pp:.3f}", p["track_id"]))
        con.commit()

    def save_state(day):
        con.executemany("insert or replace into s1_state(k,v) values(?,?)",
                        [("equity", repr(equity)), ("last_day", str(day)),
                         ("btc0", repr(btc0)), ("positions", json.dumps(positions))])
        con.commit()

    days = [d for d in common if last_day < d <= today]
    for d in days:
        prev = d - 86400_000
        day_pnl = 0.0
        for s in SYMBOLS:
            i_prev = idx[s].get(prev)
            target = sig[s][i_prev] if i_prev is not None else None
            p = positions.get(s)
            if target is not None and (p is None or p["side"] != target):
                px_open = data[s][idx[s][d]][1]
                if p is not None:                       # 平旧腿(费=1边)
                    close_track(s, p, px_open, d)
                    day_pnl -= COST_SIDE * equity * W
                    del positions[s]
                positions[s] = {"side": target, "entry": px_open, "fund_acc": 0.0,
                                "t0": d, "track_id": open_track(s, target, px_open, d)}
                day_pnl -= COST_SIDE * equity * W       # 开新腿费(1边)
        if d < today:                                   # 完整收盘日: 计损益
            nxt = d + 86400_000
            for s in SYMBOLS:
                p = positions.get(s)
                if not p:
                    continue
                o1 = next((o for t, o, _ in data[s] if t == nxt), None)
                if o1 is None:
                    continue
                o0 = data[s][idx[s][d]][1]
                fr = sum(r for t, r in funding[s] if d < t <= nxt)
                day_pnl += ((o1 / o0 - 1) * p["side"] + (-p["side"]) * fr) * equity * W
                p["fund_acc"] += fr
            equity += day_pnl
            btc = next((o for t, o, _ in data["BTCUSDT"] if t == nxt), None)
            con.execute("insert into equity_snap(ts,eq_sizing,equity,fixed_equity,btc_hold)"
                        " values(?,?,?,?,?)",
                        (fmt(nxt), "s1", round(equity, 2), round(EQUITY0, 2),
                         round(EQUITY0 * (btc / btc0) if (btc and btc0) else 0, 2)))
            con.commit()
        save_state(d)
        log(f"day {fmt(d)[:10]}: equity={equity:.2f} day_pnl={day_pnl:+.2f}")

    n = con.execute("select count(*) from ai_advice_track where status in ('WIN','LOSS')").fetchone()[0]
    avg = con.execute("select avg(result_pct) from ai_advice_track where status in ('WIN','LOSS')").fetchone()[0]
    btc_now = data["BTCUSDT"][idx["BTCUSDT"][today]][1]
    hold = EQUITY0 * (btc_now / btc0) if btc0 else 0
    pos_desc = ",".join(f"{s}:{'L' if p['side'] > 0 else 'S'}" for s, p in sorted(positions.items()))
    log(f"SUMMARY processed={len(days)} equity={equity:.2f} btc_hold={hold:.2f} "
        f"settled={n} avg_net_pp={0 if avg is None else avg * 100:.1f} pos=[{pos_desc}]")
    return 0

if __name__ == "__main__":
    sys.exit(main())
