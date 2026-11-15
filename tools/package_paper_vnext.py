"""Package verified PAPER artifacts without credentials or historical databases."""
import hashlib,json,shutil,subprocess,sys,time,zipfile
from pathlib import Path
from package_candidate import verify

ROOT=Path(__file__).resolve().parents[1]
def main():
    jar=ROOT/'target/QuanForge-springboot-0.0.1-SNAPSHOT.jar';tests=verify(jar)
    release=ROOT/'.audit-private/paper-vnext-20261115/release';release.mkdir(exist_ok=False)
    shutil.copyfile(jar,release/'app.jar');(release/'tools').mkdir()
    files=['paper_vnext_carry_worker.py','paper_vnext_carry.py','paper_vnext_market.py',
           'paper_vnext_strategy.py','paper_vnext_ledger.py','paper_vnext_worker.py']
    for name in files:(release/'tools'/name).write_bytes((ROOT/'tools'/name).read_bytes().replace(b'\r\n',b'\n'))
    for name in ['research-summary.json','carry-evidence.json']:shutil.copyfile(ROOT/'docs/paper-vnext-20261115'/name,release/name)
    hashes={f.relative_to(release).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in release.rglob('*') if f.is_file()}
    manifest=dict(version='v5.1-paperlab-20261115',created_ms=int(time.time()*1000),java_tests=tests,python_tests=92,
        account_writes=False,scheduling=False,paper_only=True,forward_profitability_passed=False,
        git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),files=hashes)
    (release/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    archive=release.with_suffix('.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for f in release.rglob('*'):
            if f.is_file():z.write(f,f.relative_to(release).as_posix())
    shutil.copyfile(release/'manifest.json',ROOT/'docs/paper-vnext-20261115/artifact-manifest.json')
    print(json.dumps(dict(bundle=str(archive),sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),java_tests=tests)))
if __name__=='__main__':main()
