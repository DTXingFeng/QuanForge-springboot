#!/usr/bin/env python3
"""上新扫描器: 从 Bybit 合约榜发现候选热山寨 (人工确认后进观察列表)
筛选: 24h成交额>=5亿$ 流动性 + 非主流/稳定币 + 近24h波动够猛
输出: TOP15 + 现任观察列表成员状态对照. 手动运行, 不自动改观察列表"""
import json, urllib.request

PROXY = {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}
op = urllib.request.build_opener(urllib.request.ProxyHandler(PROXY))
op_direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))

EXCLUDE = {"BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT",
           "ADAUSDT", "AVAXUSDT", "LINKUSDT", "TRXUSDT", "LTCUSDT", "DOTUSDT",
           "USDCUSDT", "USDEUSDT", "DAIUSDT", "FDUSDUSDT", "SUSDEUSDT", "PYUSDUSDT"}
CURRENT = {"ACEUSDT", "ZECUSDT", "SNDKUSDT"}
KNOWN_DEAD = {"HEMIUSDT", "HYPEUSDT", "CYSUSDT", "BEATUSDT"}
MIN_TURNOVER = 500_000_000   # 24h 成交额下限 5亿U

def get(url):
    for o in (op_direct, op):
        try:
            return json.load(o.open(url, timeout=15))
        except Exception:
            continue
    raise RuntimeError("fetch fail " + url)

d = get("https://api.bybit.com/v5/market/tickers?category=linear")
rows = []
for t in d["result"]["list"]:
    sym = t["symbol"]
    if not sym.endswith("USDT") or sym in EXCLUDE:
        continue
    to = float(t.get("turnover24h", 0) or 0)
    if to < MIN_TURNOVER:
        continue
    pct = float(t.get("price24hPcnt", 0) or 0) * 100
    rows.append((sym, to / 1e6, pct))
rows.sort(key=lambda r: -r[1])

def tag(sym):
    if sym in CURRENT: return "★现任"
    if sym in KNOWN_DEAD: return "×曾死"
    return "新面孔"

print(f"{'币种':<12}{'24h额($M)':>10}{'24h涨跌':>9}  身份")
for sym, to, pct in rows[:15]:
    print(f"{sym:<12}{to:>10.0f}{pct:>+8.2f}%  {tag(sym)}")

cur = [r for r in rows if r[0] in CURRENT]
print("\n现任观察列表状态:")
for sym, to, pct in cur:
    print(f"  {sym}: 24h额 {to:.0f}M  {pct:+.2f}%")
missing = CURRENT - {r[0] for r in rows}
if missing:
    print(f"  ⚠ 低于门槛额: {missing} (候选沉默中, 门槛机制生效的旁证)")
