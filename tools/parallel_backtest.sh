#!/usr/bin/env bash
# 并行分段回测驱动：把 30 天切成 N 段并行跑同一臂，完成后合并账本。
# 用法: parallel_backtest.sh <arm> <days_total> <segments> <budget_total> <out_db> <latency>
set -e
ARM="$1"; DAYS="$2"; SEGS="$3"; BUDGET="$4"; OUT="$5"; LAT="${6:-0}"
SEG_DAYS=$(( DAYS / SEGS ))
LOG_DIR=/tmp/btp
mkdir -p "$LOG_DIR"
PIDS=()
for k in $(seq 0 $((SEGS-1))); do
  SEG_OUT="$LOG_DIR/seg_${ARM}_$k.db"
  SEG_LOG="$LOG_DIR/seg_${ARM}_$k.log"
  rm -f "$SEG_OUT"
  python3 /mnt/nvme/quanforge/tools/backtest.py \
    --days $(( SEG_DAYS + 1 )) --arm "$ARM" --budget "$BUDGET" \
    --latency "$LAT" --out "$SEG_OUT" --seg-offset $(( k * SEG_DAYS )) \
    > "$SEG_LOG" 2>&1 &
  PIDS+=($!)
  echo "seg$k (offset $(( k * SEG_DAYS ))d) pid=${PIDS[-1]}"
done
echo "waiting for ${#PIDS[@]} segments..."
FAIL=0
for p in "${PIDS[@]}"; do wait "$p" || FAIL=1; done
if [ "$FAIL" = "1" ]; then echo "some segment failed, check $LOG_DIR"; exit 1; fi
# 合并
rm -f "$OUT"
python3 - "$LOG_DIR" "$ARM" "$SEGS" "$OUT" <<'PYEOF'
import sqlite3, sys, glob
log_dir, arm, segs, out = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
con = sqlite3.connect(out)
con.execute("""create table ai_advice_track(
    id integer primary key autoincrement, symbol text, action text,
    entry real, stop_loss real, take_profit real, status text,
    result_pct real, note text, sys_version text,
    created_at text, entered_at text, settled_at text, llm_ms integer)""")
n = 0
for k in range(segs):
    db = f"{log_dir}/seg_{arm}_{k}.db"
    rows = sqlite3.connect(db).execute(
        "select symbol,action,entry,stop_loss,take_profit,status,result_pct,note,"
        "sys_version,created_at,entered_at,settled_at,llm_ms from ai_advice_track").fetchall()
    con.executemany("insert into ai_advice_track(symbol,action,entry,stop_loss,take_profit,"
                    "status,result_pct,note,sys_version,created_at,entered_at,settled_at,llm_ms)"
                    " values(?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    n += len(rows)
    print(f"seg{k}: {len(rows)} rows")
con.commit()
print(f"merged {n} rows -> {out}")
PYEOF
