import sqlite3, math
print("== 前向深挖: 频率构成 + 5R显著性 + 时段分布 ==")
DBS = [("3R", "/mnt/nvme/quanforge/data/paper_trendrule.db"),
       ("5R", "/mnt/nvme/quanforge/data/paper_trendrule_tp5.db")]
for label, db in DBS:
    con = sqlite3.connect(db)
    print(f"\n[{label}]")
    print("  按symbol: ", con.execute(
        "select symbol, count(*), sum(case when status='WIN' then 1 else 0 end) "
        "from ai_advice_track where status in ('WIN','LOSS') group by symbol").fetchall())
    print("  按note: ", con.execute(
        "select note, count(*) from ai_advice_track where status in ('WIN','LOSS') "
        "group by note order by 2 desc limit 6").fetchall())
    print("  BLOCKED按note: ", con.execute(
        "select substr(note,1,12), count(*) from ai_advice_track where status='BLOCKED' "
        "group by 1 order by 2 desc limit 4").fetchall())
    rows = con.execute(
        "select result_pct from ai_advice_track where status in ('WIN','LOSS')").fetchall()
    pcts = [r[0] for r in rows]
    n = len(pcts); mean = sum(pcts)/n
    var = sum((p-mean)**2 for p in pcts)/(n-1)
    se = math.sqrt(var/n)
    t = mean/se if se > 0 else 0
    print(f"  n={n} 均笔={mean:+.4f}% se={se:.4f} t={t:+.2f} "
          f"(t>2 显著为正)")

print("\n== 触发源(全臂plan日志, 急动/冲量/扫描) ==")
import collections, re
src = collections.Counter()
for f in ("/mnt/nvme/quanforge/logs/paper.log", "/mnt/nvme/quanforge/logs/paper5.log"):
    for line in open(f, encoding="utf-8", errors="ignore"):
        m = re.search(r"\((急动|冲量|扫描)", line)
        if "[plan]" in line and m:
            src[m.group(1)] += 1
print(dict(src))
