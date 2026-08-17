"""
QuanForge 模型推理 sidecar：http://127.0.0.1:40703/predict

输入 POST JSON: {"symbol": "BTCUSDT",
                 "klines": [[ts_ms, open, high, low, close, volume, turnover], ...]}
（Bybit 原始行，任意顺序，需 >= 130 行）
输出: {"probUp": 0.62, "direction": "UP", "confidence": 0.24,
       "zone": "high|mid|low", "expectedAcc": 0.58}

双模型按品种路由（实测教训：跨品种混训会让置信度校准崩塌——
v1 纯主流币高置信区 58%，7 品种混合后高置信区跌至 51%）：
  - model_majors.joblib: BTC/ETH/SOL（域内精确匹配）
  - model_alts.joblib:   HEMI/HYPE/CYS/ACE
特征计算与 tools/train_lgbm.py 逐字一致。仅绑定 127.0.0.1。
"""
import json
import joblib
import numpy as np
import pandas as pd
from http.server import BaseHTTPRequestHandler, HTTPServer

MAJORS = {"BTCUSDT", "ETHUSDT", "SOLUSDT"}

BUNDLES = {
    "majors": joblib.load("/mnt/nvme/quanforge/model_majors.joblib"),
    "alts": joblib.load("/mnt/nvme/quanforge/model_alts.joblib"),
}


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(),
                    (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def build(df: pd.DataFrame) -> pd.DataFrame:
    """与 train_lgbm.py 的 build() 保持一致"""
    f = pd.DataFrame(index=df.index)
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    for w in (5, 15, 30, 60, 120):
        f[f"ret_{w}"] = c.pct_change(w)
    f["atr14"] = atr(df, 14) / c
    f["range_30"] = (c.rolling(30).max() - c.rolling(30).min()) / c
    mid = c.rolling(20).mean()
    sd = c.rolling(20).std()
    f["boll_pos"] = (c - mid) / (2 * sd.replace(0, np.nan))
    f["rsi14"] = rsi(c)
    f["vol_ratio"] = v / (v.rolling(60).mean() + 1e-12)
    body = (c - df["open"]).abs()
    f["body_ratio"] = body / (h - l + 1e-12)
    f["up_wick"] = (h - pd.concat([c, df["open"]], axis=1).max(axis=1)) / (h - l + 1e-12)
    f["hour_sin"] = np.sin(2 * np.pi * df.index.hour / 24)
    f["hour_cos"] = np.cos(2 * np.pi * df.index.hour / 24)
    return f


def predict(symbol, klines):
    rows = sorted(klines, key=lambda r: int(r[0]))
    if len(rows) < 130:
        raise ValueError("klines 不足 130 行")
    domain = "majors" if symbol in MAJORS else "alts"
    bundle = BUNDLES[domain]
    model, features, calib = bundle["model"], bundle["features"], bundle["calibration"]
    df = pd.DataFrame({
        "open": [float(r[1]) for r in rows],
        "high": [float(r[2]) for r in rows],
        "low": [float(r[3]) for r in rows],
        "close": [float(r[4]) for r in rows],
        "volume": [float(r[5]) for r in rows],
    }, index=pd.to_datetime([int(r[0]) for r in rows], unit="ms"))
    feats = build(df).iloc[[-1]][features]
    if feats.isna().any(axis=1).iloc[0]:
        raise ValueError("特征含 NaN（数据异常）")
    proba = float(model.predict_proba(feats)[0, 1])
    conf = abs(proba - 0.5) * 2
    # 校准来自各自域的回测：{zone: (threshold, accuracy)}
    if conf >= calib["high_threshold"]:
        zone, acc = "high", calib["high_acc"]
    elif conf >= calib["mid_threshold"]:
        zone, acc = "mid", calib["mid_acc"]
    else:
        zone, acc = "low", calib["low_acc"]
    return {
        "probUp": round(proba, 4),
        "direction": "UP" if proba >= 0.5 else "DOWN",
        "confidence": round(conf, 4),
        "zone": zone,
        "expectedAcc": acc,
        "domain": domain,
        "inDomain": symbol in (MAJORS | set(bundle.get("symbols", []))),
    }


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/predict":
            self.send_error(404)
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n))
            result = predict(body.get("symbol", ""), body["klines"])
            payload = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except Exception as e:
            payload = json.dumps({"error": str(e)}).encode()
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    def log_message(self, fmt, *args):
        print("[model-server] " + fmt % args, flush=True)


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", 40703), Handler)
    print("[model-server] dual-model listening on 127.0.0.1:40703", flush=True)
    server.serve_forever()
