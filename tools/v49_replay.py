#!/usr/bin/env python3
"""v4.9 验证回放: risk0门槛过滤入场, 其余与5R裸臂同构(risk sizing/保本/TTL全继承结算行)

核心问题: 只交易 risk0<=GATE 的单, 权益曲线/DD/月度/连亏 vs 5R裸臂如何?
注意: 过滤是按"入场时已知的risk0"——回测库的stop_loss是初始止损(保本移动发生在持仓中,
不改库), 所以过滤条件无未来函数。
"""
import sqlite3, collections

RISK = 1.0
START = 200.0

def replay(db, gate=None):
    con = sqlite3.connect(db)
    rows = con.execute(
        "select created_at, settled_at, symbol, action, entry, stop_loss, "
        "take_profit, status, result_pct from ai_advice_track "
        "where status in ('WIN','LOSS') order by settled_at").fetchall()
    con.close()
    # 剔脏: stop_loss缺失/0 会让risk sizing爆炸(历史bug遗留, 裸臂基线需干净)
    rows = [r for r in rows if r[4] and r[5] and r[4] > 0 and r[5] > 0]
    if gate is not None:
        rows = [r for r in rows if abs(r[5] - r[4]) / r[4] * 100 <= gate]
    eq = START
    peak = eq
    mdd = 0.0
    trough = eq
    cur = eq
    by_month = collections.defaultdict(lambda: [0, 0, 0.0])
    streak = maxstreak = 0
    eqs = []
    for c_at, s_at, sym, act, entry, sl, tp, st, pct in rows:
        sl_pct = abs(entry - sl) / entry * 100
        base = min(eq * RISK / sl_pct, eq * 5.0) if sl_pct > 0.01 else eq * 5.0
        eq += base * pct / 100
        peak = max(peak, eq)
        mdd = min(mdd, (eq - peak) / peak * 100)
        trough = min(trough, eq)
        m = s_at[:7]
        by_month[m][0] += 1
        by_month[m][1] += 1 if pct > 0 else 0
        by_month[m][2] += pct
        streak = streak + 1 if pct < 0 else 0
        maxstreak = max(maxstreak, streak)
        eqs.append(eq)
    # maxstreak 已记录
    n = len(rows)
    wins = sum(1 for r in rows if r[8] > 0)
    pcts = [r[8] for r in rows]
    # t-stat vs 0
    import math
    mean = sum(pcts) / n if n else 0
    var = sum((p - mean) ** 2 for p in pcts) / (n - 1) if n > 1 else 0
    t = mean / math.sqrt(var / n) if n > 1 and var > 0 else 0
    return dict(n=n, wr=100 * wins / n if n else 0, avg=mean, t=t, eq=eq,
                mdd=mdd, trough=trough, streak=maxstreak,
                months=by_month, rows=rows, eqs=eqs)

def show(tag, r):
    print(f"[{tag}] n={r['n']} WR={r['wr']:.1f}% 均笔={r['avg']:+.3f}% t={r['t']:+.1f}")
    print(f"  权益 {START:.0f} -> {r['eq']:.1f} ({(r['eq']/START-1)*100:+.1f}%) "
          f"maxDD={r['mdd']:.1f}% 谷底={r['trough']:.1f} 最大连亏={r['streak']}")
    for m in sorted(r['months']):
        c, w, s = r['months'][m]
        print(f"    {m}: n={c:<4} WR={100*w/c:>4.0f}% 价格和={s:+8.1f}pp")

DB5 = "/mnt/nvme/quanforge/data/backtest_final5.db"
print("=" * 60)
print("v4.9 验证: 5R + risk0门槛 (引擎同构回放, 结算行全继承, 只过滤入场)")
print("=" * 60)
show("5R 裸臂(现状)", replay(DB5))
for gate in [0.45, 0.50, 0.55]:
    print()
    show(f"v4.9 GATE={gate}%", replay(DB5, gate))
