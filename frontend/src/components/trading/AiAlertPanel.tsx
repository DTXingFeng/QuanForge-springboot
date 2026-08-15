import { useCallback, useEffect, useState } from "react"
import { Bot, Loader2, Sparkles, AlertTriangle, Info, ShieldAlert, RefreshCw, Activity, Target } from "lucide-react"
import { useTradeStore } from "../../store/tradeStore"
import { KpiRow, AiStatusCard } from "../ui/kpi-cards"

interface AiAlert {
  id: number
  symbol: string
  level: "INFO" | "WARN" | "CRITICAL"
  title: string
  summary: string
  detail: string
  trigger: string
  confidence: number | null
  createdAt: string
}

interface AdviceTrack {
  id: number
  symbol: string
  action: "BUY" | "SELL"
  entry: number
  status: "PENDING" | "TRACKING" | "WIN" | "LOSS" | "EXPIRED"
  resultPct: number | null
  note: string | null
  createdAt: string
}

interface TrackStats {
  wins: number
  losses: number
  expired: number
  active: number
  winRate: number | null
  avgResultPct: number | null
}

const TRACK_STYLE: Record<string, { text: string; label: string }> = {
  PENDING: { text: "text-zinc-400", label: "等入场" },
  TRACKING: { text: "text-sky-400", label: "持仓中" },
  WIN: { text: "text-emerald-400", label: "盈" },
  LOSS: { text: "text-rose-400", label: "损" },
  EXPIRED: { text: "text-zinc-500", label: "过期" },
}

interface AiConfigInfo {
  enabled: boolean
  model: string
  watchSymbols: string
  scanIntervalMinutes: number
}

const LEVEL_STYLE: Record<string, { badge: string; icon: typeof Info; label: string }> = {
  INFO: { badge: "bg-sky-500/15 text-sky-400 ring-sky-500/30", icon: Info, label: "关注" },
  WARN: { badge: "bg-amber-500/15 text-amber-400 ring-amber-500/30", icon: AlertTriangle, label: "预警" },
  CRITICAL: { badge: "bg-rose-500/15 text-rose-400 ring-rose-500/30", icon: ShieldAlert, label: "紧急" },
}

function fmtTime(iso: string): string {
  const d = new Date(iso)
  const diff = Date.now() - d.getTime()
  const min = Math.floor(diff / 60_000)
  if (min < 1) return "刚刚"
  if (min < 60) return `${min} 分钟前`
  const h = Math.floor(min / 60)
  if (h < 24) return `${h} 小时前`
  return d.toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" })
}

/** 从 detail 首行解析「参考建议」价位 */
function parseAdvice(detail: string): { action: string; entry: string; sl: string; tp: string } | null {
  const m = detail.match(/参考建议：(BUY|SELL) 入场 ([\d.]+)｜止损 ([\d.]+)｜止盈 ([\d.]+)/)
  if (!m) return null
  return { action: m[1], entry: m[2], sl: m[3], tp: m[4] }
}

/**
 * AI 盯盘面板（全宽页面版）：KPI 统计 + 状态卡 + 告警卡片流 + 手动分析。
 */
function AiAlertPanel() {
  const symbol = useTradeStore((s) => s.symbol)
  const [alerts, setAlerts] = useState<AiAlert[]>([])
  const [tracks, setTracks] = useState<AdviceTrack[]>([])
  const [trackStats, setTrackStats] = useState<TrackStats | null>(null)
  const [config, setConfig] = useState<AiConfigInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [analyzing, setAnalyzing] = useState(false)
  const [analyzeMsg, setAnalyzeMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [levelFilter, setLevelFilter] = useState<"all" | "INFO" | "WARN" | "CRITICAL">("all")

  const load = useCallback(async () => {
    try {
      const [alertsRes, configRes, tracksRes, statsRes] = await Promise.all([
        fetch("/api/ai/alerts?limit=50"),
        fetch("/api/ai/config"),
        fetch("/api/ai/tracks?limit=6"),
        fetch("/api/ai/tracks/stats"),
      ])
      if (alertsRes.ok) setAlerts(await alertsRes.json())
      if (configRes.ok) setConfig(await configRes.json())
      if (tracksRes.ok) setTracks(await tracksRes.json())
      if (statsRes.ok) setTrackStats(await statsRes.json())
    } catch {
      // 静默
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const timer = window.setInterval(load, 30_000)
    return () => window.clearInterval(timer)
  }, [load])

  const analyze = async () => {
    setAnalyzing(true)
    setAnalyzeMsg(null)
    try {
      const res = await fetch(`/api/ai/analyze?symbol=${encodeURIComponent(symbol)}`, {
        method: "POST",
      })
      const json = await res.json().catch(() => null)
      if (!res.ok) {
        const msg =
          (json && (json.message || json.detail)) ||
          (res.status === 400 ? "AI 未配置，请到设置页填写 API Key" : `分析失败 HTTP ${res.status}`)
        setAnalyzeMsg({ ok: false, text: msg })
      } else if (json && json.ok === false) {
        setAnalyzeMsg({ ok: false, text: json.message || "数据不足" })
      } else if (json) {
        setAnalyzeMsg({ ok: true, text: `研判完成：${json.title || symbol}` })
        load()
      } else {
        setAnalyzeMsg({ ok: false, text: "响应异常" })
      }
    } catch (e) {
      setAnalyzeMsg({ ok: false, text: e instanceof Error ? e.message : "网络错误" })
    } finally {
      setAnalyzing(false)
    }
  }

  // KPI 统计
  const today = new Date().toDateString()
  const todayAlerts = alerts.filter((a) => new Date(a.createdAt).toDateString() === today)
  const critical = alerts.filter((a) => a.level === "CRITICAL").length
  const warn = alerts.filter((a) => a.level === "WARN").length
  const avgConf = alerts.length
    ? Math.round(alerts.reduce((s, a) => s + (a.confidence ?? 0), 0) / alerts.length)
    : 0

  const shown = levelFilter === "all" ? alerts : alerts.filter((a) => a.level === levelFilter)

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      <KpiRow
        items={[
          { label: "今日研判", value: String(todayAlerts.length), tone: "text-zinc-100", hint: `历史 ${alerts.length} 条` },
          { label: "紧急告警", value: String(critical), tone: critical ? "text-rose-400" : "text-zinc-400" },
          { label: "预警", value: String(warn), tone: warn ? "text-amber-400" : "text-zinc-400" },
          { label: "平均置信度", value: avgConf ? `${avgConf}%` : "-", tone: "text-indigo-300" },
        ]}
      />

      {trackStats && (trackStats.wins + trackStats.losses + trackStats.active > 0) && (
        <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4">
          <div className="flex items-center gap-2">
            <Target className="size-4 text-emerald-400" />
            <span className="text-sm font-semibold">纸面战绩</span>
            <span className="text-[11px] text-zinc-500">
              （AI 带价位建议的自动跟踪，非真实下单；同根K线双触发保守判损）
            </span>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-x-8 gap-y-3">
            <div className="flex items-baseline gap-2">
              <span className="text-3xl font-bold tabular-nums text-zinc-100">
                {trackStats.winRate != null ? `${trackStats.winRate}%` : "-"}
              </span>
              <span className="text-xs text-zinc-500">胜率</span>
            </div>
            <div className="flex items-center gap-3 text-xs">
              <span className="text-emerald-400">盈 {trackStats.wins}</span>
              <span className="text-rose-400">损 {trackStats.losses}</span>
              <span className="text-sky-400">进行中 {trackStats.active}</span>
              <span className="text-zinc-500">过期 {trackStats.expired}</span>
              {trackStats.avgResultPct != null && (
                <span className={trackStats.avgResultPct >= 0 ? "text-emerald-300" : "text-rose-300"}>
                  均幅 {trackStats.avgResultPct >= 0 ? "+" : ""}{trackStats.avgResultPct}%
                </span>
              )}
            </div>
          </div>
          {tracks.length > 0 && (
            <div className="mt-3 space-y-1 border-t border-zinc-800/60 pt-3">
              {tracks.map((t) => {
                const st = TRACK_STYLE[t.status] || TRACK_STYLE.PENDING
                return (
                  <div key={t.id} className="flex items-center gap-2 text-[11px]">
                    <span className={`font-semibold ${t.action === "BUY" ? "text-emerald-400" : "text-rose-400"}`}>
                      {t.action === "BUY" ? "多" : "空"}
                    </span>
                    <span className="font-mono text-zinc-300">{t.symbol}</span>
                    <span className="font-mono text-zinc-500">@{t.entry}</span>
                    <span className={`ml-auto font-medium ${st.text}`}>
                      {st.label}
                      {t.resultPct != null && (
                        <span className="ml-1 font-mono">
                          {t.resultPct >= 0 ? "+" : ""}{t.resultPct}%
                        </span>
                      )}
                    </span>
                    <span className="w-20 text-right text-zinc-600">{fmtTime(t.createdAt)}</span>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}

      {config && (
        <div className="flex flex-wrap items-stretch gap-4">
          <AiStatusCard
            className="min-w-56 grow"
            enabled={config.enabled}
            modelName={config.model}
            watchSymbols={config.watchSymbols}
            scanInterval={config.scanIntervalMinutes}
          />
          <div className="flex items-center gap-2">
            <button
              onClick={analyze}
              disabled={analyzing}
              className="flex items-center gap-1.5 rounded-xl bg-indigo-500/15 px-4 py-2.5 text-sm font-medium text-indigo-300 ring-1 ring-inset ring-indigo-500/30 transition-colors hover:bg-indigo-500/25 disabled:opacity-50"
              title={`对 ${symbol} 手动触发一次 AI 研判`}
            >
              {analyzing ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" />}
              {analyzing ? "分析中（AI 自主收集数据，约 1-2 分钟）" : `分析 ${symbol}`}
            </button>
            <button
              onClick={load}
              className="rounded-xl p-2 text-zinc-400 transition-colors hover:bg-zinc-800 hover:text-zinc-200"
              title="刷新"
            >
              <RefreshCw className={`size-4 ${loading ? "animate-spin" : ""}`} />
            </button>
          </div>
        </div>
      )}

      {analyzeMsg && (
        <div
          className={`rounded-xl border px-4 py-2.5 text-xs ${
            analyzeMsg.ok
              ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
              : "border-rose-500/30 bg-rose-500/10 text-rose-400"
          }`}
        >
          {analyzeMsg.text}
        </div>
      )}

      <div className="flex min-h-0 flex-1 flex-col rounded-2xl border border-zinc-800 bg-zinc-900/40">
        <div className="flex items-center gap-2 border-b border-zinc-800 px-4 py-3">
          <Activity className="size-4 text-indigo-400" />
          <span className="text-sm font-semibold">研判记录</span>
          <div className="ml-auto flex items-center gap-1">
            {(["all", "INFO", "WARN", "CRITICAL"] as const).map((lv) => (
              <button
                key={lv}
                onClick={() => setLevelFilter(lv)}
                className={`rounded-lg px-2 py-1 text-[11px] font-medium transition-colors ${
                  levelFilter === lv
                    ? "bg-zinc-100 text-zinc-900"
                    : "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
                }`}
              >
                {lv === "all" ? "全部" : LEVEL_STYLE[lv].label}
              </button>
            ))}
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-3">
          {shown.length === 0 && !loading && (
            <div className="px-4 py-10 text-center text-xs leading-relaxed text-zinc-500">
              <Bot className="mx-auto mb-2 size-8 text-zinc-700" />
              暂无研判记录。
              <br />
              开启自动盯盘后异动会自动出现在这里，也可点上方按钮手动分析。
            </div>
          )}
          <div className="space-y-2">
            {shown.map((a) => {
              const style = LEVEL_STYLE[a.level] || LEVEL_STYLE.INFO
              const LevelIcon = style.icon
              const expanded = expandedId === a.id
              const advice = parseAdvice(a.detail)
              return (
                <div
                  key={a.id}
                  className="rounded-xl border border-zinc-800/60 bg-zinc-950/30 transition-colors hover:border-zinc-700"
                >
                  <button
                    className="w-full px-4 py-3 text-left"
                    onClick={() => setExpandedId(expanded ? null : a.id)}
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className={`flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium ring-1 ring-inset ${style.badge}`}
                      >
                        <LevelIcon className="size-3" />
                        {style.label}
                      </span>
                      <span className="font-mono text-xs font-semibold text-zinc-200">
                        {a.symbol}
                      </span>
                      <span className="ml-auto text-[11px] text-zinc-500">
                        {fmtTime(a.createdAt)}
                      </span>
                    </div>
                    <p className="mt-2 text-[13px] font-medium leading-snug text-zinc-100">
                      {a.title}
                    </p>
                    <p className="mt-1 text-xs leading-relaxed text-zinc-400">{a.summary}</p>
                  </button>
                  {expanded && (
                    <div className="space-y-3 border-t border-zinc-800/60 px-4 py-3">
                      {advice && (
                        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg bg-zinc-900/60 px-3 py-2 font-mono text-xs">
                          <span
                            className={
                              advice.action === "BUY" ? "text-emerald-400" : "text-rose-400"
                            }
                          >
                            {advice.action === "BUY" ? "做多" : "做空"}
                          </span>
                          <span className="text-zinc-500">
                            入场 <span className="text-zinc-200">{advice.entry}</span>
                          </span>
                          <span className="text-zinc-500">
                            止损 <span className="text-rose-300">{advice.sl}</span>
                          </span>
                          <span className="text-zinc-500">
                            止盈 <span className="text-emerald-300">{advice.tp}</span>
                          </span>
                          <span className="ml-auto text-[10px] text-zinc-600">仅供参考，非投资建议</span>
                        </div>
                      )}
                      {a.confidence != null && (
                        <div className="flex items-center gap-2 text-[11px] text-zinc-500">
                          <span>置信度</span>
                          <div className="h-1 w-28 overflow-hidden rounded-full bg-zinc-800">
                            <div
                              className="h-full rounded-full bg-indigo-400"
                              style={{ width: `${a.confidence}%` }}
                            />
                          </div>
                          <span className="font-mono text-zinc-400">{a.confidence}%</span>
                        </div>
                      )}
                      <p className="whitespace-pre-wrap text-xs leading-relaxed text-zinc-300">
                        {a.detail}
                      </p>
                      <p className="text-[11px] text-zinc-600">触发：{a.trigger}</p>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}

export default AiAlertPanel
