"""Complete only the fully captured BTC subset, without any network retries.

The original 48-case BTC/ETH capture remains FAILED/incomplete. This supplement
adds the user's 20-USDT budget before examining results; no return-based filter.
"""
import argparse
import hashlib
import json
import urllib.parse
from pathlib import Path
import research_conditional_carry as study
import crypto_edge_research as prior


class CachedOnly(study.Capture):
    def get(self,path,**params):
        url='https://api.bybit.com'+path+'?'+urllib.parse.urlencode(sorted(params.items()))
        key=hashlib.sha256(url.encode()).hexdigest()
        if key not in self.cached: raise ValueError('offline subset: missing cached response')
        record=self.cached[key];file=self.directory/record['file']
        if prior.sha(file)!=record['sha256']: raise ValueError('cached reply changed')
        return json.loads(file.read_text(encoding='utf-8'))['result']


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    p=json.loads((args.source/'protocol.json').read_text(encoding='utf-8'))
    if p['source_hashes']!=study.source_hashes(): raise ValueError('registered sources changed')
    args.output.mkdir(parents=True,exist_ok=False)
    p.update(symbols=['BTCUSDT'],capitals=['20','200','2000'],cases=36,
        label='EXPLORATORY_BTC_ONLY_DATA_AVAILABILITY_SUBSET',
        exclusion='ETH historical page reached two timeout attempts before evaluation; no result-based exclusion',
        capital_supplement='20 USDT added per user preference before reading replay results',
        subset_source_sha256=prior.sha(__file__))
    prior.dump(args.output/'protocol.json',p)
    reader=CachedOnly(args.source)
    data={'BTCUSDT':{category:reader.bars('BTCUSDT',category,p['start'],p['end_exclusive']) for category in ('spot','linear')}}
    prior.dump(args.output/'hourly-data.json',data)
    prior.dump(args.output/'capture-manifest.json',dict(hourly_data_sha256=prior.sha(args.output/'hourly-data.json'),
        extra_network_attempts=0,source_request_log_sha256=prior.sha(args.source/'requests.jsonl')))
    study.evaluate(args.output,p)


if __name__=='__main__': main()
