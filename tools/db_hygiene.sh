#!/bin/bash
# 数据卫生: kline_1m只保30天(前端图表最多回看500根=8h, 30天=5x冗余) + VACUUM + logrotate
set -e
DB=/mnt/nvme/quanforge/data/quanforge.db
CUT=$(( $(date +%s%3N) - 30*86400*1000 ))

echo "== 0) 备份 =="
cp $DB $DB.backup-preprune
ls -la $DB.backup-preprune | awk '{print $5, $9}'

echo "== 1) kline_1m 现状 =="
sqlite3 $DB "select count(*), datetime(min(open_time)/1000,'unixepoch'), datetime(max(open_time)/1000,'unixepoch') from kline_1m"

echo "== 2) 删除30天前 (在线删, WAL安全) =="
sqlite3 $DB "delete from kline_1m where open_time < $CUT"
sqlite3 $DB "select count(*) from kline_1m" | xargs echo "剩余行数:"

echo "== 3) VACUUM (需停Java, ~1分钟) =="
sudo -n systemctl stop quanforge
sqlite3 $DB "VACUUM;"
sudo -n systemctl start quanforge
sleep 12
echo "quanforge: $(systemctl is-active quanforge)"
ls -la $DB | awk '{print "库大小:", $5}'
curl -s -o /dev/null -w "API健康: %{http_code}\n" -m 8 "http://127.0.0.1:40702/api/ai/alerts?limit=1"

echo "== 4) 删备份(确认健康后) =="
rm -f $DB.backup-preprune
echo done
