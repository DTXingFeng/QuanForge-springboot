package xyz.xingfeng.QuanForge.service;

/**
 * 技术指标计算（最新值），供 AI 工具层与异动检测共用。
 * 算法与前端 indicators.ts 保持一致（RSI/MACD Wilder 口径）。
 * 数据不足时返回 NaN。
 */
final class IndicatorMath {

	private IndicatorMath() {
	}

	/** SMA 最新值 */
	static double smaLast(double[] values, int period) {
		if (values.length < period || period <= 0) {
			return Double.NaN;
		}
		double sum = 0;
		for (int i = values.length - period; i < values.length; i++) {
			sum += values[i];
		}
		return sum / period;
	}

	/** EMA 序列（首值 SMA 播种） */
	static double[] emaSeries(double[] values, int period) {
		double[] out = new double[values.length];
		if (period <= 0 || values.length < period) {
			return out;
		}
		double k = 2.0 / (period + 1);
		double sum = 0;
		for (int i = 0; i < period; i++) {
			sum += values[i];
		}
		out[period - 1] = sum / period;
		for (int i = period; i < values.length; i++) {
			out[i] = values[i] * k + out[i - 1] * (1 - k);
		}
		return out;
	}

	/** EMA 最新值 */
	static double emaLast(double[] values, int period) {
		double[] s = emaSeries(values, period);
		return s.length > 0 ? s[s.length - 1] : Double.NaN;
	}

	/** RSI 最新值（Wilder 平滑） */
	static double rsiLast(double[] closes, int period) {
		if (closes.length <= period || period <= 0) {
			return Double.NaN;
		}
		double avgGain = 0;
		double avgLoss = 0;
		for (int i = 1; i <= period; i++) {
			double d = closes[i] - closes[i - 1];
			avgGain += Math.max(d, 0);
			avgLoss += Math.max(-d, 0);
		}
		avgGain /= period;
		avgLoss /= period;
		for (int i = period + 1; i < closes.length; i++) {
			double d = closes[i] - closes[i - 1];
			avgGain = (avgGain * (period - 1) + Math.max(d, 0)) / period;
			avgLoss = (avgLoss * (period - 1) + Math.max(-d, 0)) / period;
		}
		if (avgGain == 0 && avgLoss == 0) {
			return 50;
		}
		if (avgLoss == 0) {
			return 100;
		}
		return 100 - 100 / (1 + avgGain / avgLoss);
	}

	/** MACD 最新值：[DIF, DEA, HIST] */
	static double[] macdLast(double[] closes, int fast, int slow, int signal) {
		double[] ef = emaSeries(closes, fast);
		double[] es = emaSeries(closes, slow);
		java.util.List<Double> dif = new java.util.ArrayList<>();
		for (int i = slow - 1; i < closes.length; i++) {
			dif.add(ef[i] - es[i]);
		}
		if (dif.size() < signal) {
			return new double[] { Double.NaN, Double.NaN, Double.NaN };
		}
		double prev = 0;
		for (int i = 0; i < signal; i++) {
			prev += dif.get(i);
		}
		prev /= signal;
		double k = 2.0 / (signal + 1);
		for (int i = signal; i < dif.size(); i++) {
			prev = dif.get(i) * k + prev * (1 - k);
		}
		double d = dif.get(dif.size() - 1);
		return new double[] { d, prev, d - prev };
	}

	/** BOLL 最新值：[upper, mid, lower]（总体标准差） */
	static double[] bollLast(double[] closes, int period, double mult) {
		double mid = smaLast(closes, period);
		if (Double.isNaN(mid)) {
			return new double[] { Double.NaN, Double.NaN, Double.NaN };
		}
		double sq = 0;
		for (int i = closes.length - period; i < closes.length; i++) {
			sq += (closes[i] - mid) * (closes[i] - mid);
		}
		double sd = Math.sqrt(sq / period);
		return new double[] { mid + mult * sd, mid, mid - mult * sd };
	}

	/** KDJ 最新值：[K, D, J] */
	static double[] kdjLast(double[] highs, double[] lows, double[] closes,
			int n, int kPeriod, int dPeriod) {
		double pk = 50;
		double pd = 50;
		boolean seeded = false;
		for (int i = 0; i < closes.length; i++) {
			int from = Math.max(0, i - n + 1);
			double hh = -Double.MAX_VALUE;
			double ll = Double.MAX_VALUE;
			for (int j = from; j <= i; j++) {
				if (highs[j] > hh) {
					hh = highs[j];
				}
				if (lows[j] < ll) {
					ll = lows[j];
				}
			}
			if (!seeded && i - from + 1 < n) {
				continue;
			}
			seeded = true;
			double rsv = hh == ll ? 50 : (closes[i] - ll) / (hh - ll) * 100;
			pk = pk + (rsv - pk) / kPeriod;
			pd = pd + (pk - pd) / dPeriod;
		}
		if (!seeded) {
			return new double[] { Double.NaN, Double.NaN, Double.NaN };
		}
		return new double[] { pk, pd, 3 * pk - 2 * pd };
	}

	/** ATR 最新值（Wilder 平滑） */
	static double atrLast(double[] highs, double[] lows, double[] closes, int period) {
		int len = closes.length;
		if (len < period + 1 || period <= 0) {
			return Double.NaN;
		}
		double[] tr = new double[len];
		tr[0] = highs[0] - lows[0];
		for (int i = 1; i < len; i++) {
			double pc = closes[i - 1];
			tr[i] = Math.max(highs[i] - lows[i],
					Math.max(Math.abs(highs[i] - pc), Math.abs(lows[i] - pc)));
		}
		double prev = 0;
		for (int i = 1; i <= period; i++) {
			prev += tr[i];
		}
		prev /= period;
		for (int i = period + 1; i < len; i++) {
			prev = (prev * (period - 1) + tr[i]) / period;
		}
		return prev;
	}
}
