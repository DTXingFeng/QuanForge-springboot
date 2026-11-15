"""Reproduce all frozen research cases from the bundled public data, offline."""
import argparse
import gzip
import json
import shutil
import subprocess
import sys
from pathlib import Path
import crypto_edge_research as research
from analyze_crypto_edges import analyze


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--package',type=Path,default=Path(__file__).resolve().parents[1]/'docs/crypto-research-20261114')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();package=args.package;output=args.output
    hashes=json.loads((package/'artifact-hashes.json').read_text(encoding='utf-8'))
    for name in ('dataset.json.gz','results.json.gz','protocol.json','capture-manifest.json','accounting-analysis.json'):
        if research.sha(package/name)!=hashes[name]: raise ValueError('package changed: '+name)
    p=json.loads((package/'protocol.json').read_text(encoding='utf-8'))
    if p['source_sha256']!=research.sha(research.__file__): raise ValueError('registered engine changed')
    output.mkdir(parents=True,exist_ok=False)
    for name in ('protocol.json','capture-manifest.json'):
        shutil.copyfile(package/name,output/name)
    (output/'dataset.json').write_bytes(gzip.decompress((package/'dataset.json.gz').read_bytes()))
    subprocess.run([sys.executable,research.__file__,'replay','--directory',str(output)],check=True,timeout=60)
    expected=gzip.decompress((package/'results.json.gz').read_bytes())
    if (output/'results.json').read_bytes()!=expected: raise ValueError('replay result differs')
    checked=analyze(output)
    research.dump(output/'replication-check.json',dict(exact_results_byte_match=True,
        all_40_ledgers_reconcile=checked['all_40_ledgers_reconcile'],results_sha256=research.sha(output/'results.json')))
    print('PASS: offline replay, all 40 cases identical; independent ledgers reconcile')


if __name__=='__main__': main()
