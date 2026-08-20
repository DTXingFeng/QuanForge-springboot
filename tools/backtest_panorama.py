#!/usr/bin/env python3
"""回溯盘全景报表: 三大库 逐月/逐段/逐币种/逐配置"""
import sqlite3
from collections import defaultdict

LIB = {
    "8月三臂(full/l0/lat)": "/mnt/nvme/quanforge/data/backtest.db",
    "8月LLM延迟(live/lat2)": None,   # 两个一起并进来按 sys_version 分
    "6个月矩阵(hm3/4/5)": None,
}
MERGES = [
    ("lat2", "/mnt/nvme/quanforge/data/backtest_lat2.db"),
    ("live", "/mnt/nvme/quanforge/data/backtest_live.db"),
    ("hm3", "/mnt/nvme/quanforge/data/backtest_hm3.db"),
    ("hm4", "/mnt/nvme/quanforge/data/backtest_hm4.db"),
    ("hm5", "/mnt/nvme/quanforge/data/backtest_hm5.db"),
]
import subprocess, os
for prefix, out in MERGES:
    if not os.path.exists(out):
        subprocess.run(["python3", "/mnt/nvme/quanforge/tools/merge_backtest.py",
                        prefix, "6", out], capture_output=True)

def stats(rs):
    st = [r for r in rs if r[1] in ("WIN", "LOSS")]
    if not st:
        return None
    w = [r for r in st if r[1] == "WIN"]
    gp = sum(r[3] for r in w); gl = abs(sum(r[3] for r in st if r[3] < 0))
    return dict(n=len(st), w=len(w), wr=len(w)/len(st)*100,
                pf=gp/gl if gl else 999, pnl=sum(r[3] for r in st))

def report(label, db, group_key):
    con = sqlite3.connect(db)
    rows = con.execute("select symbol,sys_version,created_at,result_pct,status "
                       "from ai_advice_track where status in ('WIN','LOSS')").fetchall()
    # rows: (symbol, sys_version, created_at, result_pct, status)
    groups = defaultdict(list)
    for sym, ver, ts, pct, st in rows:
        if group_key == "month":
            groups[ts[:7]].append((sym, st, ts, pct))
        elif group_key == "symbol":
            groups[sym].append((sym, st, ts, pct))
        elif group_key == "version":
            groups[ver].append((sym, st, ts, pct))
    print(f"\n===== {label} =====")
    for k in sorted(groups):
        s = stats(groups[k])
        if s:
            print(f"  {k:<34} n={s['n']:>5}  WR={s['wr']:>5.1f}%  PF={s['pf']:>5.2f}  "
                  f"累计={s['pnl']:>+8.1f}%")

# 1) 8月三臂库: 按版本分
report("8月回测库 backtest.db (full/l0/lat 旧延迟臂)", "/mnt/nvme/quanforge/data/backtest.db", "version")
# 2) 延迟终审库
for a in ("lat2", "live"):
    report(f"8月延迟臂 {a}", f"/mnt/nvme/quanforge/data/backtest_{a}.db", "month")
# 3) 6个月矩阵: 逐月 x 逐币种摘要
for tp in (3, 4, 5):
    report(f"6个月矩阵 TP={tp}R 逐月", f"/mnt/nvme/quanforge/data/backtest_hm{tp}.db", "month")
# 4) 笔数总账
print("\n===== 笔数总账 =====")
total = 0
for name, db in [("三臂库", "/mnt/nvme/quanforge/data/backtest.db"),
                 ("lat2", "/mnt/nvme/quanforge/data/backtest_lat2.db"),
                 ("live", "/mnt/nvme/quanforge/data/backtest_live.db"),
                 ("hm3", "/mnt/nvme/quanforge/data/backtest_hm3.db"),
                 ("hm4", "/mnt/nvme/quanforge/data/backtest_hm4.db"),
                 ("hm5", "/mnt/nvme/quanforge/data/backtest_hm5.db")]:
    con = sqlite3.connect(db)
    n = con.execute("select count(*) from ai_advice_track where status in ('WIN','LOSS')").fetchone()[0]
    total += n
    print(f"  {name:<8} {n:>6} 笔已结算")
print(f"  合计     {total:>6} 笔")
