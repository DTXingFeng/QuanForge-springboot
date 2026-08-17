"""
LightGBM 方向模型 + 高波动条件标签
标签: 未来 horizon 分钟波幅 >= move_pct 时记录方向（涨/跌），否则样本丢弃（NaN）
     —— 只在"有事发生"的样本上学方向，对齐 0.1% 门槛的实战场景
评估: 时间序列切分，报告整体准确率 + 分品种 + 按预测置信度分桶的校准
用法: python train_lgbm.py --db /mnt/nvme/quanforge/data/quanforge.db
"""
import argparse
import sqlite3

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score

FS = ["ret_5", "ret_15", "ret_30", "ret_60", "ret_120", "atr14", "range_30",
      "boll_pos", "rsi14", "vol_ratio", "body_ratio", "up_wick", "hour_sin", "hour_cos"]


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT")
    ap.add_argument("--horizon", type=int, default=30)
    ap.add_argument("--move-pct", type=float, default=0.15,
                    help="未来波幅门槛（%%），低于此的样本丢弃")
    ap.add_argument("--test-ratio", type=float, default=0.2)
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    frames = []
    for sym in args.symbols.split(","):
        df = pd.read_sql_query(
            "SELECT open_time, open, high, low, close, volume FROM kline_1m "
            "WHERE symbol=? ORDER BY open_time", conn, params=(sym.strip(),),
            parse_dates=["open_time"]).set_index("open_time")
        if len(df) < 3000:
            continue
        feats = build(df)
        fut_close = df["close"].shift(-args.horizon)
        fut_high = df["high"].rolling(args.horizon).max().shift(-args.horizon)
        fut_low = df["low"].rolling(args.horizon).min().shift(-args.horizon)
        fut_move = (fut_high - fut_low) / df["close"] * 100
        feats["label"] = np.where(fut_close > df["close"], 1, 0)
        feats["fut_move"] = fut_move
        feats["symbol"] = sym
        feats["row_id"] = np.arange(len(feats))  # 全局唯一行号，避免跨品种时间戳撞索引
        frames.append(feats)
        print(f"[load] {sym}: {len(df)} 根")
    conn.close()

    data = pd.concat(frames).dropna(subset=FS)
    # 条件标签：只在未来波幅 >= 门槛的样本上训练/评估
    kept = data[data["fut_move"] >= args.move_pct].copy()
    dropped = len(data) - len(kept)
    print(f"\n条件标签: 保留 {len(kept)} / {len(data)} 样本"
          f"（未来{args.horizon}min波幅≥{args.move_pct}%，丢弃横盘 {dropped}）")
    print(f"标签分布: 涨 {kept['label'].mean():.4f}")

    kept = kept.sort_index()
    n = len(kept)
    split = int(n * (1 - args.test_ratio))
    tr, te = kept.iloc[:split], kept.iloc[split:]
    print(f"切分: train {len(tr)} / test {len(te)}（时间序列）")

    try:
        import lightgbm as lgb
        model = lgb.LGBMClassifier(
            n_estimators=400, learning_rate=0.05, num_leaves=63,
            min_child_samples=200, subsample=0.8, colsample_bytree=0.8,
            random_state=42, verbose=-1)
        name = "LightGBM"
    except ImportError:
        from sklearn.ensemble import HistGradientBoostingClassifier
        model = HistGradientBoostingClassifier(
            max_iter=400, learning_rate=0.05, max_leaf_nodes=63,
            min_samples_leaf=200, random_state=42)
        name = "HistGB( sklearn fallback)"
    model.fit(tr[FS], tr["label"])

    proba = model.predict_proba(te[FS])[:, 1]
    pred = (proba >= 0.5).astype(int)
    label_arr = te["label"].to_numpy()
    symbol_arr = te["symbol"].to_numpy()
    acc = accuracy_score(label_arr, pred)
    base = max(label_arr.mean(), 1 - label_arr.mean())
    print(f"\n[{name}] 整体准确率 {acc:.4f}（基线猜多数 {base:.4f}，提升 {acc - base:+.4f}）")

    print("\n=== 分品种（按位置对齐，无索引）===")
    for sym in np.unique(symbol_arr):
        m = symbol_arr == sym
        a = accuracy_score(label_arr[m], pred[m])
        print(f"  {sym:<10} n={int(m.sum()):<7} acc={a:.4f}")

    print("\n=== 置信度分桶（校准）===")
    conf = np.abs(proba - 0.5) * 2
    correct = (pred == label_arr)
    for lo, hi, tag in [(0.0, 0.1, "|p-0.5|<0.05"), (0.1, 0.3, "0.05~0.15"),
                        (0.3, 1.01, ">=0.15")]:
        m = (conf >= lo) & (conf < hi)
        if m.sum() > 0:
            print(f"  置信 {tag:<14} n={int(m.sum()):<7} acc={correct[m].mean():.4f}")

    imp = sorted(zip(FS, model.feature_importances_), key=lambda x: -x[1])
    print("\nTop 特征:", ", ".join(f"{c}({v:.0f})" for c, v in imp[:8]))
    # 持久化模型与特征列表，供 get_model_prediction 工具加载
    try:
        import joblib
        joblib.dump({"model": model, "features": FS, "horizon": args.horizon,
                     "move_pct": args.move_pct}, "model_lgbm.joblib")
        print("\n模型已保存: model_lgbm.joblib")
    except Exception as e:
        print(f"模型保存失败: {e}")


if __name__ == "__main__":
    main()
