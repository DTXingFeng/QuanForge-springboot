#!/usr/bin/env python3
"""全账户钱流地图: demo钱包 + LLM臂实单账本 + 五纸面臂"""
import sqlite3, json, subprocess, datetime

def api(path, extra=""):
    return subprocess.run(
        f'curl -s -m 10 "http://127.0.0.1:40702/api/bybit/get?endpoint={path}{extra}"',
        shell=True, capture_output=True, text=True).stdout

print("== Bybit 模拟盘钱包 ==")
try:
    d = json.loads(api("/v5/account/wallet-balance", "&accountType=UNIFIED"))
    for w in d["result"]["list"]:
        for c in w.get("coin", []):
            if float(c.get("walletBalance", 0)) != 0:
                print(f"  {c['coin']}: 余额={c['walletBalance']} 已实现盈亏={c.get('cumRealisedPnl','?')}")
except Exception as e:
    print("  钱包查询失败:", e)

print("\n== 当前持仓 ==")
try:
    d = json.loads(api("/v5/position/list", "&category=linear&settleCoin=USDT"))
    L = d["result"]["list"]
    if not L:
        print("  (空仓)")
    for p in L:
        print(f"  {p['symbol']} {p['side']} qty={p['size']} avg={p['avgPrice']} "
              f"tp={p.get('takeProfit','')} sl={p.get('stopLoss','')} upl={p['unrealisedPnl']}")
except Exception as e:
    print("  持仓查询失败:", e)

print("\n== LLM臂 实单(DEMO模式)账本 ==")
con = sqlite3.connect("/mnt/nvme/quanforge/data/quanforge.db")
rows = con.execute("select status, exec_mode, count(*), coalesce(sum(result_pct),0) "
                   "from ai_advice_track group by status, exec_mode").fetchall()
for st, em, n, s in rows:
    print(f"  {st:8s} {em or '-':5s}: n={n:<4} 价格和={s:+.1f}pp")
demo = con.execute("select count(*), sum(case when result_pct>0 then 1 else 0 end), "
                   "coalesce(sum(result_pct),0) from ai_advice_track "
                   "where exec_mode='DEMO' and status in ('WIN','LOSS')").fetchone()
if demo[0]:
    print(f"  DEMO合计: n={demo[0]} WR={100*demo[1]/demo[0]:.0f}% 均笔={demo[2]/demo[0]:+.3f}%")
# 最近7天demo盈亏
r7 = con.execute("select count(*), coalesce(sum(result_pct),0) from ai_advice_track "
                 "where exec_mode='DEMO' and status in ('WIN','LOSS') "
                 "and created_at > (strftime('%s','now')-7*86400)*1000").fetchone()
print(f"  DEMO近7天: n={r7[0]} 价格和={r7[1]:+.1f}pp")
con.close()

print("\n== 纸面臂快照 ==")
for label, db in [("3R", "paper_trendrule"), ("5R", "paper_trendrule_tp5"),
                  ("5C", "paper_trendrule_tp5c"), ("v5mech", "paper_v5mech")]:
    try:
        con = sqlite3.connect(f"/mnt/nvme/quanforge/data/{db}.db")
        r = con.execute("select count(*), sum(case when result_pct>0 then 1 else 0 end), "
                        "coalesce(sum(result_pct),0) from ai_advice_track "
                        "where status in ('WIN','LOSS')").fetchone()
        eq = con.execute("select equity from equity_snap order by ts desc limit 1").fetchone()
        n = r[0] or 0
        e = f"{eq[0]:.1f}" if eq else "200"
        avg = f"{r[2]/n:+.3f}%" if n else "-"
        wr = f"{100*r[1]/n:.0f}%" if n else "-"
        print(f"  {label:7s}: n={n:<4} WR={wr:>4} 均笔={avg:>8} 权益={e}")
        con.close()
    except Exception:
        print(f"  {label}: (空)")
