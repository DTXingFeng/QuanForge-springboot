#!/usr/bin/env python3
"""
QuanForge 回测引擎：让 v4.x 体系在历史数据上快速"活一遍"。

重放一个月 = 逐分钟遍历 kline_1m：
  - 触发器确定性复现（WS 急动 1m/5m + 定时扫描 15m/RSI）
  - 触发时刻调用真实 LLM（单轮预取上下文，含历史时点的模型预测）
  - 规则层完整复现：单仓、熔断、山寨趋势纪律、majors 止损钳制、
    同根K线保守判损、TTL、保本移动、REBASE 确定性近似
  - 账本写入 backtest.db（ai_advice_track 兼容口径），sys_version 带 arm 标签

A/B 臂位（--arm）：
  full      完整 v4.7 规则（默认）
  nobreaker 关掉熔断（测熔断值多少钱）
  notrend   关掉山寨趋势纪律
  norebase  关掉 REBASE
用法：
  python3 backtest.py --days 30 --symbols BTCUSDT,ETHUSDT,SOLUSDT,ACEUSDT,ZECUSDT,SNDKUSDT --arm full
"""
import argparse, json, os, sqlite3, sys, time, urllib.request
from collections import deque

import joblib
import numpy as np
import pandas as pd

PROD_DB = "/mnt/nvme/quanforge/data/quanforge.db"
OUT_DB = "/mnt/nvme/quanforge/data/backtest.db"
LLM_BASE = "https://ai.stackpotato.com/v1"
LLM_MODEL = "gemini-3.7-flash-high"
LLM_KEY_FILE = "/mnt/nvme/quanforge/tools/.backtest_llm_key"
PROXY = {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}
MAJORS = {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
EQUITY0 = 200.0
NOTIONAL = 1000.0  # 5% x 100x x $200

# ---------------- 触发/规则参数（与生产一致） ----------------
SHOCK_1M, IMPULSE_5M, COOLDOWN_S = 0.35, 0.80, 300
SCAN_PCT15M, SCAN_RSI_X = 0.5, 25.0
BREAKER_2H = 1.2
CLAMP_MAJORS = 2.2
TTL_ALTS, TTL_MAJORS = 120, 240
SLIP_MARKET, SLIP_LIMIT = 0.0005, 0.0003
# 执行延迟模式（--latency）：
#   -1  = 自适应（推荐）：每次 LLM 调用实测耗时即该单成交等待——模型快则延迟小，
#         慢则延迟大，延迟分布自动对齐生产（llm_ms 记录在账本）
#   N>0 = 固定 N 秒
#   0   = 零延迟理想模式
EXEC_LATENCY_S = 0

opener = urllib.request.build_opener(urllib.request.ProxyHandler(PROXY))

# ---------------- 模型（与 model_server.py 逐字一致） ----------------
def rsi(s, period=14):
    d = s.diff()
    g = d.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
    return (100 - 100/(1 + g/l.replace(0, np.nan))).fillna(50)

def atr(df, period=14):
    pc = df["close"].shift()
    tr = pd.concat([df["high"]-df["low"], (df["high"]-pc).abs(),
                    (df["low"]-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()

def build(df):
    f = pd.DataFrame(index=df.index)
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    for w in (5, 15, 30, 60, 120):
        f[f"ret_{w}"] = c.pct_change(w)
    f["atr14"] = atr(df, 14) / c
    f["range_30"] = (c.rolling(30).max() - c.rolling(30).min()) / c
    mid, sd = c.rolling(20).mean(), c.rolling(20).std()
    f["boll_pos"] = (c - mid) / (2 * sd.replace(0, np.nan))
    f["rsi14"] = rsi(c)
    f["vol_ratio"] = v / (v.rolling(60).mean() + 1e-12)
    f["body_ratio"] = (c - df["open"]).abs() / (h - l + 1e-12)
    f["up_wick"] = (h - pd.concat([c, df["open"]], axis=1).max(axis=1)) / (h - l + 1e-12)
    f["hour_sin"] = np.sin(2*np.pi*df.index.hour/24)
    f["hour_cos"] = np.cos(2*np.pi*df.index.hour/24)
    return f

BUNDLES = {"majors": joblib.load("/mnt/nvme/quanforge/model_majors.joblib"),
           "alts": joblib.load("/mnt/nvme/quanforge/model_alts.joblib")}

def model_predict(symbol, df300):
    domain = "majors" if symbol in MAJORS else "alts"
    b = BUNDLES[domain]
    feats = build(df300).iloc[[-1]][b["features"]]
    if feats.isna().any(axis=1).iloc[0]:
        return None
    p = float(b["model"].predict_proba(feats)[0, 1])
    conf = abs(p - 0.5) * 2
    cal = b["calibration"]
    if conf >= cal["high_threshold"]:
        zone, acc = "high", cal["high_acc"]
    elif conf >= cal["mid_threshold"]:
        zone, acc = "mid", cal["mid_acc"]
    else:
        zone, acc = "low", cal["low_acc"]
    return {"probUp": round(p, 4), "direction": "UP" if p >= 0.5 else "DOWN",
            "confidence": round(conf, 4), "zone": zone, "expectedAcc": acc,
            "domain": domain, "inDomain": symbol in (MAJORS | set(b.get("symbols", [])))}

# ---------------- LLM ----------------
def load_key():
    if os.path.exists(LLM_KEY_FILE):
        return open(LLM_KEY_FILE).read().strip()
    raise RuntimeError(f"缺少 LLM key 文件 {LLM_KEY_FILE}（写入 sk-... 一行）")

LLM_KEY = None
def llm_judge(ctx_user):
    global LLM_KEY
    if LLM_KEY is None:
        LLM_KEY = load_key()
    body = {"model": LLM_MODEL, "temperature": 0.2, "messages": [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": ctx_user}]}
    req = urllib.request.Request(
        LLM_BASE + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + LLM_KEY,
                 "Content-Type": "application/json"})
    with opener.open(req, timeout=90) as r:
        d = json.load(r)
    txt = d["choices"][0]["message"]["content"].strip()
    a, b = txt.find("{"), txt.rfind("}")
    return json.loads(txt[a:b+1]) if a >= 0 else {}

SYSTEM_PROMPT = """你是专业的加密货币合约交易风控分析师（超短线，用户惯用 100 倍杠杆）。
哲学：损失可控优先于高确定性——方向倾向成立即可出手，空仓错过也是成本，但每单必带结构止损。
规则：
- 三项检查缺一不可：参考统计模型方向；无持仓矛盾；杠杆=品种上限截断。
- 模型交叉验证：模型与你一致→写明共振，confidence+5~10；分歧→倾向 HOLD 并说明；zone=low 忽略模型。
- 山寨币趋势纪律（非 BTC/ETH/SOL）：只顺 15m/1h 主趋势方向交易，趋势不明输出 HOLD，禁逆势抄底摸顶。
- 止损放结构失效位外（近期高低点/布林另一侧/1~1.5×ATR）；止盈≥0.1% 覆盖手续费，给最近第一目标位。
- 账户风险：实际杠杆×5%保证金×止损距离% ≤ 1%。
- 单边行情注意：2h 动量超 ±1.2% 时逆势单会被系统熔断，别浪费建议。
只输出一个 JSON：{"alertLevel":"INFO|WARN|CRITICAL|NONE","action":"BUY|SELL|HOLD",
"entry":数字或null,"stopLoss":数字或null,"takeProfit":数字或null,
"title":"≤20字","summary":"≤60字","detail":"≤120字：趋势/结构/模型结论","confidence":0-100}"""

# ---------------- 数据加载 ----------------
def load_klines(symbols, days, seg_offset=0):
    con = sqlite3.connect(PROD_DB)
    end_ms = int((time.time() - seg_offset * 86400) * 1000)
    start_ms = end_ms - days * 86400 * 1000
    frames = {}
    for s in symbols:
        df = pd.read_sql_query(
            f"select open_time, open, high, low, close, volume from kline_1m "
            f"where symbol='{s}' and open_time >= {start_ms} and open_time < {end_ms} "
            f"order by open_time", con)
        if len(df) < 2000:
            print(f"[skip] {s} 数据不足({len(df)})")
            continue
        df.index = pd.to_datetime(df["open_time"], unit="ms")
        frames[s] = df[["open", "high", "low", "close", "volume"]]
    con.close()
    return frames

# ---------------- 主循环 ----------------
class Pos:
    __slots__ = ("sym", "action", "entry", "sl", "tp", "ts", "plan_ts",
                 "rebased", "breakeven", "is_market", "wait_s", "llm_ms")

def run(symbols, days, arm, budget, out_db, latency_s=0, seg_offset=0):
    frames = load_klines(symbols, days, seg_offset)
    symbols = list(frames)
    print(f"[backtest] {len(symbols)} symbols, {days}d, arm={arm}, data ok")
    master_idx = sorted(set().union(*[set(f.index) for f in frames.values()]))
    print(f"[backtest] master timeline {len(master_idx)} minutes "
          f"({master_idx[0]} ~ {master_idx[-1]})")

    out = sqlite3.connect(out_db)
    arm_label = f"{arm}" + (f"-lat{latency_s}" if latency_s else "")
    out.execute("""create table if not exists ai_advice_track(
        id integer primary key autoincrement, symbol text, action text,
        entry real, stop_loss real, take_profit real, status text,
        result_pct real, note text, sys_version text,
        created_at text, entered_at text, settled_at text, llm_ms integer)""")
    # 兼容旧库（无 llm_ms 列）——动态补列
    cols = [r[1] for r in out.execute("pragma table_info(ai_advice_track)")]
    if "llm_ms" not in cols:
        out.execute("alter table ai_advice_track add column llm_ms integer")

    pos = {}          # symbol -> Pos (单仓)
    pending = {}      # symbol -> Pos (限价等成交)
    delay_queue = {}  # symbol -> Pos (延迟成交计划)
    last_trig = {}    # symbol -> ts
    losses_90 = {}    # symbol|dir -> [ts,...]
    llm_calls = 0
    equity = EQUITY0
    wins = losses_n = 0
    last_llm_ms = [0]  # 最近一次 LLM 调用耗时（自适应延迟臂用）

    def settle(p, status, pct, ts, note=""):
        nonlocal equity, wins, losses_n
        out.execute("insert into ai_advice_track(symbol,action,entry,stop_loss,take_profit,"
                    "status,result_pct,note,sys_version,created_at,entered_at,settled_at,llm_ms) "
                    "values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (p.sym, p.action, p.entry, p.sl, p.tp, status, round(pct, 3), note,
                     f"backtest-v4.7-{arm_label}", str(p.plan_ts), str(p.ts), str(ts),
                     p.llm_ms))
        if status in ("WIN", "LOSS"):
            equity += NOTIONAL * pct / 100
            wins += status == "WIN"
            losses_n += status == "LOSS"
        out.commit()

    def breaker_blocks(sym, action, df, i):
        if arm == "nobreaker":
            return None
        c = df["close"]
        if i >= 120:
            m2h = (c.iloc[i] / c.iloc[i-120] - 1) * 100
            if (m2h >= BREAKER_2H and action == "SELL") or \
               (m2h <= -BREAKER_2H and action == "BUY"):
                return f"breaker:2h {m2h:+.2f}%"
        key = sym + "|" + action
        recent = [t for t in losses_90.get(key, []) if (i_ts.value - t) / 1e9 <= 5400]
        if len(recent) >= 2:
            return "breaker:2连亏冷却"
        return None

    for i_ts in master_idx:
        for sym, df in frames.items():
            if i_ts not in df.index:
                continue
            i = df.index.get_loc(i_ts)
            if i < 300:
                continue
            bar = df.iloc[i]
            c = df["close"]

            # ---- 持仓管理 ----
            p = pos.get(sym)
            if p is not None:
                buy = p.action == "BUY"
                age = (i_ts.value - p.ts.value) / 6e10
                hit_sl = bar["low"] <= p.sl if buy else bar["high"] >= p.sl
                hit_tp = bar["high"] >= p.tp if buy else bar["low"] <= p.tp
                if hit_sl and hit_tp:
                    pct = -(abs(p.entry - p.sl) / p.entry * 100)
                    settle(p, "LOSS", pct, i_ts, "同根双触发保守判损"); pos.pop(sym)
                elif hit_sl:
                    pct = -(abs(p.entry - p.sl) / p.entry * 100)
                    key = sym + "|" + p.action
                    losses_90.setdefault(key, []).append(i_ts.value)
                    settle(p, "LOSS", pct, i_ts); pos.pop(sym)
                elif hit_tp:
                    pct = abs(p.tp - p.entry) / p.entry * 100
                    settle(p, "WIN", pct, i_ts); pos.pop(sym)
                else:
                    last = bar["close"]
                    prog = ((last - p.entry) if buy else (p.entry - last)) \
                        / (p.tp - p.entry)
                    # 保本移动：浮盈过半
                    if not p.breakeven and prog >= 0.5:
                        p.sl = p.entry
                        p.breakeven = True
                    # REBASE 近似（majors，一次）：浮亏 0.1~0.5% + 动能收敛 + 24h 区间内
                    if (arm != "norebase" and sym in MAJORS and not p.rebased
                            and p.breakeven is False):
                        fl = (p.entry - last) / p.entry * 100 if buy else (last - p.entry) / p.entry * 100
                        m15 = (c.iloc[i] / c.iloc[i-15] - 1) * 100
                        if i >= 1440:
                            hi24, lo24 = c.iloc[i-1440:i].max(), c.iloc[i-1440:i].min()
                            inside = lo24 * 1.001 < last < hi24 * 0.999
                            if 0.1 <= fl <= 0.5 and abs(m15) < 0.3 and inside:
                                edge = lo24 * 0.999 if buy else hi24 * 1.001
                                risk = (abs(last - edge) / last * 100 + fl) * 100 * 5 / 100
                                if risk <= 2.0:
                                    p.sl = edge
                                    p.rebased = True
                    ttl = TTL_MAJORS if sym in MAJORS else TTL_ALTS
                    if age > ttl:
                        pct = ((last - p.entry) if buy else (p.entry - last)) / p.entry * 100
                        settle(p, "WIN" if pct >= 0 else "LOSS", pct, i_ts, "TTL平仓")
                        pos.pop(sym)
                continue

            # ---- 延迟成交计划队列 ----
            # EXEC_LATENCY_S>0 时：LLM 判完的单进 delay_queue，等延迟窗口过后
            # 的第一个 bar 以该 bar 开盘价（市价近似）成交；价格已越过止损则放弃。
            dq = delay_queue.get(sym)
            if dq is not None:
                if (i_ts.value - dq.plan_ts.value) / 1e9 >= dq.wait_s:
                    entry_now = bar["open"]
                    buy_d = dq.action == "BUY"
                    invalid = entry_now <= dq.sl if buy_d else entry_now >= dq.tp
                    beyond_sl = entry_now <= dq.sl if buy_d else entry_now >= dq.sl
                    if beyond_sl:
                        out.execute("insert into ai_advice_track(symbol,action,entry,stop_loss,"
                                    "take_profit,status,result_pct,note,sys_version,created_at) "
                                    "values(?,?,?,?,?,?,?,?,?,?)",
                                    (sym, dq.action, dq.entry, dq.sl, dq.tp, "EXPIRED", None,
                                     f"延迟{int(dq.wait_s)}s价格已穿止损，弃单",
                                     f"backtest-v4.7-{arm_label}", str(dq.plan_ts)))
                        out.commit()
                    elif invalid:
                        out.execute("insert into ai_advice_track(symbol,action,entry,stop_loss,"
                                    "take_profit,status,result_pct,note,sys_version,created_at) "
                                    "values(?,?,?,?,?,?,?,?,?,?)",
                                    (sym, dq.action, dq.entry, dq.sl, dq.tp, "EXPIRED", None,
                                     "延迟后价格已越过入场逻辑位，弃单",
                                     f"backtest-v4.7-{arm_label}", str(dq.plan_ts)))
                        out.commit()
                    else:
                        dq.entry = entry_now * (1 + (SLIP_MARKET if buy_d else -SLIP_MARKET))
                        dq.ts = i_ts
                        pos[sym] = dq
                    delay_queue.pop(sym)
                continue

            # ---- 限价单成交检查 ----
            q = pending.get(sym)
            if q is not None:
                buy = q.action == "BUY"
                touched = bar["high"] >= q.entry if buy else bar["low"] <= q.entry
                age = (i_ts.value - q.ts.value) / 6e10
                if touched:
                    q.entry = q.entry * (1 + (SLIP_LIMIT if buy else -SLIP_LIMIT))
                    q.ts = i_ts
                    pos[sym] = q
                    pending.pop(sym)
                elif age > 120:
                    out.execute("insert into ai_advice_track(symbol,action,entry,stop_loss,"
                                "take_profit,status,result_pct,note,sys_version,created_at) "
                                "values(?,?,?,?,?,?,?,?,?,?)",
                                (sym, q.action, q.entry, q.sl, q.tp, "EXPIRED", None,
                                 "等入场超时", f"backtest-v4.7-{arm_label}", str(q.ts)))
                    out.commit(); pending.pop(sym)
                continue

            # ---- 触发检测（bar 收盘后） ----
            if i < 6 or (i_ts.value - last_trig.get(sym, 0)) / 1e9 < COOLDOWN_S:
                continue
            pct1m = (c.iloc[i] / c.iloc[i-1] - 1) * 100
            pct5m = (c.iloc[i] / c.iloc[i-5] - 1) * 100
            pct15m = (c.iloc[i] / c.iloc[i-15] - 1) * 100
            r = float(rsi(c).iloc[i])
            why = None
            if abs(pct1m) >= SHOCK_1M:
                why = f"实时急动 1m {pct1m:+.2f}%"
            elif abs(pct5m) >= IMPULSE_5M:
                why = f"实时冲量 5m {pct5m:+.2f}%"
            elif i_ts.minute % 30 == 0 and (abs(pct15m) >= SCAN_PCT15M or r <= SCAN_RSI_X or r >= 100 - SCAN_RSI_X):
                why = f"定时扫描 15m {pct15m:+.2f}% RSI {r:.0f}"
            if why is None or llm_calls >= budget:
                continue

            # ---- 上下文（历史时点） ----
            df300 = df.iloc[i-299:i+1]
            mp = model_predict(sym, df300)
            if mp is None:
                continue

            # ---- L0 级联快通道（--arm cascade-l0）----
            # 模型 zone=high 时跳过 LLM 直接规则化下单（零延迟）：
            # 方向=模型方向；入场=现价（市价即时）；止损=1.2×ATR；止盈=2R。
            # 规则层（熔断/趋势纪律/钳制）照常执行。其余场景走 LLM 慢通道。
            if arm == "cascade-l0" and mp["zone"] == "high" and mp["inDomain"]:
                l0_dir = "BUY" if mp["direction"] == "UP" else "SELL"
                l0_blk = breaker_blocks(sym, l0_dir, df, i)
                ema20_l0 = c.iloc[max(0,i-200):i+1].ewm(span=20).mean().iloc[-1]
                ema60_l0 = c.iloc[max(0,i-200):i+1].ewm(span=60).mean().iloc[-1]
                trend15_l0 = "UP" if ema20_l0 > ema60_l0 else "DOWN"
                trend_ok = True
                if sym not in MAJORS and (
                        (l0_dir == "BUY" and trend15_l0 == "DOWN")
                        or (l0_dir == "SELL" and trend15_l0 == "UP")):
                    trend_ok = False
                if l0_blk is not None or not trend_ok:
                    out.execute("insert into ai_advice_track(symbol,action,entry,stop_loss,"
                                "take_profit,status,result_pct,note,sys_version,created_at) "
                                "values(?,?,?,?,?,?,?,?,?,?)",
                                (sym, l0_dir, c.iloc[i], 0, 0, "BLOCKED", None,
                                 f"L0被拦:{l0_blk or '趋势纪律'}",
                                 f"backtest-v4.7-{arm_label}", str(i_ts)))
                    out.commit()
                    last_trig[sym] = i_ts.value
                    continue
                px = c.iloc[i]
                atr_l0 = float(atr(df, 14).iloc[i])
                sl_d = atr_l0 * 1.2
                l0_sl = px - sl_d if l0_dir == "BUY" else px + sl_d
                l0_tp = px + 2 * sl_d if l0_dir == "BUY" else px - 2 * sl_d
                if sym in MAJORS and abs(px - l0_sl) / px * 100 > CLAMP_MAJORS:
                    l0_sl = px - px * CLAMP_MAJORS / 100 if l0_dir == "BUY" \
                        else px + px * CLAMP_MAJORS / 100
                q0 = Pos(); q0.sym, q0.action, q0.entry = sym, l0_dir, px
                q0.sl, q0.tp, q0.ts, q0.plan_ts = l0_sl, l0_tp, i_ts, i_ts
                q0.rebased, q0.breakeven, q0.is_market = False, False, True
                q0.wait_s, q0.llm_ms = 0, 1  # LightGBM 推理 ~1ms
                q0.entry = px * (1 + (SLIP_MARKET if l0_dir == "BUY" else -SLIP_MARKET))
                pos[sym] = q0
                out.execute("insert into ai_advice_track(symbol,action,entry,stop_loss,"
                            "take_profit,status,result_pct,note,sys_version,created_at,llm_ms) "
                            "values(?,?,?,?,?,?,?,?,?,?,?)",
                            (sym, l0_dir, q0.entry, l0_sl, l0_tp, "L0-FILL", None,
                             f"L0快通道 probUp={mp['probUp']}",
                             f"backtest-v4.7-{arm_label}", str(i_ts), 1))
                out.commit()
                last_trig[sym] = i_ts.value
                continue

            ema20 = c.iloc[max(0,i-200):i+1].ewm(span=20).mean().iloc[-1]
            ema60 = c.iloc[max(0,i-200):i+1].ewm(span=60).mean().iloc[-1]
            ema200 = c.iloc[max(0,i-400):i+1].ewm(span=200).mean().iloc[-1]
            trend15 = "UP" if ema20 > ema60 else "DOWN"
            trend1h = "UP" if ema60 > ema200 else "DOWN"
            atrv = float(atr(df, 14).iloc[i] / c.iloc[i] * 100)
            user_ctx = f"""品种：{sym}
触发原因：{why}
当前时间：{i_ts}
最新价：{c.iloc[i]:.6g}
15m动量：{pct15m:+.2f}%  5m：{pct5m:+.2f}%  RSI14：{r:.1f}  ATR：{atrv:.3f}%
15m趋势：{trend15}  1h趋势：{trend1h}
统计模型（30min展望）：{json.dumps(mp, ensure_ascii=False)}
持仓：无。品种最大杠杆：{'100' if sym in MAJORS else '50'}x。
请基于以上数据（这就是全部实时数据，无需再取数）直接输出最终 JSON 研判。"""
            last_trig[sym] = i_ts.value
            llm_calls += 1
            t0 = time.time()
            try:
                res = llm_judge(user_ctx)
            except Exception as e:
                print(f"[llm err] {sym} {e}", flush=True)
                time.sleep(2)
                continue
            ms = int((time.time() - t0) * 1000)
            action = str(res.get("action", "")).upper()
            if action not in ("BUY", "SELL"):
                continue
            entry = res.get("entry"); sl = res.get("stopLoss"); tp = res.get("takeProfit")
            try:
                entry, sl, tp = float(entry), float(sl), float(tp)
            except (TypeError, ValueError):
                continue
            sane = sl < entry < tp if action == "BUY" else tp < entry < sl
            if not sane or entry <= 0:
                continue
            # 规则层
            blk = breaker_blocks(sym, action, df, i)
            if blk:
                out.execute("insert into ai_advice_track(symbol,action,entry,stop_loss,"
                            "take_profit,status,result_pct,note,sys_version,created_at) "
                            "values(?,?,?,?,?,?,?,?,?,?)",
                            (sym, action, entry, sl, tp, "BLOCKED", None, blk,
                             f"backtest-v4.7-{arm_label}", str(i_ts)))
                out.commit()
                continue
            if arm != "notrend" and sym not in MAJORS:
                if (action == "BUY" and trend15 == "DOWN") or (action == "SELL" and trend15 == "UP"):
                    out.execute("insert into ai_advice_track(symbol,action,entry,stop_loss,"
                                "take_profit,status,result_pct,note,sys_version,created_at) "
                                "values(?,?,?,?,?,?,?,?,?,?)",
                                (sym, action, entry, sl, tp, "BLOCKED", None,
                                 "趋势纪律拦截", f"backtest-v4.7-{arm_label}", str(i_ts)))
                    out.commit()
                    continue
            if sym in MAJORS:
                dist = abs(entry - sl) / entry * 100
                if dist > CLAMP_MAJORS:
                    sl = entry - entry * CLAMP_MAJORS / 100 if action == "BUY" \
                        else entry + entry * CLAMP_MAJORS / 100
            # 入场分派
            q = Pos(); q.sym, q.action, q.entry, q.sl, q.tp = sym, action, entry, sl, tp
            q.ts, q.plan_ts = i_ts, i_ts
            q.rebased, q.breakeven, q.is_market = False, False, False
            q.wait_s, q.llm_ms = 0, ms
            if latency_s == -1:
                # 自适应延迟：本次 LLM 实测耗时 = 成交等待（含网络/代理抖动，
                # 分布自动对齐生产；llm_ms 一并存入账本供复盘）
                q.wait_s = max(1, ms / 1000.0)
                delay_queue[sym] = q
            elif latency_s > 0:
                # 固定延迟模式：全部按"研判完成 → 等 N 秒 → 市价成交"模拟
                q.wait_s = latency_s
                delay_queue[sym] = q
            elif abs(entry - c.iloc[i]) / c.iloc[i] < 0.0015:
                q.entry = entry * (1 + (SLIP_MARKET if action == "BUY" else -SLIP_MARKET))
                pos[sym] = q
            else:
                pending[sym] = q
            if llm_calls % 25 == 0:
                print(f"[prog] {i_ts} calls={llm_calls}/{budget} eq={equity:.1f} "
                      f"W/L={wins}/{losses_n}", flush=True)
    out.commit()
    print(f"[done] calls={llm_calls} W/L={wins}/{losses_n} equity={equity:.2f} "
          f"(start {EQUITY0})", flush=True)
    out.close()

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT,ACEUSDT,ZECUSDT,SNDKUSDT")
    ap.add_argument("--arm", default="full",
                    choices=["full", "nobreaker", "notrend", "norebase", "cascade-l0"])
    ap.add_argument("--budget", type=int, default=1200)
    ap.add_argument("--out", default=OUT_DB)
    ap.add_argument("--latency", type=int, default=0,
                    help="-1=自适应（LLM实测耗时即延迟）/ N>0=固定N秒 / 0=零延迟")
    ap.add_argument("--seg-offset", type=int, default=0,
                    help="跳过最近 N 天，从更早的历史开始（并行分段用）")
    a = ap.parse_args()
    run(a.symbols.split(","), a.days, a.arm, a.budget, a.out, a.latency, a.seg_offset)
