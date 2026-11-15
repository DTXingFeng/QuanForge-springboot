"""Run on the authorized Pi: readonly Demo handoff check and private backup.

Does not stop services, modify credentials, or call exchange order endpoints.
"""
import hashlib,hmac,json,os,shutil,sqlite3,subprocess,time,urllib.parse,urllib.request,zipfile
from pathlib import Path

ROOT=Path('/mnt/nvme/quanforge')
SERVICES=['quanforge.service','quanforge-bridge.service','quanforge-model.service','quanforge-v5mech.service',
          'v5_guard.timer','quanforge-forward-monitor.timer']


def get(url):
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url,timeout=15) as r:return json.load(r)


def handoff():
    assert get('http://127.0.0.1:40702/api/bybit/mode')['mode']=='DEMO'
    def java(path,params):return get('http://127.0.0.1:40702/api/bybit/get?'+urllib.parse.urlencode(dict(endpoint=path,**params)))
    config=json.loads((ROOT/'tools/v5demo.json').read_text())
    assert urllib.parse.urlparse(config['base']).hostname=='api-demo.bybit.com'
    # Proxy comes from the existing application DB; optional auth remains in memory.
    db=sqlite3.connect('file:'+str(ROOT/'data/quanforge.db')+'?mode=ro',uri=True)
    proxy=db.execute('select enabled,type,host,port from proxy_config where id=1').fetchone();db.close()
    assert proxy and proxy[0] and proxy[1]=='HTTP'
    # Verified deployment uses an unauthenticated loopback listener. Fail instead of silently bypassing it.
    assert proxy[2]=='127.0.0.1' and proxy[3]==7890
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({'https':f'http://{proxy[2]}:{proxy[3]}'}))
    def shadow(path,params):
        query=urllib.parse.urlencode(params);stamp=str(int(time.time()*1000));key=config['api_key'];window='5000'
        signature=hmac.new(config['api_secret'].encode(),(stamp+key+window+query).encode(),hashlib.sha256).hexdigest()
        req=urllib.request.Request(config['base'].rstrip('/')+path+'?'+query,headers={'X-BAPI-API-KEY':key,'X-BAPI-TIMESTAMP':stamp,'X-BAPI-RECV-WINDOW':window,'X-BAPI-SIGN':signature})
        with opener.open(req,timeout=12) as r:return json.load(r)
    result={}
    for name,call in [('java_demo',java),('inactive_shadow_demo',shadow)]:
        checks={}
        for kind,path in [('positions','/v5/position/list'),('orders','/v5/order/realtime')]:
            params=dict(category='linear',settleCoin='USDT',limit=100)
            if kind=='orders':params['openOnly']=0
            count=0;seen=set()
            for _ in range(10):
                value=call(path,params);assert value.get('retCode')==0, f'{name} {kind} readonly probe failed'
                rows=value['result']['list'];count+=sum(float(r.get('size',0))!=0 for r in rows) if kind=='positions' else len(rows)
                cursor=value['result'].get('nextPageCursor')
                if not cursor:break
                assert cursor not in seen;seen.add(cursor);params['cursor']=cursor
            else:raise RuntimeError('incomplete account pagination')
            checks[kind]=dict(active_count=count,complete=True,retCode=0)
            assert count==0, f'{name} {kind} requires continued management; do not switch'
        result[name]=checks
    return dict(at=int(time.time()*1000),scope='Current legacy linear USDT Demo managers',accounts=result,
                proxy=dict(enabled=True,type=proxy[1],host=proxy[2],port=proxy[3]),no_exchange_orders_sent=True)


def backup():
    proof=handoff();dest=ROOT/'backups'/('paper-vnext-'+time.strftime('%Y%m%d-%H%M%S',time.gmtime()))
    dest.mkdir(parents=True,mode=0o700);os.chmod(dest,0o700)
    (dest/'handoff.json').write_text(json.dumps(proof,indent=2))
    states={}
    for unit in SERVICES:
        info={}
        for verb in ['is-active','is-enabled']:
            r=subprocess.run(['systemctl',verb,unit],capture_output=True,text=True);info[verb]=r.stdout.strip()
        states[unit]=info
        r=subprocess.run(['systemctl','cat',unit],capture_output=True,text=True);(dest/(unit+'.txt')).write_text(r.stdout)
    (dest/'service-states.json').write_text(json.dumps(states,indent=2))
    shutil.copy2(ROOT/'quanforge.jar',dest/'quanforge.jar')
    dbinfo={}
    for src in sorted((ROOT/'data').rglob('*')):
        if not src.is_file() or src.suffix not in ('.db','.sqlite'):continue
        relative=src.relative_to(ROOT);target=dest/relative;target.parent.mkdir(parents=True,exist_ok=True)
        original=sqlite3.connect('file:'+str(src)+'?mode=ro',uri=True);copy=sqlite3.connect(target);original.backup(copy)
        check=copy.execute('pragma integrity_check').fetchone()[0];assert check=='ok'
        tables=[r[0] for r in copy.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")]
        counts={t:copy.execute('select count(*) from "'+t.replace('"','""')+'"').fetchone()[0] for t in tables}
        copy.close();original.close();dbinfo[str(relative)]=dict(integrity=check,rows=counts,sha256=hashlib.sha256(target.read_bytes()).hexdigest())
    (dest/'database-backups.json').write_text(json.dumps(dbinfo,indent=2))
    private=dest/'private';private.mkdir(mode=0o700)
    with zipfile.ZipFile(ROOT/'quanforge.jar') as z:
        for name,output in [('application.yaml','legacy-application.yaml'),('application-local.yaml','application-local.yaml')]:
            data=z.read('BOOT-INF/classes/'+name);target=private/output;target.write_bytes(data);os.chmod(target,0o600)
    proof.update(backup=str(dest),database_count=len(dbinfo),original_jar_sha256=hashlib.sha256((dest/'quanforge.jar').read_bytes()).hexdigest())
    (dest/'prepare-result.json').write_text(json.dumps(proof,indent=2));print(json.dumps(proof))


if __name__=='__main__':backup()
