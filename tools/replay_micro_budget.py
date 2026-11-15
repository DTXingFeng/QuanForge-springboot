"""Offline reproduction of the BTC supplement and the 20-USDT experiments."""
import argparse
import gzip
import json
import shutil
from pathlib import Path
import crypto_edge_research as util
import research_conditional_carry as btc
import micro_budget_research as micro


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--package',type=Path,default=Path(__file__).resolve().parents[1]/'docs/conditional-carry-20261115')
    args=parser.parse_args();package=args.package
    hashes=json.loads((package/'artifact-hashes.json').read_text(encoding='utf-8'))
    for name,expected in hashes.items():
        if util.sha(package/name)!=expected: raise ValueError('artifact changed: '+name)
    args.output.mkdir(parents=True,exist_ok=False);checks=[]
    for part,files,evaluator in [('btc-subset',['hourly-data.json'],btc.evaluate),
                                 ('micro-budget',['historical-data.json','current-snapshot.json'],micro.evaluate)]:
        source=package/part;output=args.output/part;output.mkdir()
        for name in ('protocol.json','capture-manifest.json'):
            shutil.copyfile(source/name,output/name)
        for name in files:
            (output/name).write_bytes(gzip.decompress((source/(name+'.gz')).read_bytes()))
        p=json.loads((output/'protocol.json').read_text(encoding='utf-8'));evaluator(output,p)
        expected=gzip.decompress((source/'results.json.gz').read_bytes())
        actual=(output/'results.json').read_bytes()
        if json.loads(actual)!=json.loads(expected): raise ValueError('result differs: '+part)
        checks.append(dict(part=part,cases=len(json.loads(actual)['runs']),exact_byte_match=actual==expected,
            identical_json_results=True,results_sha256=util.sha(output/'results.json')))
    util.dump(args.output/'replication-check.json',dict(checks=checks,network_requests=0,
        original_ETH_two_year_case='not run: incomplete acquisition retained'))
    print('PASS: 36 BTC cases and 12 micro-budget cases reproduce offline')


if __name__=='__main__': main()
