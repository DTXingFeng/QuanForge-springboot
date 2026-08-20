#!/usr/bin/env python3
"""晨间总检: 模拟盘 / LLM延迟臂 / v4.7 demo / 系统状态"""
import sqlite3, subprocess, time, datetime, glob, os

def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()

print("== Pi 时间/负载 ==")
print(sh("date '+%F %T %Z'"), "|", sh("uptime | awk -F'load average:' '{print $2}'"))
print(sh("free -m | awk 'NR==2{printf \"mem: %s/%sMB avail %sMB\", $3,$2,$7}'"))
print("paper svc:", sh("systemctl is-active quanforge-paper"),
      "| backtest procs:", sh("ps aux | grep -c '[b]acktest.py'"))

print("\n== 模拟盘 trend-rule (paper.log) ==")
print("plan:", sh("grep -c '\\[plan\\]' /mnt/nvme/quanforge/logs/paper.log"),
      "fill:", sh("grep -c '\\[fill\\]' /mnt/nvme/quanforge/logs/paper.log"),
      "settle:", sh("grep -c '\\[settle\\]' /mnt/nvme/quanforge/logs/paper.log"),
      "ws_err:", sh("grep -c 'ws err' /mnt/nvme/quanforge/logs/paper.log"))
print(sh("grep '\\[beat\\]' /mnt/nvme/quanforge/logs/paper.log | tail -3"))
print(sh("grep '\\[plan\\]\\|\\[fill\\]\\|\\[settle\\]' /mnt/nvme/quanforge/logs/paper.log | tail -12"))
if os.path.exists("/mnt/nvme/quanforge/data/paper_trendrule.db"):
    con = sqlite3.connect("/mnt/nvme/quanforge/data/paper_trendrule.db")
    print("DB状态分布:", con.execute("select status,count(*) from ai_advice_track group by status").fetchall())
    rs = con.execute("select result_pct from ai_advice_track where status in ('WIN','LOSS')").fetchall()
    if rs:
        w = [r[0] for r in rs if r[0] > 0]
        print(f"已结算: n={len(rs)} W/L={len(w)}/{len(rs)-len(w)} 累计={sum(r[0] for r in rs):+.2f}%")
    print("权益快照:", con.execute("select * from equity_snap order by ts desc limit 3").fetchall())

print("\n== LLM 延迟臂 (lat2/live) ==")
for a in ("lat2", "live"):
    tails = []
    for k in range(6):
        t = sh(f"tail -1 /tmp/btp/seg_{a}_{k}.log 2>/dev/null")
        tails.append(t)
    done = sum(1 for t in tails if "[done]" in t)
    print(f"{a}: {done}/6 段完成")
    for k, t in enumerate(tails):
        print(f"  seg{k}: {t}")

print("\n== v4.7 demo (Java) ==")
con = sqlite3.connect("/mnt/nvme/quanforge/data/quanforge.db")
for r in con.execute("select status,count(*) from ai_advice_track "
                     "where created_at > datetime('now','-1 day') group by status"):
    print("近24h:", r)
rs = con.execute("select result_pct from ai_advice_track "
                 "where status in ('WIN','LOSS') and sys_version like 'v4.7%'").fetchall()
if rs:
    w = [r[0] for r in rs if r[0] > 0]
    print(f"v4.7 累计(实盘demo): n={len(rs)} W/L={len(w)}/{len(rs)-len(w)} "
          f"合计={sum(r[0] for r in rs):+.2f}%")
