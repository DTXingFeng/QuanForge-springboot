import { useEffect, useMemo, useState } from "react"
import { toast } from "sonner"
import { Resizable } from "react-resizable"
import "react-resizable/css/styles.css"
import { RefreshCw, XCircle, Loader2 } from "lucide-react"
import { useTradeStore } from "../../store/tradeStore"

interface OpenOrder {
  symbol: string
  side: string
  orderType: string
  orderId: string
  price: string
  qty: string
  leverage: string
  orderStatus: string
  cumExecQty: string
  avgPrice: string
  timeInForce: string
  createdTime: string
}

// 订单状态样式（点灯 badge）
const STATUS_STYLE: Record<string, { label: string; bg: string; border: string; text: string; dot: string }> = {
  New: { label: "待成交", bg: "bg-blue-500/10", border: "border-blue-500/30", text: "text-blue-400", dot: "bg-blue-400" },
  PartiallyFilled: { label: "部分成交", bg: "bg-amber-500/10", border: "border-amber-500/30", text: "text-amber-400", dot: "bg-amber-400" },
  Filled: { label: "已成交", bg: "bg-emerald-500/10", border: "border-emerald-500/30", text: "text-emerald-400", dot: "bg-emerald-400" },
  Cancelled: { label: "已取消", bg: "bg-zinc-500/10", border: "border-zinc-500/30", text: "text-zinc-400", dot: "bg-zinc-400" },
  Rejected: { label: "已拒绝", bg: "bg-rose-500/10", border: "border-rose-500/30", text: "text-rose-400", dot: "bg-rose-400" },
  Failed: { label: "已失败", bg: "bg-rose-500/10", border: "border-rose-500/30", text: "text-rose-400", dot: "bg-rose-400" },
}

const ORDER_TYPE_LABEL: Record<string, string> = {
  Market: "市价",
  Limit: "限价",
  Stop: "条件",
  StopMarket: "止损市价",
  StopLimit: "止损限价",
  TakeProfitMarket: "止盈市价",
  TakeProfitLimit: "止盈限价",
}

async function fetchOpenOrders(name: string): Promise<OpenOrder[]> {
  const res = await fetch(`/api/bybit/get?name=${encodeURIComponent(name)}&endpoint=/v5/order/realtime&category=linear&settleCoin=USDT&openOnly=0`)
  const json = await res.json()
  if (json.retCode !== 0) throw new Error(json.retMsg || "查询失败")
  const list: any[] = json.result?.list ?? []
  return list.map((o) => ({
    symbol: o.symbol,
    side: o.side,
    orderType: o.orderType,
    orderId: o.orderId,
    price: o.price,
    qty: o.qty,
    leverage: o.leverage,
    orderStatus: o.orderStatus,
    cumExecQty: o.cumExecQty,
    avgPrice: o.avgPrice,
    timeInForce: o.timeInForce,
    createdTime: o.createdTime,
  }))
}

async function cancelOrder(name: string, order: OpenOrder): Promise<{ retCode: number; retMsg: string }> {
  const res = await fetch(`/api/bybit/cancel-order?name=${encodeURIComponent(name)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ category: "linear", symbol: order.symbol, orderId: order.orderId }),
  })
  return await res.json()
}

async function cancelAllOrders(name: string): Promise<{ retCode: number; retMsg: string; result?: { success?: string } }> {
  const res = await fetch(`/api/bybit/cancel-all?name=${encodeURIComponent(name)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ category: "linear", settleCoin: "USDT" }),
  })
  return await res.json()
}

const DEFAULT_WIDTHS: Record<string, number> = {
  symbol: 110,
  side: 80,
  type: 90,
  price: 110,
  qty: 100,
  filled: 90,
  status: 110,
  created: 150,
  action: 80,
}

function OpenOrdersTable() {
  const [orders, setOrders] = useState<OpenOrder[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [cancelling, setCancelling] = useState("")
  const [widths, setWidths] = useState(DEFAULT_WIDTHS)
  const positionsRefreshKey = useTradeStore((s) => s.positionsRefreshKey)
  const credentialName = useTradeStore((s) => s.credentialName)

  const load = async () => {
    try {
      setOrders(await fetchOpenOrders(credentialName))
      setError("")
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    const timer = window.setInterval(load, 10000)
    return () => window.clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [credentialName])

  // 开仓/平仓后刷新
  useEffect(() => {
    load()
  }, [positionsRefreshKey])

  const handleCancel = async (order: OpenOrder) => {
    if (!window.confirm(`确认撤单 ${order.symbol} ${order.side === "Buy" ? "多" : "空"} ${order.qty} @ ${order.price} ?`)) return
    setCancelling(order.orderId)
    try {
      const r = await cancelOrder(credentialName, order)
      if (r.retCode === 0) {
        toast.success(`${order.symbol} 撤单成功`)
        setTimeout(load, 800)
      } else {
        toast.error(`撤单失败（${r.retCode}）: ${r.retMsg}`)
      }
    } catch {
      toast.error("撤单请求失败，请检查后端")
    } finally {
      setCancelling("")
    }
  }

  const handleResize = (key: string, width: number) => {
    setWidths((prev) => ({ ...prev, [key]: Math.max(60, Math.min(300, width)) }))
  }

  const timeStr = (t: string) => {
    if (!t) return "-"
    return new Date(Number(t)).toLocaleString("zh-CN", { hour12: false })
  }

  const renderHeader = (key: string, label: string) => (
    <Resizable
      width={widths[key]}
      height={0}
      onResize={(_e, data) => handleResize(key, data.size.width)}
      minConstraints={[60, 0]}
      maxConstraints={[300, 0]}
      handle={<div className="absolute right-0 top-0 bottom-0 z-10 w-1 cursor-col-resize bg-transparent transition-colors hover:bg-emerald-500/50" />}
    >
      <div className="relative flex h-10 items-center gap-1 border-r border-zinc-800 px-3 text-xs font-medium text-zinc-400" style={{ width: widths[key] }}>
        <span className="truncate">{label}</span>
      </div>
    </Resizable>
  )

  const totalCount = useMemo(() => orders.length, [orders])

  const handleCancelAll = async () => {
    if (!window.confirm(`确认撤销全部 ${totalCount} 个活动订单？`)) return
    setCancelling("ALL")
    try {
      const r = await cancelAllOrders(credentialName)
      if (r.retCode === 0) {
        toast.success(`已撤销全部活动订单（${r.result?.success ?? "-"}）`)
        setTimeout(load, 800)
      } else {
        toast.error(`撤单失败（${r.retCode}）: ${r.retMsg}`)
      }
    } catch {
      toast.error("撤单请求失败，请检查后端")
    } finally {
      setCancelling("")
    }
  }

  return (
    <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40">
      <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-zinc-200">活动订单</h2>
          <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-[11px] text-zinc-400">{totalCount}</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleCancelAll}
            disabled={loading || orders.length === 0}
            className="flex items-center gap-1.5 rounded-lg border border-rose-500/40 px-2.5 py-1.5 text-xs text-rose-400 transition-colors hover:bg-rose-500/10 disabled:opacity-40"
            title="撤销全部活动订单"
          >
            {cancelling === "ALL" ? <Loader2 className="size-3.5 animate-spin" /> : <XCircle className="size-3.5" />}
            撤全部
          </button>
          <button onClick={load} disabled={loading} className="flex items-center gap-1.5 rounded-lg border border-zinc-800 px-2.5 py-1.5 text-xs text-zinc-400 transition-colors hover:bg-zinc-800 disabled:opacity-50" title="刷新">
            {loading ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
            刷新
          </button>
        </div>
      </div>

      {error && (
        <div className="mx-4 mt-3 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-400">{error}</div>
      )}

      <div className="overflow-x-auto">
        <div className="min-w-max">
          {/* 表头 */}
          <div className="flex border-b border-zinc-800 bg-zinc-950/40">
            {renderHeader("symbol", "合约")}
            {renderHeader("side", "方向")}
            {renderHeader("type", "类型")}
            {renderHeader("price", "价格")}
            {renderHeader("qty", "数量")}
            {renderHeader("filled", "已成交")}
            {renderHeader("status", "状态")}
            {renderHeader("created", "下单时间")}
            {renderHeader("action", "操作")}
          </div>

          {/* 行 */}
          {loading && orders.length === 0 ? (
            <div className="flex items-center justify-center gap-2 py-12 text-sm text-zinc-500">
              <Loader2 className="size-4 animate-spin" /> 加载中...
            </div>
          ) : orders.length === 0 ? (
            <div className="py-12 text-center text-sm text-zinc-600">暂无活动订单</div>
          ) : (
            orders.map((o) => {
              const st = STATUS_STYLE[o.orderStatus] ?? STATUS_STYLE.New
              const filledPct = Number(o.qty) > 0 ? (Number(o.cumExecQty) / Number(o.qty)) * 100 : 0
              return (
                <div key={o.orderId} className="flex items-center border-b border-zinc-800/60 text-xs transition-colors hover:bg-zinc-800/30">
                  <div className="px-3 py-2.5 font-mono text-zinc-200" style={{ width: widths.symbol }}>{o.symbol}</div>
                  <div className="px-3 py-2.5" style={{ width: widths.side }}>
                    <span className={`rounded-md px-1.5 py-0.5 text-[11px] font-medium ${o.side === "Buy" ? "bg-emerald-500/10 text-emerald-400" : "bg-rose-500/10 text-rose-400"}`}>
                      {o.side === "Buy" ? "多" : "空"}
                    </span>
                  </div>
                  <div className="px-3 py-2.5 text-zinc-400" style={{ width: widths.type }}>{ORDER_TYPE_LABEL[o.orderType] ?? o.orderType}</div>
                  <div className="px-3 py-2.5 font-mono text-zinc-300" style={{ width: widths.price }}>{Number(o.price) > 0 ? Number(o.price).toLocaleString("en-US", { maximumFractionDigits: 2 }) : "市价"}</div>
                  <div className="px-3 py-2.5 font-mono text-zinc-300" style={{ width: widths.qty }}>{o.qty}</div>
                  <div className="px-3 py-2.5" style={{ width: widths.filled }}>
                    <div className="flex items-center gap-1.5">
                      <div className="h-1 w-10 overflow-hidden rounded-full bg-zinc-800">
                        <div className={`h-full rounded-full ${filledPct >= 100 ? "bg-emerald-500" : "bg-amber-500"}`} style={{ width: `${filledPct}%` }} />
                      </div>
                      <span className="font-mono text-[11px] text-zinc-500">{o.cumExecQty}</span>
                    </div>
                  </div>
                  <div className="px-3 py-2.5" style={{ width: widths.status }}>
                    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] ${st.bg} ${st.border} ${st.text}`}>
                      <span className={`size-1.5 rounded-full ${st.dot}`} />
                      {st.label}
                    </span>
                  </div>
                  <div className="px-3 py-2.5 font-mono text-[11px] text-zinc-500" style={{ width: widths.created }}>{timeStr(o.createdTime)}</div>
                  <div className="px-3 py-2.5" style={{ width: widths.action }}>
                    <button
                      onClick={() => handleCancel(o)}
                      disabled={cancelling === o.orderId || o.orderStatus === "Filled" || o.orderStatus === "Cancelled"}
                      title="撤单"
                      className="rounded-md border border-zinc-800 p-1.5 text-zinc-500 transition-colors hover:border-rose-500/40 hover:text-rose-400 disabled:opacity-40"
                    >
                      {cancelling === o.orderId ? <Loader2 className="size-3.5 animate-spin" /> : <XCircle className="size-3.5" />}
                    </button>
                  </div>
                </div>
              )
            })
          )}
        </div>
      </div>
    </div>
  )
}

export default OpenOrdersTable
