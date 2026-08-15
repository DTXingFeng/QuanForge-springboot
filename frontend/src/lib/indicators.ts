/**
 * 技术指标计算库（纯函数，无依赖）。
 * 约定：所有函数返回与输入等长的数组，数据不足处以 null 占位，
 * 便于按 K 线下标直接对齐图例与系列数据。
 */

export type Series = (number | null)[]

/** 简单移动平均（SMA） */
export function sma(values: number[], period: number): Series {
  const out: Series = new Array(values.length).fill(null)
  if (period <= 0) return out
  let sum = 0
  for (let i = 0; i < values.length; i++) {
    sum += values[i]
    if (i >= period) sum -= values[i - period]
    if (i >= period - 1) out[i] = sum / period
  }
  return out
}

/** 指数移动平均（EMA），首值以 SMA 播种 */
export function ema(values: number[], period: number): Series {
  const out: Series = new Array(values.length).fill(null)
  if (period <= 0 || values.length < period) return out
  const k = 2 / (period + 1)
  let sum = 0
  for (let i = 0; i < period; i++) sum += values[i]
  let prev = sum / period
  out[period - 1] = prev
  for (let i = period; i < values.length; i++) {
    prev = values[i] * k + prev * (1 - k)
    out[i] = prev
  }
  return out
}

/** 滚动窗口最高值 */
export function highest(values: number[], period: number): Series {
  const out: Series = new Array(values.length).fill(null)
  for (let i = period - 1; i < values.length; i++) {
    let m = -Infinity
    for (let j = i - period + 1; j <= i; j++) if (values[j] > m) m = values[j]
    out[i] = m
  }
  return out
}

/** 滚动窗口最低值 */
export function lowest(values: number[], period: number): Series {
  const out: Series = new Array(values.length).fill(null)
  for (let i = period - 1; i < values.length; i++) {
    let m = Infinity
    for (let j = i - period + 1; j <= i; j++) if (values[j] < m) m = values[j]
    out[i] = m
  }
  return out
}

/** Wilder 平滑（seed = 前 period 个值的 SMA），用于 ATR/DMI/RSI 一族 */
function wilder(values: number[], period: number): Series {
  const out: Series = new Array(values.length).fill(null)
  if (period <= 0 || values.length < period) return out
  let sum = 0
  for (let i = 0; i < period; i++) sum += values[i]
  let prev = sum / period
  out[period - 1] = prev
  for (let i = period; i < values.length; i++) {
    prev = (prev * (period - 1) + values[i]) / period
    out[i] = prev
  }
  return out
}

/** 取序列从首个非空值开始的连续数值段（前导 null 之后的段必须连续） */
function solid(s: Series): { vals: number[]; start: number } | null {
  const start = s.findIndex((v) => v != null)
  if (start < 0) return null
  const vals: number[] = []
  for (let i = start; i < s.length; i++) {
    const v = s[i]
    if (v == null) break
    vals.push(v)
  }
  return { vals, start }
}

/** 把计算结果按 start 偏移铺回等长 Series */
function expand(vals: Series, start: number, len: number): Series {
  const out: Series = new Array(len).fill(null)
  for (let i = 0; i < vals.length && start + i < len; i++) out[start + i] = vals[i]
  return out
}

/** 布林带（BOLL）：中轨 = SMA(N)，上下轨 = 中轨 ± mult × 总体标准差 */
export function bollinger(values: number[], period: number, mult: number) {
  const mid = sma(values, period)
  const upper: Series = new Array(values.length).fill(null)
  const lower: Series = new Array(values.length).fill(null)
  for (let i = period - 1; i < values.length; i++) {
    const m = mid[i]
    if (m == null) continue
    let sq = 0
    for (let j = i - period + 1; j <= i; j++) sq += (values[j] - m) ** 2
    const sd = Math.sqrt(sq / period)
    upper[i] = m + mult * sd
    lower[i] = m - mult * sd
  }
  return { mid, upper, lower }
}

/** 相对强弱指数（RSI），Wilder 平滑 */
export function rsi(values: number[], period: number): Series {
  const out: Series = new Array(values.length).fill(null)
  if (period <= 0 || values.length <= period) return out
  let avgGain = 0
  let avgLoss = 0
  for (let i = 1; i <= period; i++) {
    const d = values[i] - values[i - 1]
    avgGain += Math.max(d, 0)
    avgLoss += Math.max(-d, 0)
  }
  avgGain /= period
  avgLoss /= period
  const value = (g: number, l: number) =>
    g === 0 && l === 0 ? 50 : 100 - 100 / (1 + (l === 0 ? Infinity : g / l))
  out[period] = value(avgGain, avgLoss)
  for (let i = period + 1; i < values.length; i++) {
    const d = values[i] - values[i - 1]
    avgGain = (avgGain * (period - 1) + Math.max(d, 0)) / period
    avgLoss = (avgLoss * (period - 1) + Math.max(-d, 0)) / period
    out[i] = value(avgGain, avgLoss)
  }
  return out
}

/** MACD：DIF = EMA(fast) − EMA(slow)，DEA = DIF 的 EMA(signal)，柱 = DIF − DEA */
export function macd(values: number[], fast: number, slow: number, signal: number) {
  const emaFast = ema(values, fast)
  const emaSlow = ema(values, slow)
  const dif: Series = values.map((_, i) => {
    const f = emaFast[i]
    const s = emaSlow[i]
    return f != null && s != null ? f - s : null
  })
  const dea: Series = new Array(values.length).fill(null)
  const first = dif.findIndex((v) => v != null)
  if (first >= 0) {
    const k = 2 / (signal + 1)
    let sum = 0
    let prev: number | null = null
    for (let i = first; i < dif.length; i++) {
      const v = dif[i] as number
      if (prev === null) {
        sum += v
        // 连续收集满 signal 个有效 DIF 后，以 SMA 播种 DEA
        if (i - first + 1 === signal) {
          prev = sum / signal
          dea[i] = prev
        }
      } else {
        prev = v * k + prev * (1 - k)
        dea[i] = prev
      }
    }
  }
  const hist: Series = dif.map((d, i) =>
    d != null && dea[i] != null ? d - (dea[i] as number) : null,
  )
  return { dif, dea, hist }
}

/** KDJ：RSV = (C−Ln)/(Hn−Ln)×100，K/D 为 RSV 的平滑（α=1/period），J = 3K−2D */
export function kdj(
  highs: number[],
  lows: number[],
  closes: number[],
  n: number,
  kPeriod: number,
  dPeriod: number,
) {
  const len = closes.length
  const hh = highest(highs, n)
  const ll = lowest(lows, n)
  const k: Series = new Array(len).fill(null)
  const d: Series = new Array(len).fill(null)
  const j: Series = new Array(len).fill(null)
  let pk = 50
  let pd = 50
  for (let i = 0; i < len; i++) {
    const h = hh[i]
    const l = ll[i]
    if (h == null || l == null) continue
    const rsv = h === l ? 50 : ((closes[i] - l) / (h - l)) * 100
    pk = pk + (rsv - pk) / kPeriod
    pd = pd + (pk - pd) / dPeriod
    k[i] = pk
    d[i] = pd
    j[i] = 3 * pk - 2 * pd
  }
  return { k, d, j }
}

/** 随机指标 STOCH：%K = (C−Ln)/(Hn−Ln)×100 再平滑 kSmooth，%D = %K 的 SMA */
export function stochastic(
  highs: number[],
  lows: number[],
  closes: number[],
  kPeriod: number,
  kSmooth: number,
  dPeriod: number,
) {
  const len = closes.length
  const hh = highest(highs, kPeriod)
  const ll = lowest(lows, kPeriod)
  const raw: Series = new Array(len).fill(null)
  for (let i = 0; i < len; i++) {
    const h = hh[i]
    const l = ll[i]
    if (h == null || l == null) continue
    raw[i] = h === l ? 50 : ((closes[i] - l) / (h - l)) * 100
  }
  const ks = solid(raw)
  const k: Series = ks ? expand(sma(ks.vals, kSmooth), ks.start, len) : new Array(len).fill(null)
  const kd = solid(k)
  const d: Series = kd ? expand(sma(kd.vals, dPeriod), kd.start, len) : new Array(len).fill(null)
  return { k, d }
}

/** 威廉指标 WR：(Hn−C)/(Hn−Ln)×(−100)，取值 −100..0 */
export function williamsR(
  highs: number[],
  lows: number[],
  closes: number[],
  period: number,
): Series {
  const hh = highest(highs, period)
  const ll = lowest(lows, period)
  return closes.map((c, i) => {
    const h = hh[i]
    const l = ll[i]
    if (h == null || l == null) return null
    return h === l ? -50 : (-100 * (h - c)) / (h - l)
  })
}

/** 顺势指标 CCI：(TP−SMA(TP,n)) / (0.015×平均绝对偏差) */
export function cci(
  highs: number[],
  lows: number[],
  closes: number[],
  period: number,
): Series {
  const len = closes.length
  const tp = closes.map((c, i) => (highs[i] + lows[i] + c) / 3)
  const mid = sma(tp, period)
  const out: Series = new Array(len).fill(null)
  for (let i = period - 1; i < len; i++) {
    const m = mid[i]
    if (m == null) continue
    let dev = 0
    for (let j2 = i - period + 1; j2 <= i; j2++) dev += Math.abs(tp[j2] - m)
    dev /= period
    out[i] = dev === 0 ? 0 : (tp[i] - m) / (0.015 * dev)
  }
  return out
}

/** 平均真实波幅 ATR（Wilder 平滑） */
export function atr(highs: number[], lows: number[], closes: number[], period: number): Series {
  const len = closes.length
  if (len === 0) return []
  const tr: number[] = new Array(len)
  tr[0] = highs[0] - lows[0]
  for (let i = 1; i < len; i++) {
    const pc = closes[i - 1]
    tr[i] = Math.max(highs[i] - lows[i], Math.abs(highs[i] - pc), Math.abs(lows[i] - pc))
  }
  return wilder(tr, period)
}

/** 趋向指标 DMI：+DI/−DI 与 ADX */
export function dmi(
  highs: number[],
  lows: number[],
  closes: number[],
  diPeriod: number,
  adxPeriod: number,
) {
  const len = closes.length
  const tr: number[] = new Array(len)
  const pdm: number[] = new Array(len)
  const ndm: number[] = new Array(len)
  if (len > 0) {
    tr[0] = highs[0] - lows[0]
    pdm[0] = 0
    ndm[0] = 0
  }
  for (let i = 1; i < len; i++) {
    const pc = closes[i - 1]
    tr[i] = Math.max(highs[i] - lows[i], Math.abs(highs[i] - pc), Math.abs(lows[i] - pc))
    const up = highs[i] - pc
    const dn = pc - lows[i]
    pdm[i] = up > dn && up > 0 ? up : 0
    ndm[i] = dn > up && dn > 0 ? dn : 0
  }
  const smTr = wilder(tr, diPeriod)
  const smP = wilder(pdm, diPeriod)
  const smN = wilder(ndm, diPeriod)
  const plus: Series = new Array(len).fill(null)
  const minus: Series = new Array(len).fill(null)
  const dx: Series = new Array(len).fill(null)
  for (let i = 0; i < len; i++) {
    const t = smTr[i]
    if (t == null || t === 0) continue
    const p = (100 * (smP[i] as number)) / t
    const m = (100 * (smN[i] as number)) / t
    plus[i] = p
    minus[i] = m
    const sum = p + m
    dx[i] = sum === 0 ? 0 : (100 * Math.abs(p - m)) / sum
  }
  const dxs = solid(dx)
  const adx: Series = dxs ? expand(wilder(dxs.vals, adxPeriod), dxs.start, len) : new Array(len).fill(null)
  return { plus, minus, adx }
}

/** 能量潮 OBV：按收盘涨跌方向累积成交量 */
export function obv(closes: number[], volumes: number[]): Series {
  const len = closes.length
  const out: Series = new Array(len).fill(null)
  let acc = 0
  for (let i = 0; i < len; i++) {
    if (i > 0) {
      const d = closes[i] - closes[i - 1]
      acc += d > 0 ? volumes[i] : d < 0 ? -volumes[i] : 0
    }
    out[i] = acc
  }
  return out
}

/** 资金流量指标 MFI（0..100） */
export function mfi(
  highs: number[],
  lows: number[],
  closes: number[],
  volumes: number[],
  period: number,
): Series {
  const len = closes.length
  const out: Series = new Array(len).fill(null)
  const tp = closes.map((c, i) => (highs[i] + lows[i] + c) / 3)
  const mf = tp.map((t, i) => t * volumes[i])
  let pos = 0
  let neg = 0
  // 资金流方向定义在第 i 根（i>=1）：tp[i] 对比 tp[i-1]
  for (let i = 1; i < len; i++) {
    if (tp[i] > tp[i - 1]) pos += mf[i]
    else if (tp[i] < tp[i - 1]) neg += mf[i]
    const old = i - period
    if (old >= 1) {
      if (tp[old] > tp[old - 1]) pos -= mf[old]
      else if (tp[old] < tp[old - 1]) neg -= mf[old]
    }
    if (i >= period) {
      out[i] = neg === 0 ? (pos === 0 ? 50 : 100) : 100 - 100 / (1 + pos / neg)
    }
  }
  return out
}

/** 抛物线转向 SAR（Wilder）：加速因子从 start 起，创极值加 increment，封顶 max */
export function sar(
  highs: number[],
  lows: number[],
  start = 0.02,
  increment = 0.02,
  max = 0.2,
): Series {
  const len = lows.length
  const out: Series = new Array(len).fill(null)
  if (len < 2) return out
  // 初始趋势由前两根 K 线判断
  let up = highs[1] >= highs[0]
  let af = start
  let ep = up ? Math.max(highs[0], highs[1]) : Math.min(lows[0], lows[1])
  out[1] = up ? Math.min(lows[0], lows[1]) : Math.max(highs[0], highs[1])
  for (let i = 2; i < len; i++) {
    const prev = out[i - 1] as number
    let s = prev + af * (ep - prev)
    if (up) {
      // SAR 不得高于前两根 K 线的低点
      s = Math.min(s, lows[i - 1], lows[i - 2])
      if (lows[i] < s) {
        // 跌破 SAR → 反转：新 SAR = 前段极值高点
        up = false
        s = ep
        ep = lows[i]
        af = start
      } else if (highs[i] > ep) {
        ep = highs[i]
        af = Math.min(af + increment, max)
      }
    } else {
      // SAR 不得低于前两根 K 线的高点
      s = Math.max(s, highs[i - 1], highs[i - 2])
      if (highs[i] > s) {
        // 涨破 SAR → 反转：新 SAR = 前段极值低点
        up = true
        s = ep
        ep = highs[i]
        af = start
      } else if (lows[i] < ep) {
        ep = lows[i]
        af = Math.min(af + increment, max)
      }
    }
    out[i] = s
  }
  return out
}

/** 成交量加权均价 VWAP：按 UTC 自然日重置（无参数） */
export function vwap(
  times: number[],
  highs: number[],
  lows: number[],
  closes: number[],
  volumes: number[],
): Series {
  const len = closes.length
  const out: Series = new Array(len).fill(null)
  let day = -1
  let cpv = 0
  let cv = 0
  for (let i = 0; i < len; i++) {
    const d = Math.floor(times[i] / 86400)
    if (d !== day) {
      day = d
      cpv = 0
      cv = 0
    }
    const tp = (highs[i] + lows[i] + closes[i]) / 3
    cpv += tp * volumes[i]
    cv += volumes[i]
    out[i] = cv > 0 ? cpv / cv : closes[i]
  }
  return out
}
