#!/usr/bin/env python3
"""从491笔双臂样本+62笔LLM臂交易里挖可迁移的规律(假设生成, 非结论)"""
import sqlite3, re, collections, math

def load_trades(db):
    con = sqlite3.connect(db)
    rows = con.execute("select id, symbol, action, entry, stop_loss, take_profit, "
                       "status, result_pct, created_at, settled_at from ai_advice_track "
                       "where status in ('WIN','LOSS') order by id").fetchall()
    con.close()
    return rows

def load_triggers(logfile):
    """[(created_at, sym)] -> (type, magnitude)"""
    tg = {}
    pat = re.compile(r"\[plan\] (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (\S+) (BUY|SELL) "
                     r".*?\((急动|冲量|扫描) (?:1m|5m|15m) ([+-][\d.]+)%")
    for line in open(logfile, encoding="utf-8", errors="ignore"):
        m = pat.search(line)
        if m:
            tg[(m.group(1), m.group(2))] = (m.group(4), float(m.group(5)))
    return tg

def agg(items):
    n = len(items)
    if not n:
        return "n=0"
    w = sum(1 for p in items if p > 0)
    return f"n={n:<4} WR={100*w/n:>4.0f}% 均笔={sum(items)/n:+.3f}% 和={sum(items):+.1f}pp"

ARMS = [("3R", "/mnt/nvme/quanforge/data/paper_trendrule.db",
         "/mnt/nvme/quanforge/logs/paper.log"),
        ("5R", "/mnt/nvme/quanforge/data/paper_trendrule_tp5.db",
         "/mnt/nvme/quanforge/logs/paper5.log")]

for label, db, logf in ARMS:
    rows = load_trades(db)
    tg = load_triggers(logf)
    print(f"\n########## {label} (n={len(rows)}) ##########")

    # 1) 触发源 x 结果
    print("\n[1] 触发源:")
    by_src = collections.defaultdict(list)
    miss = 0
    for r in rows:
        t = tg.get((r[8], r[1]))
        if t:
            by_src[t[0]].append(r[7])
        else:
            miss += 1
    for k in ["急动", "冲量", "扫描"]:
        if k in by_src:
            print(f"  {k}: {agg(by_src[k])}")
    print(f"  (未匹配日志: {miss})")

    # 2) 时段(入场小时UTC)
    print("\n[2] 入场时段(UTC):")
    by_h = collections.defaultdict(list)
    for r in rows:
        by_h[int(r[8][11:13])].append(r[7])
    for h in sorted(by_h):
        print(f"  {h:02d}:00  {agg(by_h[h])}")
    # 分段汇总
    seg = {"亚洲 00-08": range(0, 8), "欧洲 08-14": range(8, 14),
           "美盘 14-21": range(14, 21), "深夜 21-24": range(21, 24)}
    print("  分段:")
    for name, hrs in seg.items():
        xs = [p for h in hrs for p in by_h.get(h, [])]
        print(f"    {name}: {agg(xs)}")

    # 3) 触发强度(急动|1m|)
    print("\n[3] 急动触发强度 |1m|:")
    by_mag = collections.defaultdict(list)
    for r in rows:
        t = tg.get((r[8], r[1]))
        if t and t[0] == "急动":
            m = abs(t[1])
            b = "<0.45" if m < 0.45 else ("0.45-0.6" if m < 0.6 else ">=0.6")
            by_mag[b].append(r[7])
    for b in ["<0.45", "0.45-0.6", ">=0.6"]:
        if b in by_mag:
            print(f"  {b}%: {agg(by_mag[b])}")

    # 4) 止损距离 risk0 分位
    print("\n[4] 初始止损距离 risk0:")
    by_r = collections.defaultdict(list)
    r0s = sorted(abs(r[4] - r[3]) / r[3] * 100 for r in rows)
    q1, q2 = r0s[len(r0s)//4], r0s[len(r0s)//2]
    for r in rows:
        d = abs(r[4] - r[3]) / r[3] * 100
        b = f"窄<{q1:.2f}" if d < q1 else (f"中{q1:.2f}-{q2:.2f}" if d < q2 else f"宽>={q2:.2f}")
        by_r[b].append(r[7])
    for b in sorted(by_r):
        print(f"  {b}%: {agg(by_r[b])}")

    # 5) 出口形态: 保本/小赢/中赢/全赢/亏损
    print("\n[5] 出口形态:")
    by_x = collections.defaultdict(list)
    for r in rows:
        p = r[7]
        b = ("保本~0" if abs(p) <= 0.05 else
             "小赢0-1" if p < 1 else
             "中赢1-3" if p < 3 else
             "大赢>=3" if p >= 3 else
             "小亏-0.5~0" if p > -0.5 else
             "中亏-1~-0.5" if p > -1 else "全亏<=-1")
        by_x[b].append(p)
    for b in ["保本~0", "小赢0-1", "中赢1-3", "大赢>=3", "小亏-0.5~0", "中亏-1~-0.5", "全亏<=-1"]:
        if b in by_x:
            print(f"  {b}: {agg(by_x[b])}")

    # 6) 连亏后的下一笔
    print("\n[6] 连亏后下一笔期望:")
    by_s = collections.defaultdict(list)
    streak = 0
    for r in rows:
        k = min(streak, 3)
        by_s[k].append(r[7])
        streak = streak + 1 if r[7] < 0 else 0
    for k in sorted(by_s):
        print(f"  前{k}连亏后: {agg(by_s[k])}")

# ===== 回测交叉验证: 时段结构是否同构 =====
print("\n########## 回测时段交叉验证 ##########")
for label, db in [("3R回测", "/mnt/nvme/quanforge/data/backtest_final3.db"),
                  ("5R回测", "/mnt/nvme/quanforge/data/backtest_final5.db")]:
    con = sqlite3.connect(db)
    rows = con.execute("select result_pct, created_at from ai_advice_track "
                       "where status in ('WIN','LOSS') and created_at is not null").fetchall()
    con.close()
    seg = {"亚洲00-08": range(0, 8), "欧洲08-14": range(8, 14),
           "美盘14-21": range(14, 21), "深夜21-24": range(21, 24)}
    print(f"\n[{label}] n={len(rows)}")
    by_h = collections.defaultdict(list)
    for p, ca in rows:
        by_h[int(ca[11:13])].append(p)
    for name, hrs in seg.items():
        xs = [p for h in hrs for p in by_h.get(h, [])]
        print(f"  {name}: {agg(xs)}")

# ===== LLM臂: 方向偏好+时段 =====
print("\n########## LLM臂(主流币62笔) ##########")
con = sqlite3.connect("/mnt/nvme/quanforge/data/quanforge.db")
rows = con.execute("select symbol, action, result_pct, created_at from ai_advice_track "
                   "where symbol in ('BTCUSDT','ETHUSDT','SOLUSDT') "
                   "and status in ('WIN','LOSS') and result_pct is not null").fetchall()
con.close()
by_act = collections.defaultdict(list)
for sym, act, p, ca in rows:
    by_act[act].append(p)
for a in by_act:
    print(f"  {a}: {agg(by_act[a])}")
by_h = collections.defaultdict(list)
for sym, act, p, ca in rows:
    by_h[int(ca[11:13]) // 4 * 4].append(p)
print("  4小时段:")
for h in sorted(by_h):
    print(f"    {h:02d}-{h+4:02d}: {agg(by_h[h])}")
