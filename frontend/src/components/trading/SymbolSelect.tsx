import { useEffect, useRef, useState } from "react"
import { ChevronsUpDown, Loader2, Search } from "lucide-react"
import { useTradeStore } from "../../store/tradeStore"

const POPULAR = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT"]

// 拉取 USDT 永续合约列表（instruments-info）
async function fetchSymbols(): Promise<string[]> {
  const res = await fetch("/api/bybit/market?endpoint=/v5/market/instruments-info&category=linear&limit=1000")
  const json = await res.json()
  const list: { symbol: string }[] = json?.result?.list ?? []
  return list
    .filter((it) => it.symbol.endsWith("USDT"))
    .map((it) => it.symbol)
    .sort()
}

function SymbolSelect() {
  const symbol = useTradeStore((s) => s.symbol)
  const setSymbol = useTradeStore((s) => s.setSymbol)
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const [all, setAll] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const boxRef = useRef<HTMLDivElement>(null)

  // 首次打开时拉合约列表
  useEffect(() => {
    if (open && all.length === 0) {
      setLoading(true)
      fetchSymbols()
        .then(setAll)
        .catch(() => setAll(POPULAR))
        .finally(() => setLoading(false))
    }
  }, [open, all.length])

  // 点击外部关闭
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", onDown)
    return () => document.removeEventListener("mousedown", onDown)
  }, [open])

  const q = query.trim().toUpperCase()
  const filtered = q
    ? all.filter((s) => s.includes(q))
    : [...POPULAR.filter((s) => all.includes(s)), ...all.filter((s) => !POPULAR.includes(s))]

  const select = (s: string) => {
    setSymbol(s)
    setOpen(false)
    setQuery("")
  }

  return (
    <div ref={boxRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between gap-2 rounded-xl border border-zinc-800 bg-zinc-950/60 px-3 py-2 font-mono text-sm text-zinc-200 outline-none focus:border-zinc-600"
      >
        <span>{symbol}</span>
        <ChevronsUpDown className="size-3.5 shrink-0 text-zinc-500" />
      </button>

      {open && (
        <div className="absolute left-0 top-full z-40 mt-1 w-full overflow-hidden rounded-xl border border-zinc-800 bg-zinc-950 shadow-2xl shadow-black/50">
          <div className="flex items-center gap-2 border-b border-zinc-800 px-3 py-2">
            <Search className="size-3.5 shrink-0 text-zinc-500" />
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value.toUpperCase())}
              placeholder="搜索合约..."
              className="w-full bg-transparent font-mono text-xs text-zinc-200 outline-none placeholder:text-zinc-600"
            />
          </div>
          <div className="max-h-64 overflow-y-auto py-1">
            {loading && (
              <div className="flex items-center justify-center gap-2 py-4 text-xs text-zinc-500">
                <Loader2 className="size-3.5 animate-spin" /> 加载合约列表...
              </div>
            )}
            {!loading && filtered.length === 0 && (
              <div className="py-4 text-center text-xs text-zinc-600">未找到合约 {q}</div>
            )}
            {filtered.slice(0, 30).map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => select(s)}
                className={`flex w-full items-center justify-between px-3 py-1.5 font-mono text-xs transition-colors hover:bg-zinc-800/70 ${
                  s === symbol ? "text-emerald-400" : "text-zinc-300"
                }`}
              >
                <span>{s}</span>
                {s === symbol && <span className="text-[10px] text-emerald-500">当前</span>}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default SymbolSelect
