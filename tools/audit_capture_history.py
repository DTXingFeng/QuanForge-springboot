"""Bounded, public GET-only evidence capture. Never imports trading code or credentials.

python tools/audit_capture_history.py --snapshot PATH --max-requests 500
Writes new history.sqlite and capture-history.json inside the snapshot only.
"""
import argparse
import concurrent.futures
import datetime as dt
import json
import pathlib
import sqlite3
import urllib.parse
import urllib.request


def epoch(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    # Python paper ledgers explicitly use gmtime; numeric Java fields are epochs.
    return int(dt.datetime.fromisoformat(value).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--snapshot', type=pathlib.Path, required=True)
    ap.add_argument('--max-requests', type=int, default=500)
    ap.add_argument('--skip-requests', type=int, default=0)
    ap.add_argument('--output-stem', default='history')
    ap.add_argument('--sources', default='quanforge.db,paper_trendrule.db,paper_trendrule_tp5.db,paper_trendrule_tp5c.db,paper_v5mech.db')
    ap.add_argument('--proxy', default='http://127.0.0.1:7890')
    args = ap.parse_args()
    intervals = {}
    for name in args.sources.split(','):
        if pathlib.Path(name).name != name:
            raise SystemExit('sources must be snapshot database filenames')
        c = sqlite3.connect((args.snapshot / name).resolve().as_uri() + '?mode=ro', uri=True)
        for sym, en, end in c.execute("select symbol,entered_at,settled_at from ai_advice_track "
                                     "where entered_at is not null and settled_at is not null"):
            start, stop = epoch(en), epoch(end)
            if name == 'paper_v5mech.db':
                # Original script persisted signal/exit bar OPEN, not actual bar-close time.
                # Capture the complete exit hour plus one following hour; preserve source rows.
                stop += 2 * 3600000
            if stop < start:
                continue
            intervals.setdefault(sym, []).append((start // 60000 * 60000 - 30 * 60000,
                                                  (stop // 60000 + 1) * 60000))
        c.close()
    jobs = []
    for sym, spans in sorted(intervals.items()):
        merged = []
        for start, stop in sorted(spans):
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(stop, merged[-1][1])
            else:
                merged.append([start, stop])
        for start, stop in merged:
            for left in range(start, stop, 1000 * 60000):
                jobs.append((sym, left, min(stop, left + 1000 * 60000)))
    manifest = {'public_endpoint': 'https://api.bybit.com/v5/market/kline',
                'requested_jobs': len(jobs), 'budget': args.max_requests,
                'skip': args.skip_requests,
                'captured_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'requests': []}
    def fetch(job):
        sym, start, stop = job
        params = dict(category='linear', symbol=sym, interval=1, limit=1000, start=start, end=stop - 1)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler(
            {'https': args.proxy} if args.proxy else {}))
        info = {'symbol': sym, 'start': start, 'end': stop}
        try:
            with opener.open(manifest['public_endpoint'] + '?' + urllib.parse.urlencode(params), timeout=12) as r:
                data = json.load(r)
            info['retCode'] = data.get('retCode')
            rows = data.get('result', {}).get('list', [])
            info['rows'] = len(rows)
            return info, [(sym, int(x[0]), *(float(v) for v in x[1:7])) for x in rows
                          if start <= int(x[0]) < stop]
        except Exception as e:
            info['error'] = type(e).__name__
            return info, []
    if pathlib.Path(args.output_stem).name != args.output_stem:
        raise SystemExit('output-stem must be a filename stem')
    dest = args.snapshot / (args.output_stem + '.sqlite')
    # New evidence only. Refuse to overwrite an earlier capture.
    if dest.exists():
        raise SystemExit('capture already exists; use a new output-stem')
    c = sqlite3.connect(dest)
    c.execute('create table bars(symbol text, ts integer, open real, high real, low real, close real, '
              'volume real, turnover real, primary key(symbol,ts))')
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        selected = jobs[max(0, args.skip_requests):max(0, args.skip_requests) + max(0, args.max_requests)]
        for info, rows in pool.map(fetch, selected):
            manifest['requests'].append(info)
            c.executemany('insert or ignore into bars values(?,?,?,?,?,?,?,?)', rows)
            c.commit()
    manifest['stored_bars'] = c.execute('select count(*) from bars').fetchone()[0]
    c.close()
    (args.snapshot / ('capture-' + args.output_stem + '.json')).write_text(json.dumps(manifest, indent=2))
    print(json.dumps({k: v for k, v in manifest.items() if k != 'requests'}, indent=2))


if __name__ == '__main__':
    main()
