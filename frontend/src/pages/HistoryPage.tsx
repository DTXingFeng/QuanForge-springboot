import { useEffect, useState } from "react"
import { motion, type Variants } from "framer-motion"
import { History, Receipt, Wallet, Loader2, RefreshCw } from "lucide-react"
import { cn } from "../lib/utils"
import { useTradeStore } from "../store/tradeStore"

// 通用拉取
async function fetchRecords(name: string, endpoint: string): Promise<Record<string, string>[]> {
  const res = await fetch(
    `/api/bybit/get?name=${encodeURIComponent(name)}&endpoint=${endpoint}&category=linear&settleCoin=USDT&limit=50`
  )
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const json = await res.json()
  if (json.retCode !== 0) throw new Error(json.retMsg || "请求失败")
  return (json.result?.list ?? []) as Record<string, string>[]
}

// 涨跌色（正绿负红）
function perfColor(v: number): string {
  return v >= 0 ? "text-emerald-400" : "text-rose-400"
}

// 状态徽章
const STATUS_STYLE: Record<string, { label: string; cls: string }> = {
  New: { label: "待成交", cls: "bg-sky-500/10 text-sky-400 ring-sky-500/30" },
  PartiallyFilled: { label: "部分成交", cls: "bg-amber-500/10 text-amber-400 ring-amber-500/30" },
  Filled: { label: "已成交", cls: "bg-emerald-500/10 text-emerald-400 ring-emerald-500/30" },
  Cancelled: { label: "已取消", cls: "bg-zinc-500/10 text-zinc-400 ring-zinc-500/30" },
  Rejected: { label: "已拒绝", cls: "bg-rose-500/10 text-rose-400 ring-rose-500/30" },
  Failed: { label: "失败", cls: "bg-rose-500/10 text-rose-400 ring-rose-500/30" },
}

function StatusBadge({ status }: { status: string }) {
  const s = STATUS_STYLE[status] ?? { label: status, cls: "bg-zinc-500/10 text-zinc-400 ring-zinc-500/30" }
  return (
    <span className={cn("inline-flex rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset", s.cls)}>
      {s.label}
    </span>
  )
}

const rowVariants: Variants = {
  hidden: { opacity: 0, y: 14, scale: 0.99, filter: "blur(3px)" },
  visible: {
    opacity: 1,
    y: 0,
    scale: 1,
    filter: "blur(0px)",
    transition: { type: "spring", stiffness: 350, damping: 26, mass: 0.8 },
  },
}

// 通用表格壳（FinancialTable 风格：圆角边框容器 + 网格表头）
function TableShell({
  title,
  columns,
  rows,
  renderRow,
  emptyText,
  loading,
  onRefresh,
}: {
  title: string
  columns: string[]
  rows: Record<string, string>[]
  renderRow: (r: Record<string, string>) => React.ReactNode
  emptyText: string
  loading: boolean
  onRefresh: () => void
}) {
  return (
    <div className="overflow-hidden rounded-2xl border border-zinc-800/80 bg-zinc-900/40">
      <div className="flex items-center justify-between border-b border-zinc-800/80 px-5 py-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-zinc-200">
          <History className="h-4 w-4 text-indigo-400" />
          {title}
          <span className="rounded-md bg-zinc-800 px-1.5 py-0.5 text-xs text-zinc-400">{rows.length}</span>
        </div>
        <button
          onClick={onRefresh}
          className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs text-zinc-400 transition-colors hover:bg-zinc-800 hover:text-zinc-200"
        >
          {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          刷新
        </button>
      </div>
      <div className="overflow-x-auto">
        <div className="min-w-[900px]">
          <div
            className="grid border-b border-zinc-800/60 bg-zinc-950/50 px-5 py-2.5 text-[11px] font-medium uppercase tracking-wide text-zinc-500"
            style={{ gridTemplateColumns: `repeat(${columns.length}, minmax(90px, 1fr))`, columnGap: "8px" }}
          >
            {columns.map((c) => (
              <div key={c}>{c}</div>
            ))}
          </div>
          {loading && rows.length === 0 ? (
            <div className="flex items-center justify-center py-16 text-sm text-zinc-500">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 加载中...
            </div>
          ) : rows.length === 0 ? (
            <div className="py-16 text-center text-sm text-zinc-500">{emptyText}</div>
          ) : (
            <motion.div initial="hidden" animate="visible" variants={{ visible: { transition: { staggerChildren: 0.03 } } }}>
              {rows.map((r, i) => (
                <motion.div
                  key={i}
                  variants={rowVariants}
                  className={cn(
                    "grid px-5 py-3 text-sm transition-colors hover:bg-zinc-800/30",
                    i < rows.length - 1 && "border-b border-zinc-800/40"
                  )}
                  style={{ gridTemplateColumns: `repeat(${columns.length}, minmax(90px, 1fr))`, columnGap: "8px" }}
                >
                  {renderRow(r)}
                </motion.div>
              ))}
            </motion.div>
          )}
        </div>
      </div>
    </div>
  )
}

function fmtTime(ms: string | number | undefined): string {
  if (!ms || ms === "0") return "-"
  const n = Number(ms)
  if (!Number.isFinite(n) || n <= 0) return "-"
  return new Date(n).toLocaleString("zh-CN", { hour12: false })
}

function fmtNum(v: string | number | undefined, digits = 4): string {
  if (v === undefined || v === null || v === "") return "-"
  const n = Number(v)
  if (!Number.isFinite(n)) return "-"
  return n.toLocaleString("en-US", { maximumFractionDigits: digits })
}

// ---------- 历史订单 ----------
function HistoryOrders() {
  const [rows, setRows] = useState<Record<string, string>[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const credentialName = useTradeStore((s) => s.credentialName)

  const load = async () => {
    try {
      setRows(await fetchRecords(credentialName, "/v5/order/history"))
      setError("")
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [credentialName])

  return (
    <div className="space-y-3">
      <TableShell
        title="历史订单"
        columns={["合约", "方向", "类型", "价格", "数量", "已成交", "状态", "成交均价", "下单时间"]}
        rows={rows}
        loading={loading}
        emptyText="暂无历史订单"
        onRefresh={load}
        renderRow={(r) => (
          <>
            <div className="font-mono text-zinc-200">{String(r.symbol)}</div>
            <div className={cn("font-medium", r.side === "Buy" ? "text-emerald-400" : "text-rose-400")}>
              {r.side === "Buy" ? "买入" : "卖出"}
            </div>
            <div className="text-zinc-400">{String(r.orderType)}</div>
            <div className="font-mono text-zinc-200">{fmtNum(r.price)}</div>
            <div className="font-mono text-zinc-200">{fmtNum(r.qty)}</div>
            <div className="font-mono text-zinc-400">
              {fmtNum(r.cumExecQty)} / {fmtNum(r.qty)}
            </div>
            <div>
              <StatusBadge status={String(r.orderStatus)} />
            </div>
            <div className="font-mono text-zinc-400">{fmtNum(r.avgPrice)}</div>
            <div className="text-xs text-zinc-500">{fmtTime(String(r.createdTime))}</div>
          </>
        )}
      />
      {error && <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-400">{error}</div>}
    </div>
  )
}

// ---------- 成交记录 ----------
function Executions() {
  const [rows, setRows] = useState<Record<string, string>[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const credentialName = useTradeStore((s) => s.credentialName)

  const load = async () => {
    try {
      setRows(await fetchRecords(credentialName, "/v5/execution/list"))
      setError("")
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [credentialName])

  return (
    <div className="space-y-3">
      <TableShell
        title="成交记录"
        columns={["合约", "方向", "类型", "成交价", "数量", "手续费", "已实现盈亏", "成交时间"]}
        rows={rows}
        loading={loading}
        emptyText="暂无成交记录"
        onRefresh={load}
        renderRow={(r) => (
          <>
            <div className="font-mono text-zinc-200">{String(r.symbol)}</div>
            <div className={cn("font-medium", r.side === "Buy" ? "text-emerald-400" : "text-rose-400")}>
              {r.side === "Buy" ? "买入" : "卖出"}
            </div>
            <div className="text-zinc-400">{String(r.orderType)}</div>
            <div className="font-mono text-zinc-200">{fmtNum(r.execPrice ?? r.price)}</div>
            <div className="font-mono text-zinc-200">{fmtNum(r.execQty)}</div>
            <div className="font-mono text-zinc-400">{fmtNum(r.execFee)}</div>
            <div className={cn("font-mono", perfColor(Number(r.realisedPnl ?? 0)))}>{fmtNum(r.realisedPnl)}</div>
            <div className="text-xs text-zinc-500">{fmtTime(String(r.execTime))}</div>
          </>
        )}
      />
      {error && <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-400">{error}</div>}
    </div>
  )
}

// ---------- 平仓盈亏 ----------
function ClosedPnl() {
  const [rows, setRows] = useState<Record<string, string>[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const credentialName = useTradeStore((s) => s.credentialName)

  const load = async () => {
    try {
      setRows(await fetchRecords(credentialName, "/v5/position/closed-pnl"))
      setError("")
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [credentialName])

  return (
    <div className="space-y-3">
      <TableShell
        title="平仓盈亏"
        columns={["合约", "方向", "平仓盈亏", "数量", "入场价", "出场价", "杠杆", "平仓时间"]}
        rows={rows}
        loading={loading}
        emptyText="暂无平仓记录"
        onRefresh={load}
        renderRow={(r) => (
          <>
            <div className="font-mono text-zinc-200">{String(r.symbol)}</div>
            <div className={cn("font-medium", r.side === "Buy" ? "text-emerald-400" : "text-rose-400")}>
              {r.side === "Buy" ? "买入" : "卖出"}
            </div>
            <div className={cn("font-mono font-semibold", perfColor(Number(r.closedPnl)))}>{fmtNum(r.closedPnl)}</div>
            <div className="font-mono text-zinc-200">{fmtNum(r.qty)}</div>
            <div className="font-mono text-zinc-400">{fmtNum(r.avgEntryPrice)}</div>
            <div className="font-mono text-zinc-400">{fmtNum(r.avgExitPrice)}</div>
            <div className="font-mono text-zinc-400">{fmtNum(r.leverage, 0)}x</div>
            <div className="text-xs text-zinc-500">{fmtTime(String(r.updatedTime))}</div>
          </>
        )}
      />
      {error && <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-400">{error}</div>}
    </div>
  )
}

// ---------- 页面 ----------
type TabKey = "orders" | "executions" | "closedPnl"

const TABS: { key: TabKey; label: string; icon: React.ElementType }[] = [
  { key: "orders", label: "历史订单", icon: History },
  { key: "executions", label: "成交记录", icon: Receipt },
  { key: "closedPnl", label: "平仓盈亏", icon: Wallet },
]

function HistoryPage() {
  const [tab, setTab] = useState<TabKey>("orders")

  return (
    <div className="space-y-5 p-6">
      <div>
        <h1 className="text-lg font-semibold text-zinc-100">历史记录</h1>
        <p className="mt-0.5 text-sm text-zinc-500">订单、成交与平仓盈亏明细</p>
      </div>

      <div className="flex gap-1.5 rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-1.5">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={cn(
              "flex flex-1 items-center justify-center gap-2 rounded-lg py-2 text-sm font-medium transition-colors",
              tab === t.key
                ? "bg-indigo-500/15 text-indigo-300 ring-1 ring-inset ring-indigo-500/30"
                : "text-zinc-400 hover:bg-zinc-800/60 hover:text-zinc-200"
            )}
          >
            <t.icon className="h-4 w-4" />
            {t.label}
          </button>
        ))}
      </div>

      {tab === "orders" && <HistoryOrders />}
      {tab === "executions" && <Executions />}
      {tab === "closedPnl" && <ClosedPnl />}
    </div>
  )
}

export default HistoryPage
