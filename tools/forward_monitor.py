#!/usr/bin/env python3
"""前向验证自动监控: 每次运行把 paper_status + paper_vs_backtest 追加到
data/forward_validation.log (带时间戳分节), 供随时查阅/回放.
由 systemd timer (quanforge-forward-monitor.timer) 每日两次驱动.
用法: python3 tools/forward_monitor.py"""
import subprocess, sys, datetime, os

LOG = "/mnt/nvme/quanforge/data/forward_validation.log"
TOOLS = "/mnt/nvme/quanforge/tools"

def run(script):
    r = subprocess.run([sys.executable, f"{TOOLS}/{script}"],
                       capture_output=True, text=True, timeout=120)
    return (r.stdout + (("\n[stderr]\n" + r.stderr) if r.stderr.strip() else "")).strip()

now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
out = []
out.append(f"{'='*70}\n== {now} 前向验证快照 ==")
for s in ("paper_status.py", "paper_vs_backtest.py"):
    try:
        out.append(run(s))
    except Exception as e:
        out.append(f"[{s}] 执行失败: {e}")

with open(LOG, "a", encoding="utf-8") as f:
    f.write("\n\n" + "\n\n".join(out) + "\n")
print("\n\n".join(out))
print(f"[monitor] appended to {LOG} ({os.path.getsize(LOG)} bytes total)")
