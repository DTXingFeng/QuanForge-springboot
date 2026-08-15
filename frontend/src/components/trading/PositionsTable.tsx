import { useEffect, useState } from "react"
import { Loader2, RefreshCw, Layers, X, Crosshair } from "lucide-react"
import { toast } from "sonner"
import { useTradeStore } from "../../store/tradeStore"

interface Position {
  symbol: string
  side: string
  size: string
  avgPrice: string
  liqPrice: string
  breakEvenPrice: string
  markPrice: string
  unrealisedPnl: string
  curRealisedPnl: string
  positionValue: string
  leverage: string
  positionIM: string
  positionMM: string
  positionIdx: string
  tpslMode?: string
  takeProfit?: string
  stopLoss?: string
  trailingStop?: string
}

// 拉取持仓列表
async function fetchPositions(name: string): Promise<Position[]> {
  const url = `/api/bybit/get?name=${encodeURIComponent(name)}&endpoint=/v5/position/list&category=linear&settleCoin=USDT`
  const res = await fetch(url)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const json = await res.json()
  if (json.retCode !== 0) throw new Error(json.retMsg || "Bybit 接口错误")
  const list: any[] = json?.result?.list || []
  return list
    .filter((p) => Number(p.size) !== 0)
    .map((p) => ({
      symbol: p.symbol,
      side: p.side,
      size: p.size,
      avgPrice: p.avgPrice,
      liqPrice: p.liqPrice,
      breakEvenPrice: p.breakEvenPrice,
      markPrice: p.markPrice,
      unrealisedPnl: p.unrealisedPnl,
      curRealisedPnl: p.curRealisedPnl,
      positionValue: p.positionValue,
      leverage: p.leverage,
      positionIM: p.positionIM,
      positionMM: p.positionMM,
      positionIdx: p.positionIdx,
      tpslMode: p.tpslMode,
      takeProfit: p.takeProfit,
      stopLoss: p.stopLoss,
      trailingStop: p.trailingStop,
    }))
}

// 市价反向单平仓
async function closePosition(name: string, p: Position): Promise<{ retCode: number; retMsg: string; orderId?: string }> {
  const res = await fetch(`/api/bybit/create-order?name=${encodeURIComponent(name)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      category: "linear",
      symbol: p.symbol,
      side: p.side === "Buy" ? "Sell" : "Buy",
      orderType: "Market",
      qty: p.size,
      positionIdx: String(p.positionIdx),
      timeInForce: "IOC",
      reduceOnly: true,
    }),
  })
  return await res.json()
}

// 设置止盈止损（trading-stop）
async function setTradingStop(name: string, p: Position, body: Record<string, string>): Promise<{ retCode: number; retMsg: string }> {
  const res = await fetch(`/api/bybit/trading-stop?name=${encodeURIComponent(name)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      category: "linear",
      symbol: p.symbol,
      tpslMode: body.tpslMode || "Full",
      positionIdx: p.positionIdx || "0",
      ...body,
    }),
  })
  return await res.json()
}

function PositionsTable() {
  const [positions, setPositions] = useState<Position[]>([])
  const [loading, setLoading] = useState(true)
  const [closing, setClosing] = useState("")
  const [error, setError] = useState("")
  const positionsRefreshKey = useTradeStore((s) => s.positionsRefreshKey)
  const bumpPositionsRefresh = useTradeStore((s) => s.bumpPositionsRefresh)
  const credentialName = useTradeStore((s) => s.credentialName)

  // 止盈止损弹窗
  const [tpslTarget, setTpslTarget] = useState<Position | null>(null)
  const [tpMode, setTpMode] = useState("Full")
  const [tpValue, setTpValue] = useState("")
  const [slValue, setSlValue] = useState("")
  const [tsValue, setTsValue] = useState("")
  const [tpSaving, setTpSaving] = useState(false)

  const openTpsl = (p: Position) => {
    setTpslTarget(p)
    setTpMode(p.tpslMode || "Full")
    setTpValue(p.takeProfit && Number(p.takeProfit) !== 0 ? p.takeProfit : "")
    setSlValue(p.stopLoss && Number(p.stopLoss) !== 0 ? p.stopLoss : "")
    setTsValue(p.trailingStop && Number(p.trailingStop) !== 0 ? p.trailingStop : "")
  }

  const handleSaveTpsl = async () => {
    if (!tpslTarget) return
    const body: Record<string, string> = { tpslMode: tpMode }
    // 空值=不变，填 0=取消；追踪止损同理
    if (tpValue.trim() !== "") body.takeProfit = tpValue.trim()
    if (slValue.trim() !== "") body.stopLoss = slValue.trim()
    if (tsValue.trim() !== "") body.trailingStop = tsValue.trim()
    setTpSaving(true)
    const r = await setTradingStop(credentialName, tpslTarget, body)
    setTpSaving(false)
    if (r.retCode === 0) {
      toast.success(`${tpslTarget.symbol} 止盈止损已更新`)
      setTpslTarget(null)
      bumpPositionsRefresh()
    } else {
      toast.error(`设置失败（${r.retCode}）: ${r.retMsg}`, { duration: 8000 })
    }
  }

  const load = async () => {
    try {
      const data = await fetchPositions(credentialName)
      setPositions(data)
      setError("")
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    const timer = setInterval(load, 10000)
    return () => clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [credentialName])

  // 开仓/平仓后自动刷新
  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [positionsRefreshKey])

  const handleClose = async (p: Position) => {
    const key = `${p.symbol}-${p.positionIdx}`
    if (!window.confirm(`确认市价平仓 ${p.symbol} ${p.side === "Buy" ? "多" : "空"} ${p.size} ?`)) return
    setClosing(key)
    try {
      const r = await closePosition(credentialName, p)
      if (r.retCode === 0) {
        toast.success(`${p.symbol} 平仓成功 orderId: ${r.orderId}`)
        bumpPositionsRefresh()
      } else {
        toast.error(`平仓失败（${r.retCode}）: ${r.retMsg}`)
      }
    } catch {
      toast.error("平仓请求失败，请检查后端")
    } finally {
      setClosing("")
    }
  }

  const formatNum = (v: string | undefined, digits = 2): string => {
    if (!v || v === "0") return "0"
    const n = Number(v)
    return n.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: digits })
  }

  const formatPrice = (v: string | undefined, digits = 2): string => {
    if (!v) return "-"
    const n = Number(v)
    if (n === 0) return "-"
    return n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })
  }

  // ROI = 未实现盈亏 / 保证金（positionValue / leverage）
  const roiOf = (p: Position): string => {
    const pnl = Number(p.unrealisedPnl) || 0
    const val = Number(p.positionValue) || 0
    const lev = Number(p.leverage) || 1
    const margin = val / lev
    if (!margin) return "0.00%"
    return `${((pnl / margin) * 100).toFixed(2)}%`
  }

  return (
    <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40">
      <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
        <div className="flex items-center gap-2">
          <Layers className="size-4 text-zinc-400" />
          <h2 className="text-sm font-semibold text-zinc-200">当前持仓</h2>
          <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-[11px] text-zinc-400">{positions.length}</span>
        </div>
        <button
          onClick={load}
          className="rounded-lg p-1.5 text-zinc-400 transition-colors hover:bg-zinc-800 hover:text-zinc-200"
          title="刷新"
        >
          <RefreshCw className={`size-4 ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full whitespace-nowrap text-xs">
          <thead>
            <tr className="border-b border-zinc-800 text-left text-zinc-500">
              <th className="px-3 py-2.5 font-medium">合约</th>
              <th className="px-3 py-2.5 font-medium">方向</th>
              <th className="px-3 py-2.5 font-medium text-right">合约数量</th>
              <th className="px-3 py-2.5 font-medium text-right">价值</th>
              <th className="px-3 py-2.5 font-medium text-right">入场价格</th>
              <th className="px-3 py-2.5 font-medium text-right">标记价格</th>
              <th className="px-3 py-2.5 font-medium text-right">预估强平价</th>
              <th className="px-3 py-2.5 font-medium text-right">盈亏平衡价</th>
              <th className="px-3 py-2.5 font-medium text-right">IM</th>
              <th className="px-3 py-2.5 font-medium text-right">MM</th>
              <th className="px-3 py-2.5 font-medium text-right">未结盈亏 (ROI)</th>
              <th className="px-3 py-2.5 font-medium text-right">已结盈亏</th>
              <th className="px-3 py-2.5 font-medium text-right">止盈/止损</th>
              <th className="px-3 py-2.5 font-medium text-right">追踪出场</th>
              <th className="px-3 py-2.5 font-medium text-center">操作</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => {
              const pnl = Number(p.unrealisedPnl) || 0
              const up = pnl >= 0
              const closingKey = `${p.symbol}-${p.positionIdx}`
              const tp = p.takeProfit || ""
              const sl = p.stopLoss || ""
              return (
                <tr
                  key={closingKey}
                  className="border-b border-zinc-800/50 text-zinc-300 transition-colors hover:bg-zinc-800/30"
                >
                  <td className="px-3 py-2.5 font-mono text-zinc-200">{p.symbol}</td>
                  <td className="px-3 py-2.5">
                    <span
                      className={`inline-flex rounded-md px-2 py-0.5 text-xs font-semibold ${
                        p.side === "Buy" ? "bg-emerald-500/15 text-emerald-400" : "bg-rose-500/15 text-rose-400"
                      }`}
                    >
                      {p.side === "Buy" ? "多" : "空"}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono">{formatNum(p.size, 4)}</td>
                  <td className="px-3 py-2.5 text-right font-mono">{formatNum(p.positionValue, 2)}</td>
                  <td className="px-3 py-2.5 text-right font-mono">{formatPrice(p.avgPrice)}</td>
                  <td className="px-3 py-2.5 text-right font-mono">{formatPrice(p.markPrice)}</td>
                  <td className="px-3 py-2.5 text-right font-mono text-amber-400/80">{formatPrice(p.liqPrice)}</td>
                  <td className="px-3 py-2.5 text-right font-mono text-zinc-500">{formatPrice(p.breakEvenPrice)}</td>
                  <td className="px-3 py-2.5 text-right font-mono text-zinc-500">{formatNum(p.positionIM, 2)}</td>
                  <td className="px-3 py-2.5 text-right font-mono text-zinc-500">{formatNum(p.positionMM, 2)}</td>
                  <td className={`px-3 py-2.5 text-right font-mono font-semibold ${up ? "text-emerald-400" : "text-rose-400"}`}>
                    {up ? "+" : ""}
                    {formatNum(p.unrealisedPnl, 4)}
                    <span className="ml-1 opacity-70">({roiOf(p)})</span>
                  </td>
                  <td className={`px-3 py-2.5 text-right font-mono ${Number(p.curRealisedPnl) >= 0 ? "text-emerald-400/80" : "text-rose-400/80"}`}>
                    {formatNum(p.curRealisedPnl, 2)}
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    <button
                      onClick={() => openTpsl(p)}
                      className={`inline-flex items-center gap-1 rounded-lg px-2 py-1 font-mono text-xs transition-colors hover:bg-zinc-800 ${
                        tp || sl ? "" : "text-zinc-600 hover:text-zinc-300"
                      }`}
                      title="设置止盈止损"
                    >
                      {tp || sl ? (
                        <>
                          <span className={tp ? "text-emerald-400" : "text-zinc-500"}>
                            {formatPrice(tp)}
                            {tp && sl ? " / " : ""}
                            {sl ? <span className={!tp ? "" : "text-rose-400"}>{formatPrice(sl)}</span> : null}
                          </span>
                          <Crosshair className="size-3 text-zinc-500" />
                        </>
                      ) : (
                        <>
                          <span className="text-zinc-600">未设置</span>
                          <Crosshair className="size-3 text-zinc-600" />
                        </>
                      )}
                    </button>
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    <button
                      onClick={() => openTpsl(p)}
                      className={`inline-flex items-center gap-1 rounded-lg px-2 py-1 font-mono text-xs transition-colors hover:bg-zinc-800 ${
                        p.trailingStop && Number(p.trailingStop) !== 0 ? "" : "text-zinc-600 hover:text-zinc-300"
                      }`}
                      title="设置追踪止损"
                    >
                      {p.trailingStop && Number(p.trailingStop) !== 0 ? (
                        <>
                          <span className="text-zinc-300">{p.trailingStop}</span>
                          <Crosshair className="size-3 text-zinc-500" />
                        </>
                      ) : (
                        <>
                          <span className="text-zinc-600">未设置</span>
                          <Crosshair className="size-3 text-zinc-600" />
                        </>
                      )}
                    </button>
                  </td>
                  <td className="px-3 py-2.5 text-center">
                    <button
                      onClick={() => handleClose(p)}
                      disabled={closing === closingKey}
                      className="inline-flex items-center gap-1 rounded-lg border border-rose-500/40 px-2.5 py-1 text-xs font-medium text-rose-400 transition-colors hover:bg-rose-500/15 disabled:opacity-50"
                      title="市价平仓"
                    >
                      {closing === closingKey ? <Loader2 className="size-3 animate-spin" /> : <X className="size-3" />}
                      平仓
                    </button>
                  </td>
                </tr>
              )
            })}
            {!loading && positions.length === 0 && !error && (
              <tr>
                <td colSpan={15} className="px-4 py-10 text-center text-sm text-zinc-600">
                  暂无持仓，快去开仓吧
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {loading && (
        <div className="flex items-center justify-center py-10">
          <Loader2 className="size-5 animate-spin text-zinc-500" />
        </div>
      )}
      {error && (
        <div className="flex items-center justify-center py-10">
          <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-2 text-sm text-rose-400">{error}</div>
        </div>
      )}

      {/* 止盈止损设置弹窗 */}
      {tpslTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => setTpslTarget(null)}>
          <div
            className="w-full max-w-md rounded-2xl border border-zinc-800 bg-zinc-950 p-5 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-zinc-200">
                止盈止损 · {tpslTarget.symbol}{" "}
                <span className={tpslTarget.side === "Buy" ? "text-emerald-400" : "text-rose-400"}>
                  {tpslTarget.side === "Buy" ? "多" : "空"}
                </span>
              </h3>
              <button onClick={() => setTpslTarget(null)} className="rounded-lg p-1 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-300">
                <X className="size-4" />
              </button>
            </div>

            {/* 模式切换 */}
            <div className="mb-4 grid grid-cols-2 gap-2">
              <button
                onClick={() => setTpMode("Full")}
                className={`rounded-xl py-2 text-xs font-semibold transition-all ${
                  tpMode === "Full" ? "bg-emerald-500/20 text-emerald-400 ring-1 ring-emerald-500/50" : "bg-zinc-900 text-zinc-500 hover:bg-zinc-800"
                }`}
              >
                全部 (Full)
              </button>
              <button
                onClick={() => setTpMode("Partial")}
                className={`rounded-xl py-2 text-xs font-semibold transition-all ${
                  tpMode === "Partial" ? "bg-amber-500/20 text-amber-400 ring-1 ring-amber-500/50" : "bg-zinc-900 text-zinc-500 hover:bg-zinc-800"
                }`}
              >
                部分 (Partial)
              </button>
            </div>

            {/* 输入项 */}
            <div className="space-y-3">
              <div>
                <label className="mb-1.5 block text-xs text-zinc-500">
                  止盈价 <span className="text-zinc-700">（填 0 取消，留空不改）</span>
                </label>
                <input
                  value={tpValue}
                  onChange={(e) => setTpValue(e.target.value)}
                  className="w-full rounded-xl border border-zinc-800 bg-zinc-900/60 px-3 py-2 font-mono text-sm text-emerald-400 outline-none focus:border-zinc-600"
                  placeholder={tpslTarget.markPrice}
                />
              </div>
              <div>
                <label className="mb-1.5 block text-xs text-zinc-500">
                  止损价 <span className="text-zinc-700">（填 0 取消，留空不改）</span>
                </label>
                <input
                  value={slValue}
                  onChange={(e) => setSlValue(e.target.value)}
                  className="w-full rounded-xl border border-zinc-800 bg-zinc-900/60 px-3 py-2 font-mono text-sm text-rose-400 outline-none focus:border-zinc-600"
                  placeholder={tpslTarget.markPrice}
                />
              </div>
              <div>
                <label className="mb-1.5 block text-xs text-zinc-500">
                  追踪止损价差 <span className="text-zinc-700">（留空不改）</span>
                </label>
                <input
                  value={tsValue}
                  onChange={(e) => setTsValue(e.target.value)}
                  className="w-full rounded-xl border border-zinc-800 bg-zinc-900/60 px-3 py-2 font-mono text-sm text-zinc-200 outline-none focus:border-zinc-600"
                  placeholder="如 500"
                />
              </div>
            </div>

            <button
              onClick={handleSaveTpsl}
              disabled={tpSaving}
              className="mt-5 flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-500 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-emerald-400 disabled:opacity-60"
            >
              {tpSaving && <Loader2 className="size-4 animate-spin" />}
              保存设置
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default PositionsTable
