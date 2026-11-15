"""Authorized one-shot Pi release switch. Original JAR and DB stay at old paths."""
import hashlib,json,os,shlex,shutil,sqlite3,subprocess,sys,time,urllib.error,urllib.request,zipfile
from pathlib import Path
from paper_vnext_pi_prepare import ROOT,SERVICES,handoff,get


def ctl(*args):subprocess.run(['sudo','-n','systemctl',*args],check=True,stdout=subprocess.DEVNULL)
def rows(db):
    c=sqlite3.connect('file:'+str(db)+'?mode=ro',uri=True)
    tables=[r[0] for r in c.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")]
    result={t:c.execute('select count(*) from "'+t.replace('"','""')+'"').fetchone()[0] for t in tables};c.close();return result
def main(bundle,backup):
    backup=backup.resolve();assert backup.parent==ROOT/'backups';assert (backup/'prepare-result.json').is_file()
    release=ROOT/'releases/paper-vnext-20261115';assert not release.exists()
    release.mkdir(parents=True,mode=0o755)
    with zipfile.ZipFile(bundle) as z:
        assert all(not n.startswith('/') and '..' not in Path(n).parts for n in z.namelist());z.extractall(release)
    manifest=json.loads((release/'manifest.json').read_text())
    for name,digest in manifest['files'].items():assert hashlib.sha256((release/name).read_bytes()).hexdigest()==digest
    assert manifest['paper_only'] and not manifest['account_writes']
    assert manifest['java_tests']['failures']==manifest['java_tests']['errors']==0
    data=ROOT/'data/paper-vnext';assert not data.exists();data.mkdir(mode=0o700)
    metadata=ROOT/'data/paper-lab-meta.db';assert not metadata.exists()
    for name in ['research-summary.json','carry-evidence.json']:shutil.copyfile(release/name,data/name)
    override=Path('/etc/systemd/system/quanforge.service.d/90-paper-vnext.conf')
    worker_unit=Path('/etc/systemd/system/quanforge-paper-vnext.service')
    assert not override.exists() and not worker_unit.exists()
    # Fresh check occurs immediately before stopping the legacy trigger and manager.
    proof=handoff();(backup/'handoff-at-switch.json').write_text(json.dumps(proof,indent=2))
    for unit in SERVICES[1:]:ctl('disable','--now',unit)
    ctl('stop','v5_guard.service','quanforge-forward-monitor.service');ctl('stop','quanforge.service')
    db=ROOT/'data/quanforge.db';before=rows(db)
    c=sqlite3.connect('file:'+str(db)+'?mode=ro',uri=True);snapshot=sqlite3.connect(backup/'quanforge-final-at-switch.db');c.backup(snapshot);snapshot.close();c.close()
    hash_before=hashlib.sha256(db.read_bytes()).hexdigest()
    states=json.loads((backup/'service-states.json').read_text())
    try:
        private=backup/'private'
        args=['/mnt/nvme/jdk-24.0.1/bin/java','-Xms128m','-Xmx512m','-jar',str(release/'app.jar'),
            '--spring.profiles.active=paper','--server.port=40702','--app.paper-only=true',
            '--app.scheduling.enabled=false','--app.execution.account-writes-enabled=false',
            '--app.paper.root='+str(data),'--spring.datasource.url=jdbc:sqlite:'+str(metadata)+'?journal_mode=WAL&busy_timeout=5000',
            '--spring.config.additional-location=file:'+str(private/'legacy-application.yaml')+',file:'+str(private/'application-local.yaml')]
        conf=backup/'paper-override.conf';conf.write_text('[Service]\nExecStart=\nExecStart='+shlex.join(args)+'\n')
        subprocess.run(['sudo','-n','install','-d','-m','755',str(override.parent)],check=True)
        subprocess.run(['sudo','-n','install','-m','644',str(conf),str(override)],check=True)
        unit=backup/'paper-worker-unit.conf'
        unit.write_text('[Unit]\nDescription=QF-S 20U carry PAPER worker (public market GET only)\nAfter=network-online.target quanforge.service\nWants=network-online.target\nStartLimitIntervalSec=900\nStartLimitBurst=3\n\n[Service]\nType=simple\nUser=xingfeng\nWorkingDirectory='+str(release)+'\nUMask=0077\nExecStart=/usr/bin/python3 -u '+str(release/'tools/paper_vnext_carry_worker.py')+' --root '+str(data)+' --proxy-file '+str(data/'.proxy-runtime.json')+'\nRestart=on-failure\nRestartSec=20\nTimeoutStopSec=20\nNoNewPrivileges=true\nPrivateTmp=true\n\n[Install]\nWantedBy=multi-user.target\n')
        subprocess.run(['sudo','-n','install','-m','644',str(unit),str(worker_unit)],check=True)
        ctl('daemon-reload');ctl('start','quanforge.service')
        for _ in range(45):
            try:
                runtime=get('http://127.0.0.1:40702/api/runtime')
                if runtime.get('paperOnly') is True:break
            except Exception:pass
            time.sleep(1)
        else:raise RuntimeError('new paper server did not become ready')
        # Copy proxy row byte-for-byte, with the original private crypto key. No trading credentials copied.
        old=sqlite3.connect('file:'+str(db)+'?mode=ro',uri=True);columns=[r[1] for r in old.execute('pragma table_info(proxy_config)')]
        values=old.execute('select '+','.join(columns)+' from proxy_config where id=1').fetchone();old.close();assert values
        new=sqlite3.connect(metadata,timeout=5)
        with new:new.execute('insert into proxy_config('+','.join(columns)+') values('+','.join('?' for _ in columns)+')',values)
        assert new.execute('select count(*) from api_credential').fetchone()[0]==0;new.close()
        safe=get('http://127.0.0.1:40702/api/paper/proxy');assert safe['enabled'] and safe['host']==proof['proxy']['host'] and safe['port']==proof['proxy']['port']
        assert os.stat(data/'.proxy-runtime.json').st_mode&0o777==0o600
        ctl('enable','--now','quanforge-paper-vnext.service')
        for _ in range(50):
            try:
                report=get('http://127.0.0.1:40702/api/paper/status')
                if report['health']['last_quote_at'] and report['counts'].get('QUOTE',0)>=2:break
            except Exception:pass
            time.sleep(1)
        else:raise RuntimeError('new paper worker did not observe two quotes')
        assert not report['real_order_capability'] and report['accounting']['profit_protect']['ledger_cash_residual']=='0'
        for path in ['/api/credentials','/api/bybit/wallet-balance']:
            try:get('http://127.0.0.1:40702'+path)
            except urllib.error.HTTPError as e:assert e.code==403
            else:raise RuntimeError('legacy account route not blocked')
        assert rows(db)==before and hashlib.sha256(db.read_bytes()).hexdigest()==hash_before
        result=dict(at=int(time.time()*1000),runtime=runtime,release=str(release),backup=str(backup),
            proxy=safe,original_database_rows=before,original_database_unchanged=True,original_database_sha256=hash_before,
            artifact_sha256=manifest['files']['app.jar'],stage=report['stage'],counts=report['counts'],
            accounting=report['accounting'],legacy_account_routes_blocked=True,no_exchange_orders_sent=True)
        (backup/'deployment-result.json').write_text(json.dumps(result,indent=2));(data/'deployment-result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
    except Exception:
        ctl('stop','quanforge-paper-vnext.service');ctl('disable','quanforge-paper-vnext.service');ctl('stop','quanforge.service')
        if override.exists():subprocess.run(['sudo','-n','rm','--',str(override)],check=True)
        ctl('daemon-reload')
        for unit,state in states.items():
            if state['is-enabled']=='enabled':ctl('enable',unit)
            if state['is-active']=='active':ctl('start',unit)
        print(json.dumps(dict(deployment_failed=True,original_runtime_restored=True,backup=str(backup))))
        raise


if __name__=='__main__':main(Path(sys.argv[1]),Path(sys.argv[2]))
