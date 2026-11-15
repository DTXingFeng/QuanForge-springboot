"""Read-only QF-S runtime evidence export. Never imports deployed trading code.

Only whitelisted strategy tables/columns leave the Pi. Credentials are excluded.
"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

REMOTE=r'''
import sqlite3,json,pathlib,subprocess,hashlib,time
root=pathlib.Path('/mnt/nvme/quanforge');data=root/'data'
out={'observed_utc_ms':int(time.time()*1000),'databases':{},'services':{}}
for service in ['quanforge.service','quanforge-v5mech.service','quanforge-paper.service','quanforge-paper5.service','quanforge-paper5c.service','quanforge-forward-monitor.service']:
    result=subprocess.run(['systemctl','show',service,'-p','ActiveState','-p','SubState','-p','ExecMainStartTimestamp','-p','ExecMainExitTimestamp','-p','MainPID'],capture_output=True,text=True)
    out['services'][service]=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
out['deployed_jar_sha256']=hashlib.sha256((root/'quanforge.jar').read_bytes()).hexdigest()
for name in ['quanforge.db','paper_v5mech.db','paper_trendrule.db','paper_trendrule_tp5.db','paper_trendrule_tp5c.db']:
    c=sqlite3.connect((data/name).as_uri()+'?mode=ro',uri=True);c.row_factory=sqlite3.Row
    c.execute('begin')
    columns={r[1] for r in c.execute('pragma table_info(ai_advice_track)')}
    allowed=['id','symbol','action','status','result_pct','created_at','entered_at','settled_at','sys_version','exec_mode','entry','actual_entry','actual_exit','qty','stop_loss','take_profit','rebased_at','note']
    item={'tracks':[dict(r) for r in c.execute('select '+','.join(x for x in allowed if x in columns)+' from ai_advice_track order by id')], 'source_mtime_ns':(data/name).stat().st_mtime_ns}
    if name=='quanforge.db':
        flags=['enabled','auto_order_enabled','scan_interval_minutes','leverage','auto_margin_pct','watch_symbols','updated_at']
        item['safe_config']=[dict(r) for r in c.execute('select '+','.join(flags)+' from ai_config')]
    else:
        item['equity_snapshots']=[dict(r) for r in c.execute('select ts,eq_sizing,equity,fixed_equity from equity_snap order by rowid')]
    c.rollback();c.close();out['databases'][name]=item
print(json.dumps(out,ensure_ascii=True))
'''


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.parent.mkdir(parents=True,exist_ok=True)
    if args.output.exists(): raise ValueError('refuse overwrite captured history')
    result=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=8','xingfeng@192.168.8.240','python3','-'],
        input=REMOTE.encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=40,check=True)
    captured=json.loads(result.stdout)
    with args.output.open('xb') as f: f.write(result.stdout)
    print(json.dumps(dict(file=str(args.output),sha256=hashlib.sha256(result.stdout).hexdigest(),
        observed_utc_ms=captured['observed_utc_ms'],rows={name:len(item['tracks']) for name,item in captured['databases'].items()})))


if __name__=='__main__': main()
