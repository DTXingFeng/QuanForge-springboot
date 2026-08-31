#!/usr/bin/env python3
"""前向验证常备报表: 模拟盘(3R/5R) vs 回测预测基准
用法: python3 paper_status.py   (Pi上随时跑, 零依赖之外的python标准库+sqlite3)"""
import sqlite3, subprocess, time, datetime, os

def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()

PAPERS = [
    ("3R对照", "/mnt/nvme/quanforge/data/paper_trendrule.db", "paper.log"),
    ("5R主候选", "/mnt/nvme/quanforge/data/paper_trendrule_tp5.db", "paper5.log"),
    ("5C砍尾", "/mnt/nvme/quanforge/data/paper_trendrule_tp5c.db", "paper5c.log"),
]
# 回测预测基准(6个月矩阵, alts-only + ATR门槛0.32, 2026-08-20切换观察列表后口径)
# 3R保本线25% / 5R保本线16.7%
# 风险平价权益路径参考(引擎同构重跑): 3R 200->112(-44%) / 5R 200->556(+178%)
# 5C(v4.9)=5R+risk0>=1.0%拒单: 参照同5R回测, 判定口径=与5R臂差分(砍掉的尾巴均-0.542%)
BENCH = {"3R对照": dict(wr=25.2, pnl_per_trade=0.0307, trades_day=11.0, eq_ref=112.0),
         "5R主候选": dict(wr=19.2, pnl_per_trade=0.0990, trades_day=9.5, eq_ref=556.0),
         "5C砍尾": dict(wr=19.2, pnl_per_trade=0.0990, trades_day=8.7, eq_ref=556.0)}

now_str = sh("date '+%F %T'")
print(f"== 前向验证报表 {now_str} ==")
print("服务:", sh("systemctl is-active quanforge-paper quanforge-paper5 | tr '\\n' ' '"),
      "| v4.7:", sh("systemctl is-active quanforge"))
for label, db, lg in PAPERS:
    print(f"\n----- {label} ({os.path.basename(db)}) -----")
    if not os.path.exists(db):
        print("  账本不存在"); continue
    con = sqlite3.connect(db)
    try:
        cnt = dict(con.execute("select status,count(*) from ai_advice_track "
                               "group by status").fetchall())
    except Exception as e:
        print("  账本读取失败:", e); continue
    if not cnt:
        print("  空(尚无事件)")
    else:
        print("  事件:", cnt)
        rs = con.execute("select result_pct from ai_advice_track "
                         "where status in ('WIN','LOSS')").fetchall()
        if rs:
            pcts = [r[0] for r in rs]
            w = [p for p in pcts if p > 0]
            days = max((datetime.datetime.now() - datetime.datetime(2026, 8, 20)).days, 1)
            b = BENCH[label]
            print(f"  已结算 n={len(pcts)} WR={len(w)/len(pcts)*100:.1f}% "
                  f"(回测预测 {b['wr']}%)")
            print(f"  均笔={sum(pcts)/len(pcts):+.3f}% (预测 {b['pnl_per_trade']:+.3f}%) "
                  f"累计={sum(pcts):+.1f}% 频率={len(pcts)/days:.1f}笔/天 (预测 ~{b['trades_day']})")
        eq = con.execute("select equity,fixed_equity from equity_snap "
                         "order by ts desc limit 1").fetchone()
        if eq:
            print(f"  权益: eq-sizing={eq[0]:.1f} fixed={eq[1]:.1f} (起点200)")
    # 拦截分布(volgate是否在工作)
    blocks = con.execute("select count(*) from ai_advice_track "
                         "where status='BLOCKED' and note like 'volgate%'").fetchone()
    print(f"  volgate拦截: {blocks[0] if blocks else 0}")
    # 最近5条日志
    tail = sh(f"tail -3 /mnt/nvme/quanforge/logs/{lg}")
    print("  日志尾:", " || ".join(tail.splitlines()[-2:]))
