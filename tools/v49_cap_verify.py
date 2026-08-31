#!/usr/bin/env python3
"""v4.9-砍尾验证: 前向宽尾深挖 + 置换检验 + 回测泄露盈亏平衡分析"""
import sqlite3, random, collections

def load(db):
    con = sqlite3.connect(db)
    rows = con.execute(
        "select symbol, entry, stop_loss, result_pct, settled_at from ai_advice_track "
        "where status in ('WIN','LOSS') and entry>0 and stop_loss>0 order by settled_at").fetchall()
    con.close()
    return [(r[0], abs(r[2] - r[1]) / r[1] * 100, r[3], r[4]) for r in rows]

fwd5 = load("/mnt/nvme/quanforge/data/paper_trendrule_tp5.db")
fwd3 = load("/mnt/nvme/quanforge/data/paper_trendrule.db")

print("== [A] 前向5R宽尾(risk0>=1.0%)深挖 ==")
wide = [t for t in fwd5 if t[1] >= 1.0]
nar = [t for t in fwd5 if t[1] < 1.0]
be = sum(1 for t in wide if abs(t[2]) <= 0.05)
w = sum(1 for t in wide if t[2] > 0.05)
l = sum(1 for t in wide if t[2] < -0.05)
print(f"n={len(wide)}: 真赢={w} 保本={be} 真亏={l}")
print(f"  宽尾亏损构成: " + " ".join(f"{t[2]:+.2f}" for t in sorted(wide, key=lambda x: x[2])[:10]))
bysym = collections.defaultdict(lambda: [0, 0.0])
for t in wide:
    bysym[t[0]][0] += 1
    bysym[t[0]][1] += t[2]
print(f"  按币: {dict((k, (v[0], round(v[1], 2))) for k, v in bysym.items())}")
byreg = collections.defaultdict(lambda: [0, 0.0])
for t in wide:
    k = "高波动(8/20-25)" if t[3] < "2026-08-26" else "低波动(8/26-)"
    byreg[k][0] += 1
    byreg[k][1] += t[2]
for k, (n, s) in byreg.items():
    print(f"  {k}: n={n} sum={s:+.2f}pp")
for th in [1.0, 1.25, 1.5]:
    xs = [t[2] for t in fwd5 if t[1] >= th]
    if xs:
        print(f"  阈值{th}: n={len(xs)} W={sum(1 for x in xs if x>0)} sum={sum(xs):+.2f}pp avg={sum(xs)/len(xs):+.3f}%")

print("\n== [B] 置换检验: 宽vs窄 均笔差 (5R前向) ==")
obs = (sum(t[2] for t in nar) / len(nar)) - (sum(t[2] for t in wide) / len(wide))
pcts = [t[2] for t in fwd5]
k = len(wide)
random.seed(42)
cnt = 0
N = 20000
for _ in range(N):
    idx = random.sample(range(len(pcts)), k)
    g = [pcts[i] for i in idx]
    h = [pcts[i] for i in range(len(pcts)) if i not in set(idx)]
    if (sum(h) / len(h)) - (sum(g) / len(g)) >= obs:
        cnt += 1
print(f"观测差(窄-宽)={obs:+.3f}pp/笔 | 置换p值={cnt/N:.4f} (单尾)")

print("\n== [C] 回测泄露盈亏平衡分析 ==")
bt5 = load("/mnt/nvme/quanforge/data/backtest_final5.db")
clean = [t for t in bt5 if t[1] >= 0.05]
leak = [t for t in bt5 if t[1] < 0.05]
btwide = [t for t in clean if t[1] >= 1.0]
dmg = sum(t[2] for t in btwide)
leak_gain = sum(t[2] for t in leak)
print(f"回测: 泄露单(保本覆写) n={len(leak)} 贡献={leak_gain:+.1f}pp (均{leak_gain/len(leak):+.3f})")
print(f"      宽尾-从未保本 n={len(btwide)} 贡献={dmg:+.1f}pp (均{dmg/len(btwide):+.3f})")
f_be = -dmg / leak_gain
print(f"盈亏平衡: 需 {f_be*100:.1f}% 的保止单原本是宽止损(risk0>=1.0), 砍尾才变亏")
wide_frac_clean = len(btwide) / len(clean)
print(f"参照: 从未保本组里宽止损占比 = {wide_frac_clean*100:.1f}%")
print(f"      若保本与初始宽止损独立 -> 期望净收益 = {-dmg - wide_frac_clean*leak_gain:+.1f}pp")

print("\n== [D] 3R对照再确认 ==")
w3 = [t[2] for t in fwd3 if t[1] >= 1.0]
n3 = [t[2] for t in fwd3 if t[1] < 1.0]
print(f"3R前向: 宽n={len(w3)} avg={sum(w3)/len(w3):+.3f}% | 窄n={len(n3)} avg={sum(n3)/len(n3):+.3f}%")

print("\n== [E] 频率代价 ==")
print(f"5R前向砍尾比例: {len(wide)}/{len(fwd5)} = {100*len(wide)/len(fwd5):.1f}%")
