#!/usr/bin/env python3
"""三臂回测对比报告: full(LLM) / l0(级联) / lat(自适应延迟)"""
import sqlite3, statistics as st

DBS = {"full": "/mnt/nvme/quanforge/data/backtest.db",
       "l0":   "/mnt/nvme/quanforge/data/backtest_l0.db",
       "lat":  "/mnt/nvme/quanforge/data/backtest_lat.db"}
NOTIONAL = 1000.0   # 每笔名义 $1000, 1% = $10

def load(db):
    con = sqlite3.connect(db)
    rows = con.execute("select symbol,action,status,result_pct,note,created_at,llm_ms "
                       "from ai_advice_track order by created_at").fetchall()
    segs = {}
    for r in con.execute("select seg from seg_map") if False else []:
        pass
    return rows

def seg_of(ts):
    """created_at -> 段号: 窗口起点 seg k = k*5 天偏移, 2026-07-19 起"""
    import datetime
    t = datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    base = datetime.datetime(2026, 7, 19)
    return int((t - base).total_seconds() // (5 * 86400))

def stats(rows):
    settled = [r for r in rows if r[2] in ("WIN", "LOSS")]
    wins = [r for r in settled if r[2] == "WIN"]
    losses = [r for r in settled if r[2] == "LOSS"]
    gp = sum(r[3] for r in wins); gl = abs(sum(r[3] for r in losses))
    return dict(n=len(settled), w=len(wins), l=len(losses),
                wr=len(wins) / len(settled) * 100 if settled else 0,
                pf=gp / gl if gl else float("inf"),
                pnl_pct=sum(r[3] for r in settled),
                pnl_usd=sum(r[3] for r in settled) * NOTIONAL / 100)

print("=" * 88)
print("总览（每段起点$200，6段 → 合并名义基线$1200）")
print(f"{'臂':<6}{'成交笔数':>8}{'胜':>6}{'负':>6}{'胜率':>8}{'PF':>7}{'累计%':>9}{'累计$':>10}")
arm_rows = {}
for name, db in DBS.items():
    rows = load(db)
    arm_rows[name] = rows
    s = stats(rows)
    print(f"{name:<6}{s['n']:>8}{s['w']:>6}{s['l']:>6}{s['wr']:>7.1f}%{s['pf']:>7.2f}{s['pnl_pct']:>9.1f}{s['pnl_usd']:>10.0f}")

print("\n被拦截/弃单/规则单计数")
for name, rows in arm_rows.items():
    from collections import Counter
    c = Counter(r[2] for r in rows)
    l0fill = sum(1 for r in rows if r[2] == "L0-FILL")
    l0blk = sum(1 for r in rows if "L0被拦" in (r[4] or ""))
    exp = c.get("EXPIRED", 0)
    print(f"{name:<6} BLOCKED={c.get('BLOCKED',0):>5}  EXPIRED={exp:>5}  L0成交={l0fill:>4}  L0被拦={l0blk:>4}")

print("\n按段配对对比（同 5 天窗口, 段内累计%）")
hdr = f"{'段':<4}" + "".join(f"{n+'累计%':>12}" for n in DBS)
print(f"{'段':<4}{'full':>12}{'l0':>12}{'lat':>12}   (W/L full | l0 | lat)")
seg_data = {n: {} for n in DBS}
for name, rows in arm_rows.items():
    for r in rows:
        if r[2] in ("WIN", "LOSS", "L0-FILL"):
            k = seg_of(r[5])
            seg_data[name].setdefault(k, []).append(r)
for k in sorted(set().union(*[set(d) for d in seg_data.values()])):
    line = f"{k:<4}"
    wl = []
    for name in DBS:
        rs = seg_data[name].get(k, [])
        if rs:
            s = stats(rs)
            line += f"{s['pnl_pct']:>12.1f}"
            wl.append(f"{s['w']}/{s['l']}")
        else:
            line += f"{'--':>12}"; wl.append("--")
    print(line + "   (" + " | ".join(wl) + ")")

print("\n分币种（累计%, 括号内胜率%)")
symbols = sorted({r[0] for rows in arm_rows.values() for r in rows})
print(f"{'币种':<10}" + "".join(f"{n+'%':>12}" for n in DBS) + "   胜率")
for sym in symbols:
    line = f"{sym:<10}"
    wrs = []
    for name in DBS:
        rs = [r for r in arm_rows[name] if r[0] == sym and r[2] in ("WIN", "LOSS", "L0-FILL")]
        if rs:
            s = stats(rs)
            line += f"{s['pnl_pct']:>12.1f}"
            wrs.append(f"{s['wr']:.0f}%/{s['n']}")
        else:
            line += f"{'--':>12}"; wrs.append("--")
    print(line + "   " + " | ".join(wrs))

print("\nL0 规则单 vs LLM 单（l0 臂内）")
rows = arm_rows["l0"]
l0f = [r for r in rows if r[2] == "L0-FILL"]
llm = [r for r in rows if r[2] in ("WIN", "LOSS")]
for label, rs in [("L0规则单", l0f), ("LLM单", llm)]:
    if not rs: continue
    s = stats(rs)
    print(f"{label:<8} n={s['n']:>4} WR={s['wr']:>5.1f}% PF={s['pf']:>5.2f} 累计={s['pnl_pct']:>7.1f}%")

print("\nLLM 延迟分布 (ms, 已成交单)")
for name in DBS:
    ms = [r[6] for r in arm_rows[name] if r[2] in ("WIN", "LOSS", "L0-FILL") and r[6]]
    if ms:
        print(f"{name:<6} n={len(ms):>5} 均值={st.mean(ms):>6.0f} 中位={st.median(ms):>6.0f} p90={sorted(ms)[int(len(ms)*0.9)]:>6.0f}")

print("\nlat 臂弃单原因 & 弃单后行情（延迟期间价格跑了多远才弃）")
rows = arm_rows["lat"]
exp = [r for r in rows if r[2] == "EXPIRED"]
print(f"EXPIRED={len(exp)} / 非拦截总数={len([r for r in rows if r[2]!='BLOCKED'])}")
ms = [r[6] for r in exp if r[6]]
if ms: print(f"弃单单LLM耗时: 均值={st.mean(ms):.0f}ms 中位={st.median(ms):.0f}ms")

print("\n按小时的胜率（full 臂, 看什么时段亏最多）")
from collections import defaultdict
hh = defaultdict(lambda: [0, 0, 0.0])
for r in arm_rows["full"]:
    if r[2] in ("WIN", "LOSS"):
        h = int(r[5][11:13]); hh[h][0] += 1
        if r[2] == "WIN": hh[h][1] += 1
        hh[h][2] += r[3]
worst = sorted(hh.items(), key=lambda x: x[1][2])[:5]
print("最亏的5个小时段:", [(f"{h:02d}:00", f"{v[2]:.0f}%", f"WR{v[1]}/{v[0]}") for h, v in worst])
