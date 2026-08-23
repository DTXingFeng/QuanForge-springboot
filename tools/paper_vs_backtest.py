#!/usr/bin/env python3
"""前向 vs 回测 逐日对齐比对: 模拟盘实绩 与 同配置参考回测(backtest_finalX)
按日历日对齐: 频率/WR/均笔 三指标, 前向累计 vs 回测同期期望.
参照系: 回测同期 n>=30 用同期均笔; 否则回退全期回测均笔(回测库止于前向起点, 同期恒为0).
用法: python3 paper_vs_backtest.py   (样本到量后随时跑)"""
import sqlite3, datetime, math, os

PAIRS = [
    ("3R", "/mnt/nvme/quanforge/data/paper_trendrule.db",
     "/mnt/nvme/quanforge/data/backtest_final3.db"),
    ("5R", "/mnt/nvme/quanforge/data/paper_trendrule_tp5.db",
     "/mnt/nvme/quanforge/data/backtest_final5.db"),
]

def daily(db):
    if not os.path.exists(db):
        return {}
    con = sqlite3.connect(db)
    agg = {}
    for ts, pct in con.execute(
            "select settled_at, result_pct from ai_advice_track "
            "where status in ('WIN','LOSS') and settled_at is not null"):
        d = ts[:10]
        a = agg.setdefault(d, [0, 0, 0.0])
        a[0] += 1
        if pct > 0:
            a[1] += 1
        a[2] += pct
    return agg

print(f"== 前向 vs 回测 逐日比对  {datetime.datetime.now():%F %T} ==")
for label, pdb, bdb in PAIRS:
    p, b = daily(pdb), daily(bdb)
    if not p:
        print(f"\n[{label}] 模拟盘尚无已结算样本")
        continue
    print(f"\n[{label}]  {'日期':<12}{'前向 n/WR/累计%':>26}{'回测同日 n/WR/累计%':>26}")
    tot_p = [0, 0, 0.0]
    tot_b = [0, 0, 0.0]
    for d in sorted(p):
        a = p[d]
        m = b.get(d, [0, 0, 0.0])
        tot_p[0] += a[0]; tot_p[1] += a[1]; tot_p[2] += a[2]
        tot_b[0] += m[0]; tot_b[1] += m[1]; tot_b[2] += m[2]
        wr_p = f"{a[1]/a[0]*100:.0f}%" if a[0] else "-"
        wr_b = f"{m[1]/m[0]*100:.0f}%" if m[0] else "-"
        print(f"  {d:<12}{a[0]:>10} {wr_p:>6} {a[2]:>+8.1f}%"
              f"{m[0]:>13} {wr_b:>6} {m[2]:>+8.1f}%")
    n = tot_p[0]
    wr = tot_p[1]/n*100 if n else 0
    avg = tot_p[2]/n if n else 0
    nb = tot_b[0]
    wrb = tot_b[1]/nb*100 if nb else 0
    avgb = tot_b[2]/nb if nb else 0
    print(f"  {'合计':<12} 前向: n={n} WR={wr:.1f}% 均笔={avg:+.4f}% 累计={tot_p[2]:+.2f}%")
    # 参照系: 同期n>=30用同期, 否则全期回测期望(修复: 原版nb=0时拿0当参照, 误判"优于")
    nf = wf = 0
    sumf = 0.0
    if os.path.exists(bdb):
        con = sqlite3.connect(bdb)
        nf = con.execute("select count(*), sum(case when result_pct>0 then 1 else 0 end), "
                         "coalesce(sum(result_pct),0) from ai_advice_track "
                         "where status in ('WIN','LOSS')").fetchone()
        nf, wf, sumf = nf
        con.close()
    avgf = sumf/nf if nf else 0.0
    if nb >= 30:
        ref, refname = avgb, f"回测同期(n={nb})"
    elif nf > 0:
        ref, refname = avgf, f"全期回测(n={nf}, WR={wf/nf*100:.1f}%)"
        print(f"  {'':<12} 回测同期无样本(回测库止于前向起点), 参照{refname}: 均笔={avgf:+.4f}%")
    else:
        ref, refname = None, "无"
    if nb > 0:
        print(f"  {'':<12} 回测同期: n={nb} WR={wrb:.1f}% 均笔={avgb:+.4f}% 累计={tot_b[2]:+.2f}%")
    if n >= 30 and ref is not None:
        diff = avg - ref
        verdict = "符合回测" if abs(diff) < 0.05 else ("优于回测" if diff > 0 else "劣于回测")
        pcts = [p for p, in sqlite3.connect(pdb).execute(
                    "select result_pct from ai_advice_track "
                    "where status in ('WIN','LOSS')")]
        se = math.sqrt(sum((x-avg)**2 for x in pcts)/(len(pcts)-1)/len(pcts)) if len(pcts) > 1 else 0
        t = diff/se if se > 0 else 0
        print(f"  判定(n={n}≥30, 参照={refname}): 前向均笔{avg:+.4f}% vs {ref:+.4f}% "
              f"差{diff:+.4f}pp (t={t:+.2f}) -> {verdict}")
    elif n >= 30:
        print(f"  判定(n={n}≥30): 无可用回测参照, 跳过")
    else:
        print(f"  判定: 样本不足(n={n}<30), 攒够再判")
