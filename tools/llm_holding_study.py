#!/usr/bin/env python3
"""LLM臂持仓时长 x 结果: 直接检验"LLM更适合趋势而非短窗"假设"""
import sqlite3, collections, datetime

con = sqlite3.connect("/mnt/nvme/quanforge/data/quanforge.db")
rows = con.execute(
    "select symbol, action, entry, result_pct, entered_at, settled_at, note "
    "from ai_advice_track where status in ('WIN','LOSS') and result_pct is not null "
    "and entered_at is not null and settled_at is not null").fetchall()
con.close()

def span_min(ca, sa):
    # Java存epoch毫秒
    try:
        return (int(sa) - int(ca)) / 60000.0
    except (ValueError, TypeError):
        try:
            t1 = datetime.datetime.fromisoformat(ca.replace("T", " ").split(".")[0])
            t2 = datetime.datetime.fromisoformat(sa.replace("T", " ").split(".")[0])
            return (t2 - t1).total_seconds() / 60
        except Exception:
            return None

buckets = collections.defaultdict(list)
spans_all = []
for sym, act, e, pct, ca, sa, note in rows:
    m = span_min(ca, sa)
    if m is None:
        continue
    spans_all.append(m)
    b = ("<10分" if m < 10 else "10-30分" if m < 30 else "30-90分" if m < 90
         else "1.5-4时" if m < 240 else ">=4时")
    buckets[b].append(pct)

spans_all.sort()
n = len(spans_all)
print(f"LLM臂全部已结算 n={n} 持仓时长: 中位={spans_all[n//2]:.0f}分 "
      f"p25={spans_all[n//4]:.0f}分 p75={spans_all[3*n//4]:.0f}分")
print("\n按持仓时长切片:")
for b in ["<10分", "10-30分", "30-90分", "1.5-4时", ">=4时"]:
    xs = buckets.get(b, [])
    if not xs:
        continue
    w = sum(1 for x in xs if x > 0)
    print(f"  {b:7s}: n={len(xs):<3} WR={100*w/len(xs):>3.0f}% 均笔={sum(xs)/len(xs):+.3f}% "
          f"和={sum(xs):+.2f}pp")

# 动态管理介入的单 vs 自然TP/SL出场的单
managed = [r for r in rows if r[6] and ("动态管理" in r[6])]
print(f"\n动态管理介入的单: n={len(managed)} "
      f"和={sum(r[3] for r in managed):+.2f}pp 均笔={sum(r[3] for r in managed)/max(len(managed),1):+.3f}%")
