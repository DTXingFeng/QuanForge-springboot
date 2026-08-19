# Trade Autopsy Tool: classify every LOSS/EXPIRED trade into error taxonomy
# Uses kline history to replay what happened after our stop was hit
import sqlite3, json, urllib.request, sys
from collections import Counter

op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
BASE = "http://127.0.0.1:40702"

def get(path):
    return json.load(op.open(BASE + path, timeout=15))

def klines(symbol, start_ms, end_ms):
    out, cur = [], start_ms
    while cur < end_ms:
        d = get(f"/api/bybit/market?endpoint=/v5/market/kline&category=linear&symbol={symbol}"
                f"&interval=1&limit=200&start={cur}&end={end_ms}")
        lst = d.get("result", {}).get("list", [])
        if not lst:
            break
        rows = sorted((int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]))
                      for k in lst)  # time, open, high, low, close
        out.extend(r for r in rows if r[0] >= cur)
        cur = rows[-1][0] + 60_000
    return out

con = sqlite3.connect("/mnt/nvme/quanforge/data/quanforge.db")
con.row_factory = sqlite3.Row

ver = sys.argv[1] if len(sys.argv) > 1 else None
where = "status in ('WIN','LOSS')" + (f" and sys_version='{ver}'" if ver else "")
rows = con.execute(f"""
    select id, symbol, action, entry, actual_entry, stop_loss, take_profit,
           entered_at, settled_at, result_pct, note, exec_mode, rebased_at
    from ai_advice_track where {where} and entered_at is not null
    order by id""").fetchall()

print(f"analyzing {len(rows)} trades" + (f" (version {ver})" if ver else ""))
taxonomy = Counter()
examples = {}
for t in rows:
    entry = t["actual_entry"] or t["entry"]
    buy = t["action"] == "BUY"
    sl, tp = t["stop_loss"], t["take_profit"]
    hi_ms, st_ms = int(t["entered_at"]), int(t["settled_at"])
    ks = klines(t["symbol"], hi_ms, max(st_ms, hi_ms) + 4 * 3600_000)
    win = t["result_pct"] is not None and t["result_pct"] > 0

    # post-mortem path after settlement: did TP get touched later?
    tp_after = None
    for (tm, _o, hi, lo, _c) in ks:
        if tm <= st_ms:
            continue
        if (buy and hi >= tp) or (not buy and lo <= tp):
            tp_after = (tm - st_ms) / 60_000
            break
    # adverse excursion beyond SL in 4h
    worst = 0.0
    for (tm, _o, hi, lo, _c) in ks:
        exc = (sl - lo) / sl * 100 if buy and lo < sl else ((hi - sl) / sl * 100 if not buy and hi > sl else 0)
        worst = max(worst, exc)

    sl_dist = abs(entry - sl) / entry * 100
    tp_dist = abs(tp - entry) / entry * 100

    if win:
        cat = "WIN-clean"
        # won but could have won more? TP hit then kept running >50% extra
        ran = 0.0
        for (tm, _o, hi, lo, _c) in ks:
            if tm <= st_ms:
                continue
            ext = (hi - tp) / tp * 100 if buy else (tp - lo) / tp * 100
            ran = max(ran, ext)
            break_ = 10
        if ran > tp_dist * 0.5:
            cat = "WIN-capped-early"
    else:
        if tp_after is not None and tp_after <= 240:
            cat = "LOSS-chop-stop"  # stopped out, then price reached TP: noise/wrong placement
        elif worst > sl_dist * 1.5:
            cat = "LOSS-right-side-trend"  # price kept going against hard: wrong direction
        else:
            cat = "LOSS-drift-flat"  # neither recovered nor collapsed: no edge, chop

    taxonomy[cat] += 1
    examples.setdefault(cat, []).append(
        (t["id"], t["symbol"], t["action"], round(t["result_pct"] or 0, 2),
         round(sl_dist, 2), None if tp_after is None else int(tp_after)))

print()
print("=== error taxonomy ===")
total_loss = sum(v for k, v in taxonomy.items() if k.startswith("LOSS"))
total_win = sum(v for k, v in taxonomy.items() if k.startswith("WIN"))
for cat, n in taxonomy.most_common():
    base = total_loss if cat.startswith("LOSS") else total_win
    print(f"{cat:26s} {n:3d}  ({n*100.0/max(1,base):4.1f}% of {'losses' if cat.startswith('LOSS') else 'wins'})")
    print(f"    e.g. {examples[cat][:4]}")
print()
print("=== interpretation keys ===")
print("LOSS-chop-stop       : 被打掉后价格在4h内到达止盈 → 止损放错位/噪音扫损 (REBASE 的靶子)")
print("LOSS-right-side-trend: 打掉后继续同向深跌 >1.5x止损距 → 方向就错了 (研判问题)")
print("LOSS-drift-flat      : 既不恢复也不崩 → 无边界的震荡磨损 (出手时机问题)")
print("WIN-capped-early     : 止盈后趋势延续>50% → 止盈太近，利润截断 (MOVE_TP 的代价)")
con.close()
