"""
QuanForge 训练数据准备 + 基线模型评估
用法:
  python train_baseline.py --db /mnt/nvme/quanforge/data/quanforge.db [--horizon 30]

产出:
  1. 基线对照（永远猜涨 / 猜多数类）
  2. 逻辑回归方向分类器（未来 horizon 分钟收盘涨/跌）时间序列切分评估
说明: 用 scikit-learn（pip install scikit-learn pandas numpy），Pi 上可直接跑（CPU）。
"""
import argparse
import sqlite3

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report
from sklearn.preprocessing import StandardScaler

FEATURES = []


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    pc = df["close"].shift()
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - pc).abs(),
        (df["low"] - pc).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    f = pd.DataFrame(index=df.index)
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    # 收益率族（不同回看窗）
    for w in (5, 15, 30, 60, 120):
        f[f"ret_{w}"] = c.pct_change(w)
    # 波动族
    f["atr14"] = atr(df, 14) / c
    f["range_30"] = (c.rolling(30).max() - c.rolling(30).min()) / c
    # 布林位置（20）
    mid = c.rolling(20).mean()
    sd = c.rolling(20).std()
    f["boll_pos"] = (c - mid) / (2 * sd.replace(0, np.nan))
    # 动量指标
    f["rsi14"] = rsi(c)
    f["vol_ratio"] = v / (v.rolling(60).mean() + 1e-12)
    # K 线形态
    body = (c - df["open"]).abs()
    f["body_ratio"] = body / (h - l + 1e-12)
    f["up_wick"] = (h - pd.concat([c, df["open"]], axis=1).max(axis=1)) / (h - l + 1e-12)
    f["hour_sin"] = np.sin(2 * np.pi * df.index.hour / 24)
    f["hour_cos"] = np.cos(2 * np.pi * df.index.hour / 24)
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT")
    ap.add_argument("--horizon", type=int, default=30, help="预测未来多少分钟")
    ap.add_argument("--test-ratio", type=float, default=0.2)
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    frames = []
    for sym in args.symbols.split(","):
        df = pd.read_sql_query(
            "SELECT open_time, open, high, low, close, volume FROM kline_1m "
            "WHERE symbol=? ORDER BY open_time", conn, params=(sym.strip(),),
            parse_dates=["open_time"])
        if len(df) < 3000:
            print(f"[skip] {sym}: 只有 {len(df)} 根（<3000）")
            continue
        df = df.set_index("open_time")
        feats = build_features(df)
        # 标签：未来 horizon 分钟收盘价相对当前（剔除手续费 0.055% taker 单边的影响先不做了，纯方向）
        feats["label"] = (df["close"].shift(-args.horizon) > df["close"]).astype(int)
        feats["symbol"] = sym
        frames.append(feats.dropna())
        print(f"[load] {sym}: {len(df)} 根 -> 特征 {len(feats.dropna())} 行")
    conn.close()
    if not frames:
        print("无足够数据")
        return

    data = pd.concat(frames)
    feat_cols = [c for c in data.columns if c not in ("label", "symbol")]
    # 时间序列切分：前 80% 训练，后 20% 测试（各 symbol 内部保持时间序）
    data = data.sort_index()
    n = len(data)
    split = int(n * (1 - args.test_ratio))
    train, test = data.iloc[:split], data.iloc[split:]

    print(f"\n=== 数据集：{n} 行（train {len(train)} / test {len(test)}），horizon={args.horizon}min ===")
    print(f"标签分布（全量）: 涨 {data['label'].mean():.4f}")

    # ---- 基线对照 ----
    majority = int(train["label"].mode()[0])
    base_acc = accuracy_score(test["label"], [majority] * len(test))
    print(f"\n[基线] 永远猜{'涨' if majority == 1 else '跌'}: test 准确率 {base_acc:.4f}")

    # ---- 逻辑回归 ----
    scaler = StandardScaler().fit(train[feat_cols])
    model = LogisticRegression(max_iter=1000, C=0.1)
    model.fit(scaler.transform(train[feat_cols]), train["label"])
    pred = model.predict(scaler.transform(test[feat_cols]))
    acc = accuracy_score(test["label"], pred)
    print(f"[LogReg] test 准确率 {acc:.4f}（vs 基线 {base_acc:.4f}，提升 {acc - base_acc:+.4f}）")
    print(classification_report(test["label"], pred, target_names=["跌", "涨"], digits=3))

    # 特征重要性（|系数| 排序，标准化后可比）
    imp = sorted(zip(feat_cols, np.abs(model.coef_[0])), key=lambda x: -x[1])
    print("Top 特征:", ", ".join(f"{c}({v:.2f})" for c, v in imp[:8]))


if __name__ == "__main__":
    main()
