#!/usr/bin/env python3
"""v5趋势触发研究: 15m/1h EMA排列翻转事件的密度/质量/持续性
事件定义: ema20/ema60/ema200 三线全多=UP, 全空=DOWN, 其余=MIXED
          MIXED->UP / MIXED->DOWN 的翻转 = 候选触发事件
质量口径: 事件后 4/12/24/48h 前瞻收益(顺事件方向) vs 无条件基线
"""
import json, time, urllib.request, collections
import pandas as pd

PROXY = {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}
op_px = urllib.request.build_opener(urllib.request.ProxyHandler(PROXY))
op_dir = urllib.request.build_opener(urllib.request.ProxyHandler({}))
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ACEUSDT", "ZECUSDT", "SNDKUSDT"]

def fetch_klines(sym, interval, days):
    """分页拉K线, 返回旧->新 DataFrame"""
    got, end_ms = [], int(time.time() * 1000)
    deadline = end_ms - days * 86400_000
    for _ in range(12):
        url = (f"https://api.bybit.com/v5/market/kline?category=linear&symbol={sym}"
               f"&interval={interval}&limit=1000&end={end_ms}")
        d = None
        for op in (op_dir, op_px):
            try:
                d = json.load(op.open(url, timeout=20))
                break
            except Exception:
                continue
        if not d or not d.get("result", {}).get("list"):
            break
        rows = d["result"]["list"]
        got.extend(rows)
        oldest = int(rows[-1][0])
        if oldest <= deadline or len(rows) < 1000:
            break
        end_ms = oldest - 1
    df = pd.DataFrame(got, columns=["ts", "o", "h", "l", "c", "v", "turnover"])
    df["ts"] = df["ts"].astype("int64")
    df = df.drop_duplicates("ts").sort_values("ts")
    for col in ("o", "h", "l", "c"):
        df[col] = df[col].astype(float)
    return df.reset_index(drop=True)

def regime_events(df):
    """返回 [(idx, ts, 'UP'/'DOWN', price)], 以及state序列"""
    c = df["c"]
    e20 = c.ewm(span=20, adjust=False).mean()
    e60 = c.ewm(span=60, adjust=False).mean()
    e200 = c.ewm(span=200, adjust=False).mean()
    state = []
    for i in range(len(df)):
        if e20.iloc[i] > e60.iloc[i] > e200.iloc[i]:
            state.append("UP")
        elif e20.iloc[i] < e60.iloc[i] < e200.iloc[i]:
            state.append("DOWN")
        else:
            state.append("MIXED")
    events = []
    for i in range(1, len(state)):
        if state[i] in ("UP", "DOWN") and state[i - 1] != state[i]:
            events.append((i, int(df["ts"].iloc[i]), state[i], float(c.iloc[i])))
    return events, state

def fwd(df, i, direction, hours, tf_h):
    j = i + int(hours / tf_h)
    if j >= len(df):
        return None
    r = (df["c"].iloc[j] / df["c"].iloc[i] - 1) * 100
    return r if direction == "UP" else -r

print(f"{'='*72}")
print(f"1h 级别研究 (~180天): 事件密度 / 前瞻收益 / 趋势持续性")
print(f"{'='*72}")
all_ev = []
cache = {}
for sym in SYMBOLS:
    df = fetch_klines(sym, "60", 180)
    cache[sym] = df
    if len(df) < 250:
        print(f"{sym}: 数据不足({len(df)}根), 跳过")
        continue
    events, state = regime_events(df)
    days_span = (df['ts'].iloc[-1] - df['ts'].iloc[0]) / 86400000
    # 持续性: 每个UP/DOWN段持续多少根
    segs, cur, n = [], state[0], 1
    for s in state[1:]:
        if s == cur:
            n += 1
        else:
            if cur != "MIXED":
                segs.append(n)
            cur, n = s, 1
    med_seg = sorted(segs)[len(segs)//2] * 1 if segs else 0
    # 前瞻收益
    stats = collections.defaultdict(list)
    for i, ts, d, p in events:
        for h in (4, 12, 24, 48):
            v = fwd(df, i, d, h, 1.0)
            if v is not None:
                stats[h].append(v)
    line = f"{sym:9s} {days_span:5.0f}天 n={len(df):5d}根 | 事件{len(events):3d}个"
    line += f"({len(events)/days_span*7:.1f}/周) | 段中位{med_seg:.0f}h | "
    for h in (4, 12, 24, 48):
        xs = stats[h]
        if xs:
            wr = 100 * sum(1 for x in xs if x > 0) / len(xs)
            line += f"{h}h:{sum(xs)/len(xs):+.2f}%/{wr:.0f}% "
    print(line)
    for e in events:
        all_ev.append((sym,) + e)

# 基线对比: 同币种随机时点(3x事件数)的无条件前瞻收益
print(f"\n事件后收益 vs 无条件基线(逐币随机时点, n=3x事件):")
base_stats = collections.defaultdict(lambda: collections.defaultdict(list))
ev_stats = collections.defaultdict(lambda: collections.defaultdict(list))
import random
random.seed(7)
for sym in SYMBOLS:
    df = cache.get(sym)
    if df is None or len(df) < 250:
        continue
    events, _ = regime_events(df)
    nb = min(len(events) * 3, 300)
    idxs = random.sample(range(200, len(df) - 50), nb) if nb else []
    for h in (4, 12, 24, 48):
        for k in idxs:
            j = k + h
            if j < len(df):
                base_stats[sym][h].append((df["c"].iloc[j] / df["c"].iloc[k] - 1) * 100)
        for i, ts, d, p in events:
            v = fwd(df, i, d, h, 1.0)
            if v is not None:
                ev_stats[sym][h].append(v)
for h in (4, 12, 24, 48):
    eb = [x for sym in SYMBOLS for x in base_stats[sym].get(h, [])]
    ee = [x for sym in SYMBOLS for x in ev_stats[sym].get(h, [])]
    if eb and ee:
        print(f"  {h:2d}h: 事件后 均值{sum(ee)/len(ee):+.2f}% WR{100*sum(1 for x in ee if x>0)/len(ee):.0f}% (n={len(ee)})"
              f" | 基线 均值{sum(eb)/len(eb):+.2f}% (n={len(eb)}) | 增量{sum(ee)/len(ee)-sum(eb)/len(eb):+.2f}pp")

# 15m密度抽查(近10天)
print(f"\n{'='*72}")
print("15m 级别密度抽查(近10天):")
for sym in SYMBOLS:
    df = fetch_klines(sym, "15", 10)
    if len(df) < 250:
        continue
    events, _ = regime_events(df)
    days_span = (df['ts'].iloc[-1] - df['ts'].iloc[0]) / 86400000
    stats = collections.defaultdict(list)
    for i, ts, d, p in events:
        for h in (1, 4):
            v = fwd(df, i, d, h, 0.25)
            if v is not None:
                stats[h].append(v)
    line = f"{sym:9s} 事件{len(events):3d}个({len(events)/days_span:.1f}/天) | "
    for h in (1, 4):
        xs = stats[h]
        if xs:
            line += f"{h}h:{sum(xs)/len(xs):+.2f}%/{100*sum(1 for x in xs if x>0)/len(xs):.0f}% "
    print(line)
