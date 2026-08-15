import { useCallback, useEffect, useRef, useState } from "react"
import { Newspaper, RefreshCw, ExternalLink, Loader2 } from "lucide-react"

interface NewsItem {
  source: string
  title: string
  content: string
  url: string
  publishedAt: number
}

const SOURCES = [
  { key: "all", label: "全部" },
  { key: "华尔街见闻", label: "要闻" },
  { key: "Binance", label: "Binance" },
  { key: "CoinDesk", label: "CoinDesk" },
  { key: "Cointelegraph", label: "CT" },
]

/** 源标签配色 */
function sourceStyle(source: string): string {
  switch (source) {
    case "华尔街见闻":
      return "bg-sky-500/15 text-sky-400 ring-sky-500/30"
    case "Binance":
      return "bg-amber-500/15 text-amber-400 ring-amber-500/30"
    case "CoinDesk":
      return "bg-indigo-500/15 text-indigo-400 ring-indigo-500/30"
    case "Cointelegraph":
      return "bg-violet-500/15 text-violet-400 ring-violet-500/30"
    default:
      return "bg-zinc-500/15 text-zinc-400 ring-zinc-500/30"
  }
}

function timeAgo(ts: number): string {
  if (!ts) return ""
  const diff = Date.now() - ts
  if (diff < 0) return "刚刚"
  const min = Math.floor(diff / 60_000)
  if (min < 1) return "刚刚"
  if (min < 60) return `${min} 分钟前`
  const h = Math.floor(min / 60)
  if (h < 24) return `${h} 小时前`
  return `${Math.floor(h / 24)} 天前`
}

/**
 * 快讯流（全宽页面版）：四源聚合、时间倒序、源筛选、关键词过滤、30 秒轮询。
 */
function NewsFeed() {
  const [items, setItems] = useState<NewsItem[]>([])
  const [source, setSource] = useState("all")
  const [keyword, setKeyword] = useState("")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [lastRefreshAt, setLastRefreshAt] = useState(0)
  const sourceRef = useRef(source)
  sourceRef.current = source

  const load = useCallback(async () => {
    try {
      const res = await fetch(`/api/news?limit=100&source=${encodeURIComponent(sourceRef.current)}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setItems(json.items || [])
      setLastRefreshAt(json.lastRefreshAt || 0)
      setError("")
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    setLoading(true)
    load()
    const timer = window.setInterval(load, 30_000)
    return () => window.clearInterval(timer)
  }, [source, load])

  const kw = keyword.trim().toLowerCase()
  const filtered = kw
    ? items.filter(
        (i) => i.title.toLowerCase().includes(kw) || i.content.toLowerCase().includes(kw),
      )
    : items

  return (
    <div className="flex min-h-0 flex-1 flex-col rounded-2xl border border-zinc-800 bg-zinc-900/40">
      <div className="flex flex-wrap items-center gap-2 border-b border-zinc-800 px-4 py-3">
        <Newspaper className="size-4 text-zinc-400" />
        <span className="text-sm font-semibold">快讯</span>
        {lastRefreshAt > 0 && (
          <span className="text-[11px] text-zinc-600">更新于 {timeAgo(lastRefreshAt)}</span>
        )}
        <input
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          placeholder="关键词过滤..."
          className="ml-auto w-40 rounded-lg border border-zinc-800 bg-zinc-950/60 px-2.5 py-1.5 text-xs text-zinc-200 outline-none placeholder:text-zinc-600 focus:border-zinc-600"
        />
        <button
          onClick={load}
          className="rounded-lg p-1.5 text-zinc-400 transition-colors hover:bg-zinc-800 hover:text-zinc-200"
          title="刷新"
        >
          <RefreshCw className={`size-3.5 ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>

      <div className="flex items-center gap-1 border-b border-zinc-800 px-3 py-2">
        {SOURCES.map((s) => (
          <button
            key={s.key}
            onClick={() => setSource(s.key)}
            className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
              source === s.key
                ? "bg-zinc-100 text-zinc-900"
                : "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
            }`}
          >
            {s.label}
          </button>
        ))}
        <span className="ml-auto text-[11px] text-zinc-600">{filtered.length} 条</span>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {error && <div className="px-3 py-2 text-xs text-rose-400">{error}</div>}
        {!error && filtered.length === 0 && loading && (
          <div className="flex items-center justify-center gap-2 py-10 text-sm text-zinc-500">
            <Loader2 className="size-4 animate-spin" /> 拉取快讯中...
          </div>
        )}
        <div className="space-y-1.5">
          {filtered.map((item) => (
            <a
              key={item.url}
              href={item.url}
              target="_blank"
              rel="noreferrer"
              className="group flex items-start gap-3 rounded-xl border border-zinc-800/60 bg-zinc-950/30 px-3.5 py-3 transition-colors hover:border-zinc-700 hover:bg-zinc-800/30"
            >
              <div className="min-w-0 grow">
                <div className="flex items-center gap-2">
                  <span
                    className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ring-1 ring-inset ${sourceStyle(item.source)}`}
                  >
                    {item.source}
                  </span>
                  <span className="text-[11px] text-zinc-500">{timeAgo(item.publishedAt)}</span>
                  <ExternalLink className="ml-auto size-3 shrink-0 text-zinc-600 opacity-0 transition-opacity group-hover:opacity-100" />
                </div>
                <p className="mt-1.5 text-[13px] font-medium leading-snug text-zinc-100">
                  {item.title}
                </p>
                {item.content && item.content !== item.title && (
                  <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-zinc-500">
                    {item.content}
                  </p>
                )}
              </div>
            </a>
          ))}
        </div>
      </div>
    </div>
  )
}

export default NewsFeed
