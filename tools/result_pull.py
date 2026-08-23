import sqlite3, math
from collections import defaultdict

BT = {"3R": (0.031, 25.2), "5R": (0.099, 19.2)}   # 回测: 均笔%, WR%
DBS = [("3R", "/mnt/nvme/quanforge/data/paper_trendrule.db"),
       ("5R", "/mnt/nvme/quanforge/data/paper_trendrule_tp5.db")]

for label, db in DBS:
    con = sqlite3.connect(db)
    rows = con.execute("select symbol, status, result_pct, settled_at, note "
                       "from ai_advice_track where status in ('WIN','LOSS') "
                       "order by id").fetchall()
    pcts = [r[2] for r in rows]
    n = len(pcts)
    if n < 2:
        print(f"[{label}] 样本不足 n={n}"); con.close(); continue
    wins = [p for p in pcts if p > 0]
    wr = 100 * len(wins) / n
    mean = sum(pcts) / n
    var = sum((p - mean) ** 2 for p in pcts) / (n - 1)
    se = math.sqrt(var / n)
    t0 = mean / se
    mu = BT[label][0]
    tmu = (mean - mu) / se

    snaps = con.execute("select ts, equity from equity_snap order by ts").fetchall()
    eqs = [s[1] for s in snaps]
    peak, mdd = eqs[0], 0.0
    for e in eqs:
        peak = max(peak, e)
        mdd = min(mdd, (e - peak) / peak * 100)
    trough = min(eqs)

    day = defaultdict(lambda: [0, 0, 0.0])
    for r in rows:
        d = (r[3] or "")[:10]
        day[d][0] += 1
        day[d][1] += 1 if r[2] > 0 else 0
        day[d][2] += r[2]
    sym = defaultdict(lambda: [0, 0, 0.0])
    for r in rows:
        sym[r[0]][0] += 1
        sym[r[0]][1] += 1 if r[2] > 0 else 0
        sym[r[0]][2] += r[2]
    mcl = cur = 0
    for p in pcts:
        cur = cur + 1 if p < 0 else 0
        mcl = max(mcl, cur)
    opens = con.execute("select symbol, action, entry, stop_loss, take_profit, "
                        "created_at from ai_advice_track where status='OPEN'").fetchall()
    blocked = con.execute("select substr(note,1,14) bn, count(*) c from ai_advice_track "
                          "where status='BLOCKED' group by 1 order by 2 desc limit 5").fetchall()
    winnotes = con.execute("select note, count(*) from ai_advice_track "
                           "where status='WIN' group by 1").fetchall()

    print(f"===== {label} (截至 {snaps[-1][0]}) =====")
    print(f"n={n} W={len(wins)} L={n - len(wins)} WR={wr:.1f}% (回测{BT[label][1]}%)")
    print(f"均笔={mean:+.3f}% se={se:.3f} t(vs0)={t0:+.2f} | vs回测{mu:+.3f}%: "
          f"差{mean - mu:+.3f}pp t={tmu:+.2f}")
    print(f"中位={sorted(pcts)[n // 2]:+.3f}% 盈极值={max(pcts):+.2f}% "
          f"亏极值={min(pcts):+.2f}% 累计={sum(pcts):+.1f}pp 最大连亏={mcl}")
    print(f"权益 {eqs[0]:.1f} -> {eqs[-1]:.1f} ({(eqs[-1] / eqs[0] - 1) * 100:+.1f}%) "
          f"maxDD={mdd:.1f}% 谷底={trough:.1f}")
    print("按日:")
    for d in sorted(day):
        c, w, s = day[d]
        print(f"  {d}: n={c} WR={100 * w / c:.0f}% 累{sum(p for p in [s]):+.1f}pp")
    print("按币:")
    for k in sorted(sym, key=lambda k: -sym[k][0]):
        c, w, s = sym[k]
        print(f"  {k}: n={c} W={w} 和={s:+.2f}pp")
    print(f"WIN构成: {winnotes}")
    print(f"在场: {opens}")
    print(f"拦截: {blocked}")
    print("近8笔:")
    for r in rows[-8:]:
        print(f"  {r[3]} {r[0]} {r[2]:+.2f}% {r[4] or ''}")
    con.close()
