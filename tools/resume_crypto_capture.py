"""One bounded recovery after the first public capture timed out.

Reconstructs identical requests from the registered protocol and retained replies.
The original research engine/protocol and all raw responses remain unchanged.
"""
import argparse
import json
from pathlib import Path
import crypto_edge_research as research


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--directory',type=Path,required=True)
    args=parser.parse_args();directory=args.directory
    p=json.loads((directory/'protocol.json').read_text(encoding='utf-8'))
    if research.sha(research.__file__)!=p['source_sha256']: raise ValueError('registered engine changed')
    retained=sorted(directory.glob('public-*.json'))
    research.dump(directory/'resume-registration.json',dict(reason='single read timeout at request 38',
        retained_successful_replies=len(retained),prior_failed_requests=1,max_total_network_attempts=96,
        resume_source_sha256=research.sha(__file__)))
    original=research.PublicCapture
    reconstructed=[]
    class ResumeCapture(original):
        def get(self,path,**params):
            request_index=self.calls+1;file=self.directory/f'public-{request_index:03}.json'
            if file.exists():
                if path not in research.ALLOWED: raise ValueError('allowlist')
                value=json.loads(file.read_text(encoding='utf-8'))
                if value.get('retCode')!=0: raise ValueError('cached response failed')
                self.calls+=1
                cached=True
                result=value['result']
            else:
                # Count the previous failed attempt in addition to completed requests.
                if self.calls+1>=96: raise ValueError('total attempt budget')
                result=super().get(path,**params);cached=False
            reconstructed.append(dict(index=request_index,path=path,params=params,
                from_retained_response=cached,sha256=research.sha(file)))
            return result
    research.PublicCapture=ResumeCapture
    research.capture(directory,p)
    research.dump(directory/'resume-manifest.json',dict(total_network_attempts=len(reconstructed)+1,
        prior_failed_requests=1,reconstructed_requests=reconstructed,
        retained_replies_were_not_refetched=True))


if __name__=='__main__': main()
