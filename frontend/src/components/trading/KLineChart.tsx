import { Fragment, useEffect, useRef, useState, type ReactNode } from "react"
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  ColorType,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts"
import { CandlestickChart, Loader2, RefreshCw, Settings2 } from "lucide-react"
import { useTradeStore } from "../../store/tradeStore"
import SymbolSelect from "./SymbolSelect"
import {
  sma,
  ema,
  bollinger,
  rsi,
  macd,
  kdj,
  stochastic,
  williamsR,
  cci,
  dmi,
  atr,
  obv,
  mfi,
  vwap,
  sar,
  type Series,
} from "../../lib/indicators"

interface KlineItem {
  time: UTCTimestamp
  open: number
  high: number
  low: number
  close: number
  volume: number
}

const INTERVALS = [
  { label: "1m", value: "1" },
  { label: "5m", value: "5" },
  { label: "15m", value: "15" },
  { label: "30m", value: "30" },
  { label: "1h", value: "60" },
  { label: "4h", value: "240" },
  { label: "1d", value: "D" },
]

// ==================== 指标定义表 ====================

type Scope = "overlay" | "sub"

interface ParamDef {
  field: string
  label: string
  min?: number
  max?: number
  step?: number
}

/** 图例中的一段文本（可带线色） */
interface Seg {
  text: string
  color?: string
}

interface Point {
  time: UTCTimestamp
  value: number
  color?: string
}

interface SeriesSpec {
  kind: "line" | "hist"
  color: string
  width?: 1 | 2
  data: Point[]
  /** 副图固定值域（RSI 0-100 等） */
  fixedRange?: [number, number]
  /** 只画点不画线（SAR 点列） */
  pointsOnly?: boolean
}

interface IndicatorDef {
  key: string
  scope: Scope
  defaultOn?: boolean
  defaults: Record<string, number>
  label: (p: Record<string, number>) => string
  dots: string[]
  paramDefs: ParamDef[]
  /** 参考虚线（如 RSI 的 30/70） */
  guides?: number[]
  compute: (
    data: KlineItem[],
    p: Record<string, number>,
  ) => { series: SeriesSpec[]; legend: (idx: number) => Seg[] }
}

const MA_COLORS = ["#fbbf24", "#a78bfa", "#38bdf8"]
const EMA_COLORS = ["#fb7185", "#34d399", "#a3e635"]
const BOLL_MID_COLOR = "#e879f9"
const BOLL_BAND_COLOR = "#22d3ee"
const RSI_COLOR = "#fbbf24"
const MACD_DIF_COLOR = "#38bdf8"
const MACD_DEA_COLOR = "#f59e0b"
const VWAP_COLOR = "#f472b6"
const SAR_COLOR = "#2dd4bf"
const KDJ_K_COLOR = "#38bdf8"
const KDJ_D_COLOR = "#f59e0b"
const KDJ_J_COLOR = "#e879f9"
const STOCH_K_COLOR = "#38bdf8"
const STOCH_D_COLOR = "#f43f5e"
const WR_COLOR = "#a3e635"
const CCI_COLOR = "#fbbf24"
const DMI_PLUS_COLOR = "#34d399"
const DMI_MINUS_COLOR = "#f43f5e"
const DMI_ADX_COLOR = "#a78bfa"
const ATR_COLOR = "#fb923c"
const OBV_COLOR = "#60a5fa"
const MFI_COLOR = "#f472b6"
const LEGEND_NAME_COLOR = "#71717a"
const UP_COLOR = "#10b981"
const DOWN_COLOR = "#f43f5e"

const fmtP = (v: number | null | undefined) =>
  v == null
    ? "—"
    : v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 6 })
const fmt2 = (v: number | null | undefined) => (v == null ? "—" : v.toFixed(2))
const compactFmt = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 })

/** Series → 图表数据点（跳过前导空值） */
function toPts(data: KlineItem[], s: Series): Point[] {
  const out: Point[] = []
  for (let i = 0; i < data.length; i++) {
    const v = s[i]
    if (v != null) out.push({ time: data[i].time, value: v })
  }
  return out
}

const INDICATORS: IndicatorDef[] = [
  // ---------- 主图叠加 ----------
  {
    key: "ma",
    scope: "overlay",
    defaultOn: true,
    defaults: { fast: 7, mid: 25, slow: 99 },
    label: (p) => `MA(${p.fast},${p.mid},${p.slow})`,
    dots: MA_COLORS,
    paramDefs: [
      { field: "fast", label: "快" },
      { field: "mid", label: "中" },
      { field: "slow", label: "慢" },
    ],
    compute: (data, p) => {
      const closes = data.map((d) => d.close)
      const ps = [p.fast, p.mid, p.slow]
      const arrs = ps.map((x) => sma(closes, x))
      return {
        series: ps.map((_, i) => ({ kind: "line", color: MA_COLORS[i], data: toPts(data, arrs[i]) })),
        legend: (idx) => [
          ...ps.map((x, i) => ({ text: `MA${x} ${fmtP(arrs[i][idx])}`, color: MA_COLORS[i] })),
        ],
      }
    },
  },
  {
    key: "ema",
    scope: "overlay",
    defaults: { fast: 7, mid: 25, slow: 99 },
    label: (p) => `EMA(${p.fast},${p.mid},${p.slow})`,
    dots: EMA_COLORS,
    paramDefs: [
      { field: "fast", label: "快" },
      { field: "mid", label: "中" },
      { field: "slow", label: "慢" },
    ],
    compute: (data, p) => {
      const closes = data.map((d) => d.close)
      const ps = [p.fast, p.mid, p.slow]
      const arrs = ps.map((x) => ema(closes, x))
      return {
        series: ps.map((_, i) => ({ kind: "line", color: EMA_COLORS[i], data: toPts(data, arrs[i]) })),
        legend: (idx) => [
          ...ps.map((x, i) => ({ text: `EMA${x} ${fmtP(arrs[i][idx])}`, color: EMA_COLORS[i] })),
        ],
      }
    },
  },
  {
    key: "boll",
    scope: "overlay",
    defaults: { period: 20, mult: 2 },
    label: (p) => `BOLL(${p.period},${p.mult})`,
    dots: [BOLL_BAND_COLOR, BOLL_MID_COLOR, BOLL_BAND_COLOR],
    paramDefs: [
      { field: "period", label: "周期" },
      { field: "mult", label: "倍数", min: 0.5, max: 5, step: 0.1 },
    ],
    compute: (data, p) => {
      const closes = data.map((d) => d.close)
      const b = bollinger(closes, p.period, p.mult)
      return {
        series: [
          { kind: "line", color: BOLL_BAND_COLOR, data: toPts(data, b.upper) },
          { kind: "line", color: BOLL_MID_COLOR, data: toPts(data, b.mid) },
          { kind: "line", color: BOLL_BAND_COLOR, data: toPts(data, b.lower) },
        ],
        legend: (idx) => [
          { text: `BOLL(${p.period},${p.mult})`, color: LEGEND_NAME_COLOR },
          { text: fmtP(b.upper[idx]), color: BOLL_BAND_COLOR },
          { text: fmtP(b.mid[idx]), color: BOLL_MID_COLOR },
          { text: fmtP(b.lower[idx]), color: BOLL_BAND_COLOR },
        ],
      }
    },
  },
  {
    key: "vwap",
    scope: "overlay",
    defaults: {},
    label: () => "VWAP",
    dots: [VWAP_COLOR],
    paramDefs: [],
    compute: (data) => {
      const s = vwap(
        data.map((d) => d.time as number),
        data.map((d) => d.high),
        data.map((d) => d.low),
        data.map((d) => d.close),
        data.map((d) => d.volume),
      )
      return {
        series: [{ kind: "line", color: VWAP_COLOR, data: toPts(data, s) }],
        legend: (idx) => [
          { text: "VWAP", color: LEGEND_NAME_COLOR },
          { text: fmtP(s[idx]), color: VWAP_COLOR },
        ],
      }
    },
  },
  // ---------- 副图窗格 ----------
  {
    key: "rsi",
    scope: "sub",
    defaults: { period: 14 },
    label: (p) => `RSI(${p.period})`,
    dots: [RSI_COLOR],
    paramDefs: [{ field: "period", label: "周期" }],
    guides: [30, 70],
    compute: (data, p) => {
      const s = rsi(
        data.map((d) => d.close),
        p.period,
      )
      return {
        series: [
          {
            kind: "line",
            color: RSI_COLOR,
            width: 2,
            fixedRange: [0, 100],
            data: toPts(data, s),
          },
        ],
        legend: (idx) => [
          { text: `RSI(${p.period})`, color: LEGEND_NAME_COLOR },
          { text: fmt2(s[idx]), color: RSI_COLOR },
        ],
      }
    },
  },
  {
    key: "macd",
    scope: "sub",
    defaults: { fast: 12, slow: 26, signal: 9 },
    label: (p) => `MACD(${p.fast},${p.slow},${p.signal})`,
    dots: [MACD_DIF_COLOR, MACD_DEA_COLOR],
    paramDefs: [
      { field: "fast", label: "快" },
      { field: "slow", label: "慢" },
      { field: "signal", label: "信号" },
    ],
    guides: [0],
    compute: (data, p) => {
      const m = macd(
        data.map((d) => d.close),
        p.fast,
        p.slow,
        p.signal,
      )
      const histPts: Point[] = []
      for (let i = 0; i < data.length; i++) {
        const v = m.hist[i]
        if (v != null)
          histPts.push({ time: data[i].time, value: v, color: v >= 0 ? "rgba(16,185,129,0.55)" : "rgba(244,63,94,0.55)" })
      }
      return {
        series: [
          { kind: "hist", color: "", data: histPts },
          { kind: "line", color: MACD_DIF_COLOR, data: toPts(data, m.dif) },
          { kind: "line", color: MACD_DEA_COLOR, data: toPts(data, m.dea) },
        ],
        legend: (idx) => [
          { text: `MACD(${p.fast},${p.slow},${p.signal})`, color: LEGEND_NAME_COLOR },
          { text: fmt2(m.dif[idx]), color: MACD_DIF_COLOR },
          { text: fmt2(m.dea[idx]), color: MACD_DEA_COLOR },
          { text: fmt2(m.hist[idx]), color: m.hist[idx] != null && m.hist[idx]! >= 0 ? UP_COLOR : DOWN_COLOR },
        ],
      }
    },
  },
  {
    key: "sar",
    scope: "overlay",
    defaults: { start: 0.02, inc: 0.02, max: 0.2 },
    label: (p) => `SAR(${p.start},${p.inc},${p.max})`,
    dots: [SAR_COLOR],
    paramDefs: [
      { field: "start", label: "起步", min: 0.01, max: 0.2, step: 0.01 },
      { field: "inc", label: "步进", min: 0.01, max: 0.2, step: 0.01 },
      { field: "max", label: "上限", min: 0.05, max: 0.5, step: 0.05 },
    ],
    compute: (data, p) => {
      const s = sar(
        data.map((d) => d.high),
        data.map((d) => d.low),
        p.start,
        p.inc,
        p.max,
      )
      return {
        series: [{ kind: "line", color: SAR_COLOR, pointsOnly: true, data: toPts(data, s) }],
        legend: (idx) => [
          { text: `SAR(${p.start},${p.inc},${p.max})`, color: LEGEND_NAME_COLOR },
          { text: fmtP(s[idx]), color: SAR_COLOR },
        ],
      }
    },
  },
  {
    key: "kdj",
    scope: "sub",
    defaults: { n: 9, k: 3, d: 3 },
    label: (p) => `KDJ(${p.n},${p.k},${p.d})`,
    dots: [KDJ_K_COLOR, KDJ_D_COLOR, KDJ_J_COLOR],
    paramDefs: [
      { field: "n", label: "周期" },
      { field: "k", label: "K平滑" },
      { field: "d", label: "D平滑" },
    ],
    guides: [20, 80],
    compute: (data, p) => {
      const r = kdj(
        data.map((d) => d.high),
        data.map((d) => d.low),
        data.map((d) => d.close),
        p.n,
        p.k,
        p.d,
      )
      return {
        series: [
          { kind: "line", color: KDJ_K_COLOR, data: toPts(data, r.k) },
          { kind: "line", color: KDJ_D_COLOR, data: toPts(data, r.d) },
          { kind: "line", color: KDJ_J_COLOR, data: toPts(data, r.j) },
        ],
        legend: (idx) => [
          { text: `KDJ(${p.n},${p.k},${p.d})`, color: LEGEND_NAME_COLOR },
          { text: `K ${fmt2(r.k[idx])}`, color: KDJ_K_COLOR },
          { text: `D ${fmt2(r.d[idx])}`, color: KDJ_D_COLOR },
          { text: `J ${fmt2(r.j[idx])}`, color: KDJ_J_COLOR },
        ],
      }
    },
  },
  {
    key: "stoch",
    scope: "sub",
    defaults: { kPeriod: 9, kSmooth: 3, dPeriod: 3 },
    label: (p) => `STOCH(${p.kPeriod},${p.kSmooth},${p.dPeriod})`,
    dots: [STOCH_K_COLOR, STOCH_D_COLOR],
    paramDefs: [
      { field: "kPeriod", label: "K周期" },
      { field: "kSmooth", label: "K平滑" },
      { field: "dPeriod", label: "D周期" },
    ],
    guides: [20, 80],
    compute: (data, p) => {
      const r = stochastic(
        data.map((d) => d.high),
        data.map((d) => d.low),
        data.map((d) => d.close),
        p.kPeriod,
        p.kSmooth,
        p.dPeriod,
      )
      return {
        series: [
          { kind: "line", color: STOCH_K_COLOR, fixedRange: [0, 100], data: toPts(data, r.k) },
          { kind: "line", color: STOCH_D_COLOR, fixedRange: [0, 100], data: toPts(data, r.d) },
        ],
        legend: (idx) => [
          { text: `STOCH(${p.kPeriod},${p.kSmooth},${p.dPeriod})`, color: LEGEND_NAME_COLOR },
          { text: `K ${fmt2(r.k[idx])}`, color: STOCH_K_COLOR },
          { text: `D ${fmt2(r.d[idx])}`, color: STOCH_D_COLOR },
        ],
      }
    },
  },
  {
    key: "wr",
    scope: "sub",
    defaults: { period: 14 },
    label: (p) => `WR(${p.period})`,
    dots: [WR_COLOR],
    paramDefs: [{ field: "period", label: "周期" }],
    guides: [-80, -20],
    compute: (data, p) => {
      const s = williamsR(
        data.map((d) => d.high),
        data.map((d) => d.low),
        data.map((d) => d.close),
        p.period,
      )
      return {
        series: [
          { kind: "line", color: WR_COLOR, width: 2, fixedRange: [-100, 0], data: toPts(data, s) },
        ],
        legend: (idx) => [
          { text: `WR(${p.period})`, color: LEGEND_NAME_COLOR },
          { text: fmt2(s[idx]), color: WR_COLOR },
        ],
      }
    },
  },
  {
    key: "cci",
    scope: "sub",
    defaults: { period: 14 },
    label: (p) => `CCI(${p.period})`,
    dots: [CCI_COLOR],
    paramDefs: [{ field: "period", label: "周期" }],
    guides: [100, -100],
    compute: (data, p) => {
      const s = cci(
        data.map((d) => d.high),
        data.map((d) => d.low),
        data.map((d) => d.close),
        p.period,
      )
      return {
        series: [{ kind: "line", color: CCI_COLOR, width: 2, data: toPts(data, s) }],
        legend: (idx) => [
          { text: `CCI(${p.period})`, color: LEGEND_NAME_COLOR },
          { text: fmt2(s[idx]), color: CCI_COLOR },
        ],
      }
    },
  },
  {
    key: "dmi",
    scope: "sub",
    defaults: { di: 14, adx: 14 },
    label: (p) => `DMI(${p.di},${p.adx})`,
    dots: [DMI_PLUS_COLOR, DMI_MINUS_COLOR, DMI_ADX_COLOR],
    paramDefs: [
      { field: "di", label: "DI周期" },
      { field: "adx", label: "ADX周期" },
    ],
    compute: (data, p) => {
      const r = dmi(
        data.map((d) => d.high),
        data.map((d) => d.low),
        data.map((d) => d.close),
        p.di,
        p.adx,
      )
      return {
        series: [
          { kind: "line", color: DMI_PLUS_COLOR, fixedRange: [0, 100], data: toPts(data, r.plus) },
          { kind: "line", color: DMI_MINUS_COLOR, fixedRange: [0, 100], data: toPts(data, r.minus) },
          { kind: "line", color: DMI_ADX_COLOR, width: 2, fixedRange: [0, 100], data: toPts(data, r.adx) },
        ],
        legend: (idx) => [
          { text: `DMI(${p.di},${p.adx})`, color: LEGEND_NAME_COLOR },
          { text: `+DI ${fmt2(r.plus[idx])}`, color: DMI_PLUS_COLOR },
          { text: `-DI ${fmt2(r.minus[idx])}`, color: DMI_MINUS_COLOR },
          { text: `ADX ${fmt2(r.adx[idx])}`, color: DMI_ADX_COLOR },
        ],
      }
    },
  },
  {
    key: "atr",
    scope: "sub",
    defaults: { period: 14 },
    label: (p) => `ATR(${p.period})`,
    dots: [ATR_COLOR],
    paramDefs: [{ field: "period", label: "周期" }],
    compute: (data, p) => {
      const s = atr(
        data.map((d) => d.high),
        data.map((d) => d.low),
        data.map((d) => d.close),
        p.period,
      )
      return {
        series: [{ kind: "line", color: ATR_COLOR, width: 2, data: toPts(data, s) }],
        legend: (idx) => [
          { text: `ATR(${p.period})`, color: LEGEND_NAME_COLOR },
          { text: fmtP(s[idx]), color: ATR_COLOR },
        ],
      }
    },
  },
  {
    key: "obv",
    scope: "sub",
    defaults: {},
    label: () => "OBV",
    dots: [OBV_COLOR],
    paramDefs: [],
    compute: (data) => {
      const s = obv(
        data.map((d) => d.close),
        data.map((d) => d.volume),
      )
      return {
        series: [{ kind: "line", color: OBV_COLOR, data: toPts(data, s) }],
        legend: (idx) => [
          { text: "OBV", color: LEGEND_NAME_COLOR },
          { text: compactFmt.format(s[idx] ?? 0), color: OBV_COLOR },
        ],
      }
    },
  },
  {
    key: "mfi",
    scope: "sub",
    defaults: { period: 14 },
    label: (p) => `MFI(${p.period})`,
    dots: [MFI_COLOR],
    paramDefs: [{ field: "period", label: "周期" }],
    guides: [20, 80],
    compute: (data, p) => {
      const s = mfi(
        data.map((d) => d.high),
        data.map((d) => d.low),
        data.map((d) => d.close),
        data.map((d) => d.volume),
        p.period,
      )
      return {
        series: [
          { kind: "line", color: MFI_COLOR, width: 2, fixedRange: [0, 100], data: toPts(data, s) },
        ],
        legend: (idx) => [
          { text: `MFI(${p.period})`, color: LEGEND_NAME_COLOR },
          { text: fmt2(s[idx]), color: MFI_COLOR },
        ],
      }
    },
  },
]

const OVERLAY_DEFS = INDICATORS.filter((d) => d.scope === "overlay")
const SUB_DEFS = INDICATORS.filter((d) => d.scope === "sub")

// ==================== 偏好持久化 ====================

const STORE_KEY = "quanforge.chart-indicators.v1"

interface Prefs {
  enabled: Record<string, boolean>
  params: Record<string, Record<string, number>>
}

function loadPrefs(): Prefs {
  let stored: Partial<Prefs> = {}
  try {
    stored = JSON.parse(localStorage.getItem(STORE_KEY) || "{}")
  } catch {
    // 损坏的存储忽略，回退默认
  }
  const enabled: Record<string, boolean> = {}
  const params: Record<string, Record<string, number>> = {}
  for (const d of INDICATORS) {
    enabled[d.key] = stored.enabled?.[d.key] ?? !!d.defaultOn
    params[d.key] = { ...d.defaults, ...(stored.params?.[d.key] || {}) }
  }
  return { enabled, params }
}

// ==================== 拉取 Bybit K线 ====================

async function fetchKlines(symbol: string, interval: string, limit: number): Promise<KlineItem[]> {
  const url = `/api/bybit/market?endpoint=/v5/market/kline&category=linear&symbol=${encodeURIComponent(
    symbol,
  )}&interval=${interval}&limit=${limit}`
  const res = await fetch(url)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const json = await res.json()
  if (json.retCode !== 0) throw new Error(json.retMsg || "Bybit 接口错误")
  const list: string[][] = json?.result?.list || []
  return list
    .slice()
    .sort((a, b) => Number(a[0]) - Number(b[0]))
    .map((k) => ({
      time: Math.floor(Number(k[0]) / 1000) as UTCTimestamp,
      open: Number(k[1]),
      high: Number(k[2]),
      low: Number(k[3]),
      close: Number(k[4]),
      volume: Number(k[5]) || 0,
    }))
}

// ==================== 小控件 ====================

function IndicatorChip({
  active,
  label,
  dots,
  onToggle,
  onOpenSettings,
  settings,
}: {
  active: boolean
  label: string
  dots: string[]
  onToggle: () => void
  onOpenSettings?: () => void
  settings?: ReactNode
}) {
  return (
    <div data-indicator-chip className="relative">
      <div
        className={`flex items-center rounded-lg text-xs font-medium transition-colors ${
          active ? "bg-zinc-800 text-zinc-100" : "text-zinc-500 hover:bg-zinc-800/60 hover:text-zinc-300"
        }`}
      >
        <button onClick={onToggle} className="flex items-center gap-1.5 py-1 pl-2 pr-1">
          {dots.map((c, i) => (
            <span
              key={`${c}-${i}`}
              className={`size-1.5 rounded-full ${active ? "" : "opacity-40"}`}
              style={{ background: c }}
            />
          ))}
          <span>{label}</span>
        </button>
        {onOpenSettings && (
          <button
            onClick={onOpenSettings}
            className={`rounded-md p-1 transition-colors ${
              active ? "hover:bg-zinc-700" : "hover:bg-zinc-700/60"
            }`}
            title="指标参数"
          >
            <Settings2 className="size-3" />
          </button>
        )}
      </div>
      {settings}
    </div>
  )
}

function ParamPopover({ children }: { children: ReactNode }) {
  return (
    <div className="absolute left-0 top-full z-30 mt-1.5 flex items-center gap-2.5 rounded-xl border border-zinc-700 bg-zinc-900 px-3 py-2 shadow-xl shadow-black/40">
      {children}
    </div>
  )
}

function Num({
  label,
  value,
  onChange,
  min = 1,
  max = 500,
  step = 1,
}: {
  label: string
  value: number
  onChange: (n: number) => void
  min?: number
  max?: number
  step?: number
}) {
  return (
    <label className="flex items-center gap-1.5">
      <span className="text-[11px] text-zinc-500">{label}</span>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(e) => {
          const n = Number(e.target.value)
          if (Number.isFinite(n) && n >= min && n <= max) onChange(n)
        }}
        className="w-14 rounded-md border border-zinc-700 bg-zinc-950 px-1.5 py-1 font-mono text-xs text-zinc-200 outline-none focus:border-zinc-500"
      />
    </label>
  )
}

// ==================== 主组件 ====================

// TSX 解析器会把函数体内 new Map<含字符串字面量的泛型>() 误判为比较表达式，
// 故统一抽成类型别名规避（见 git 历史：曾因此产生 TS2693/TS2348 级联错误）
type SeriesMap = Map<string, ISeriesApi<"Line"> | ISeriesApi<"Histogram">>
type CandleSeriesRef = ISeriesApi<"Candlestick"> | null
type VolumeSeriesRef = ISeriesApi<"Histogram"> | null

function KLineChart() {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleRef = useRef<CandleSeriesRef>(null)
  const volumeRef = useRef<VolumeSeriesRef>(null)
  /** 指标系列（不含 K 线与成交量） */
  const indicatorSeriesRef = useRef<SeriesMap>(new Map())
  const dataRef = useRef<KlineItem[]>([])
  const timeIdxRef = useRef(new Map<UTCTimestamp, number>())
  /** rebuild 后各启用指标的图例函数 */
  const legendFnsRef = useRef(new Map<string, (idx: number) => Seg[]>())

  const symbol = useTradeStore((s) => s.symbol)
  const [interval, setInterval] = useState("60")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [lastPrice, setLastPrice] = useState<number | null>(null)
  const [lastChange, setLastChange] = useState<number | null>(null)

  const [prefs, setPrefs] = useState<Prefs>(loadPrefs)
  const [openKey, setOpenKey] = useState<string | null>(null)
  const [legendIdx, setLegendIdx] = useState<number | null>(null)
  /** rebuild 后强制图例重渲染（legendIdx 不变时 React 会跳过渲染） */
  const [, setLegendTick] = useState(0)

  // 供图表回调读取最新偏好（避免闭包过期）
  const prefsRef = useRef(prefs)
  prefsRef.current = prefs
  const rebuildRef = useRef<() => void>(() => {})
  const loadRef = useRef<() => void>(() => {})

  // 初始化图表（仅一次）
  useEffect(() => {
    if (!containerRef.current) return
    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#a1a1aa",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "rgba(63,63,70,0.25)" },
        horzLines: { color: "rgba(63,63,70,0.25)" },
      },
      rightPriceScale: { borderColor: "rgba(63,63,70,0.4)" },
      timeScale: { borderColor: "rgba(63,63,70,0.4)", timeVisible: true, secondsVisible: false },
      crosshair: {
        mode: 0,
        vertLine: { color: "#52525b", labelBackgroundColor: "#3f3f46" },
        horzLine: { color: "#52525b", labelBackgroundColor: "#3f3f46" },
      },
      autoSize: true,
    })
    const candle = chart.addSeries(CandlestickSeries, {
      upColor: "#10b981",
      downColor: "#f43f5e",
      borderUpColor: "#10b981",
      borderDownColor: "#f43f5e",
      wickUpColor: "#10b981",
      wickDownColor: "#f43f5e",
    })
    const volume = chart.addSeries(HistogramSeries, {
      priceScaleId: "volume",
      priceFormat: { type: "volume" },
      lastValueVisible: false,
      priceLineVisible: false,
    })
    chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } })

    // 十字光标跟随：图例切换到悬停的 K 线
    chart.subscribeCrosshairMove((param) => {
      const data = dataRef.current
      if (!data.length) return
      const idx =
        param.time !== undefined ? timeIdxRef.current.get(param.time as UTCTimestamp) : undefined
      setLegendIdx(idx ?? data.length - 1)
    })

    chartRef.current = chart
    candleRef.current = candle
    volumeRef.current = volume
    return () => {
      chart.remove()
      chartRef.current = null
      candleRef.current = null
      volumeRef.current = null
      indicatorSeriesRef.current.clear()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 按当前开关与参数重建全部指标系列（K 线与成交量不动）
  rebuildRef.current = () => {
    const chart = chartRef.current
    if (!chart) return
    const data = dataRef.current

    // 先清空旧指标系列
    for (const s of indicatorSeriesRef.current.values()) {
      try {
        chart.removeSeries(s)
      } catch {
        // 系列已随窗格移除，忽略
      }
    }
    indicatorSeriesRef.current.clear()

    const legendFns = new Map<string, (idx: number) => Seg[]>()
    let pane = 1
    for (const def of INDICATORS) {
      if (!prefsRef.current.enabled[def.key]) continue
      const built = def.compute(data, prefsRef.current.params[def.key])
      const target = def.scope === "overlay" ? 0 : pane
      built.series.forEach((spec, si) => {
        const common = {
          priceLineVisible: false,
          lastValueVisible: false,
          ...(spec.fixedRange
            ? {
                autoscaleInfoProvider: () => ({
                  priceRange: { minValue: spec.fixedRange![0], maxValue: spec.fixedRange![1] },
                }),
              }
            : {}),
        }
        const series =
          spec.kind === "line"
            ? chart.addSeries(
                LineSeries,
                {
                  ...common,
                  color: spec.color,
                  lineWidth: spec.width ?? 1,
                  crosshairMarkerVisible: false,
                  ...(spec.pointsOnly
                    ? { lineVisible: false, pointMarkersVisible: true, pointMarkersRadius: 2 }
                    : {}),
                },
                target,
              )
            : chart.addSeries(HistogramSeries, common, target)
        series.setData(spec.data)
        indicatorSeriesRef.current.set(`${def.key}-${si}`, series)
        // 参考虚线画在该指标第一个系列上
        if (si === 0 && def.guides) {
          for (const g of def.guides) {
            series.createPriceLine({
              price: g,
              color: "#52525b",
              lineWidth: 1,
              lineStyle: LineStyle.Dashed,
              axisLabelVisible: false,
            })
          }
        }
      })
      legendFns.set(def.key, built.legend)
      if (def.scope === "sub") pane++
    }
    legendFnsRef.current = legendFns

    // 清掉多余空窗格；主图占大头（副图越多主图比例越小但保持 2:1）
    const subCount = pane - 1
    const expected = 1 + subCount
    while (chart.panes().length > expected) chart.removePane(chart.panes().length - 1)
    chart.panes().forEach((pn, i) => pn.setStretchFactor(i === 0 ? (subCount ? 2 : 1) : 1))

    if (data.length) {
      setLegendIdx(data.length - 1)
      setLegendTick((t) => t + 1)
    }
  }

  // 拉数据（symbol/interval 变化或手动刷新时触发）
  loadRef.current = async () => {
    if (!candleRef.current || !volumeRef.current) return
    setLoading(true)
    setError("")
    try {
      const data = await fetchKlines(symbol, interval, 300)
      if (!chartRef.current || !candleRef.current || !volumeRef.current) return
      dataRef.current = data
      timeIdxRef.current = new Map(data.map((d, i) => [d.time, i]))
      candleRef.current.setData(data)
      volumeRef.current.setData(
        data.map((k) => ({
          time: k.time,
          value: k.volume,
          color: k.close >= k.open ? "rgba(16,185,129,0.35)" : "rgba(244,63,94,0.35)",
        })),
      )
      const last = data[data.length - 1]
      if (last) {
        setLastPrice(last.close)
        const prev = data[data.length - 2]
        setLastChange(prev ? ((last.close - prev.close) / prev.close) * 100 : null)
      }
      rebuildRef.current()
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadRef.current()
    // 实时更新：每 15 秒刷新最后一根 K 线
    const timer = window.setInterval(() => loadRef.current(), 15000)
    return () => window.clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, interval])

  // 开关 / 参数变化 → 重建指标并持久化
  useEffect(() => {
    rebuildRef.current()
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify(prefs))
    } catch {
      // localStorage 不可用时静默忽略
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefs])

  // 点击指标条外部关闭参数弹层
  useEffect(() => {
    if (!openKey) return
    const close = (e: PointerEvent) => {
      const el = e.target as HTMLElement
      if (!el.closest?.("[data-indicator-chip]")) setOpenKey(null)
    }
    document.addEventListener("pointerdown", close)
    return () => document.removeEventListener("pointerdown", close)
  }, [openKey])

  const toggle = (k: string) =>
    setPrefs((p) => ({ ...p, enabled: { ...p.enabled, [k]: !p.enabled[k] } }))

  const setParam = (k: string, field: string, n: number) =>
    setPrefs((p) => ({
      ...p,
      params: { ...p.params, [k]: { ...p.params[k], [field]: n } },
    }))

  const up = (lastChange ?? 0) >= 0
  const subCount = SUB_DEFS.filter((d) => prefs.enabled[d.key]).length
  const chartHeight = Math.min(420 + 170 * subCount, 900)

  const renderChip = (def: IndicatorDef) => {
    const active = prefs.enabled[def.key]
    const params = prefs.params[def.key]
    return (
      <IndicatorChip
        key={def.key}
        active={active}
        label={def.label(params)}
        dots={def.dots}
        onToggle={() => toggle(def.key)}
        {...(def.paramDefs.length > 0
          ? {
              onOpenSettings: () => setOpenKey(openKey === def.key ? null : def.key),
              settings:
                openKey === def.key ? (
                  <ParamPopover>
                    {def.paramDefs.map((pd) => (
                      <Num
                        key={pd.field}
                        label={pd.label}
                        value={params[pd.field]}
                        min={pd.min ?? 1}
                        max={pd.max ?? 500}
                        step={pd.step ?? 1}
                        onChange={(n) => setParam(def.key, pd.field, n)}
                      />
                    ))}
                  </ParamPopover>
                ) : undefined,
            }
          : {})}
      />
    )
  }

  // ==================== 图例 ====================
  const renderLegend = () => {
    const data = dataRef.current
    if (legendIdx == null || !data[legendIdx]) return null
    const k = data[legendIdx]
    const upBar = k.close >= k.open
    const ohlcColor = upBar ? "text-emerald-400" : "text-rose-400"
    return (
      <div className="pointer-events-none absolute left-3 top-2 z-10 flex max-w-[95%] flex-wrap items-center gap-x-3 gap-y-0.5 font-mono text-[11px] leading-4">
        <span className="text-zinc-500">
          O <span className={ohlcColor}>{fmtP(k.open)}</span> H{" "}
          <span className={ohlcColor}>{fmtP(k.high)}</span> L{" "}
          <span className={ohlcColor}>{fmtP(k.low)}</span> C{" "}
          <span className={ohlcColor}>{fmtP(k.close)}</span>
        </span>
        {INDICATORS.filter((d) => legendFnsRef.current.has(d.key)).map((d) => {
          const segs = legendFnsRef.current.get(d.key)!(legendIdx)
          return (
            <span key={d.key} className="text-zinc-400">
              {segs.map((s, i) => (
                <Fragment key={i}>
                  {i > 0 && " "}
                  <span style={s.color ? { color: s.color } : undefined}>{s.text}</span>
                </Fragment>
              ))}
            </span>
          )
        })}
      </div>
    )
  }

  return (
    <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40">
      {/* 顶栏：品种 / 价格 / 周期 */}
      <div className="flex flex-wrap items-center gap-3 border-b border-zinc-800 px-4 py-3">
        <CandlestickChart className="size-4 text-zinc-400" />
        <div className="w-36">
          <SymbolSelect />
        </div>
        {lastPrice !== null && (
          <span className={`font-mono text-sm font-semibold ${up ? "text-emerald-400" : "text-rose-400"}`}>
            {lastPrice.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 6 })}
            {lastChange !== null && (
              <span className="ml-2 text-xs font-normal opacity-80">
                {up ? "+" : ""}
                {lastChange.toFixed(2)}%
              </span>
            )}
          </span>
        )}
        <div className="ml-auto flex items-center gap-1">
          {INTERVALS.map((it) => (
            <button
              key={it.value}
              onClick={() => setInterval(it.value)}
              className={`rounded-lg px-2 py-1 text-xs font-medium transition-colors ${
                interval === it.value
                  ? "bg-zinc-100 text-zinc-900"
                  : "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
              }`}
            >
              {it.label}
            </button>
          ))}
          <button
            onClick={() => loadRef.current()}
            className="ml-2 rounded-lg p-1.5 text-zinc-400 transition-colors hover:bg-zinc-800 hover:text-zinc-200"
            title="刷新"
          >
            <RefreshCw className={`size-4 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {/* 指标开关条 */}
      <div className="flex flex-wrap items-center gap-1 border-b border-zinc-800 px-4 py-2">
        <span className="mr-1 text-[11px] font-medium text-zinc-600">主图</span>
        {OVERLAY_DEFS.map(renderChip)}
        <div className="mx-1 h-4 w-px bg-zinc-800" />
        <span className="mr-1 text-[11px] font-medium text-zinc-600">副图</span>
        {SUB_DEFS.map(renderChip)}
      </div>

      <div className="relative">
        <div
          ref={containerRef}
          data-chart-container=""
          className="w-full transition-[height] duration-200"
          style={{ height: chartHeight }}
        />
        {renderLegend()}
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-zinc-950/50 backdrop-blur-sm">
            <Loader2 className="size-6 animate-spin text-zinc-500" />
          </div>
        )}
        {error && (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-2 text-sm text-rose-400">
              {error}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default KLineChart
