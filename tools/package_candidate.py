"""Build a local review bundle from an already tested artifact. Never deploys or reads credentials."""
import argparse
import hashlib
import json
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(jar):
    reports=list((ROOT/'target/surefire-reports').glob('TEST-*.xml'))
    if not reports:raise ValueError('missing tests')
    totals={key:0 for key in ['tests','failures','errors','skipped']};cases=set()
    for report in reports:
        suite=ET.parse(report).getroot()
        for key in totals:totals[key]+=int(suite.get(key,0))
        cases.update(case.get('name') for case in suite.findall('testcase') if not list(case))
    # Testcases may contain system-out, so include any with no actual failure/error/skip.
    for report in reports:
        for case in ET.parse(report).getroot().findall('testcase'):
            if not any(case.find(tag) is not None for tag in ['failure','error','skipped']):cases.add(case.get('name'))
    if totals['tests']==0 or any(totals[key] for key in ['failures','errors','skipped']):raise ValueError('tests not clean')
    required={'defaultClientMustBlockAllAccountWritesBeforeCreatingRequest','observerConfigurationDisablesScheduledTasks'}
    if not required<=cases:raise ValueError('write/scheduler gates not verified')
    inputs=list((ROOT/'src').rglob('*.java'))+[ROOT/'pom.xml',ROOT/'src/main/resources/application.yaml',ROOT/'src/test/resources/application.yaml']
    if max(p.stat().st_mtime for p in inputs)>min(p.stat().st_mtime for p in reports):raise ValueError('test evidence predates sources')
    if jar.stat().st_mtime<max(p.stat().st_mtime for p in reports):raise ValueError('jar predates tests')
    with zipfile.ZipFile(jar) as archive:
        names=archive.namelist()
        if any('application-local.' in name or Path(name).name.startswith('.env') or name.endswith(('.db','.sqlite')) for name in names):
            raise ValueError('private configuration/database in candidate')
        config=archive.read('BOOT-INF/classes/application.yaml').decode('utf-8')
        if 'account-writes-enabled: false' not in config:raise ValueError('candidate write guard not default closed')
        frontend=list((ROOT/'frontend/dist').rglob('*'))
        if not (ROOT/'frontend/dist/index.html').exists():raise ValueError('frontend build missing')
        for file in frontend:
            if file.is_file() and archive.read('BOOT-INF/classes/static/'+file.relative_to(ROOT/'frontend/dist').as_posix())!=file.read_bytes():
                raise ValueError('embedded frontend differs from build')
    return totals


def package(jar,out,runbook,migration):
    totals=verify(jar)
    if out.exists():raise ValueError('review bundle path already exists; never overwrite a previous candidate')
    out.mkdir(parents=True)
    shutil.copy2(jar,out/'quanforge-candidate.jar')
    shutil.copy2(runbook,out/'RUNBOOK.md');shutil.copy2(migration,out/'prepare-schema.sql')
    sources=[p for p in (ROOT/'src').rglob('*.java')]+[ROOT/'pom.xml',ROOT/'src/main/resources/application.yaml']
    source_hashes={p.relative_to(ROOT).as_posix():sha(p) for p in sorted(sources)}
    manifest=dict(created_ms=int(time.time()*1000),status='CANDIDATE_ONLY_NOT_ADMITTED_FOR_DEMO',
        baseline_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        version='v4.8.7-audit-20261114',account_writes_default=False,observer_scheduling_enabled=False,
        tests=totals,files={p.name:sha(p) for p in sorted(out.iterdir()) if p.is_file()},
        source_hashes=source_hashes,source_tree_sha256=hashlib.sha256(json.dumps(source_hashes,sort_keys=True).encode()).hexdigest(),
        contents_verified=dict(no_application_local=True,no_databases=True,current_frontend_matches=True),
        no_credentials_included=True,production_not_modified=True)
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    archive=out.with_suffix('.zip')
    if archive.exists():raise ValueError('archive already exists')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as bundle:
        for file in sorted(out.iterdir()):bundle.write(file,file.name)
    return dict(bundle=str(archive.resolve()),bundle_sha256=sha(archive),candidate_sha256=sha(out/'quanforge-candidate.jar'),
                tests=totals,manifest_sha256=sha(out/'manifest.json'),status=manifest['status'])


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--jar',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--runbook',type=Path,required=True);parser.add_argument('--migration',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True);args=parser.parse_args()
    result=package(args.jar,args.out,args.runbook,args.migration)
    args.report.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result,indent=2))
