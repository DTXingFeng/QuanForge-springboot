import { useEffect, useState } from "react"
import { toast } from "sonner"
import { Card } from "../ui/card"
import { Wallet, TrendingUp, Eye, RefreshCw, ArrowDown, ArrowUp, ArrowLeftRight, Clock, Bitcoin, Loader2, X } from "lucide-react"
import { useTradeStore } from "../../store/tradeStore"

interface WalletData {
  totalWalletBalance: string
  totalMarginBalance: string
  totalEquity: string
  totalAvailableBalance: string
  totalPerpUPL: string
  coins: { coin: string; equity: string; walletBalance: string }[]
}

// 拉取 Bybit 统一账户余额
async function fetchWallet(name: string): Promise<WalletData | null> {
  try {
    const res = await fetch(`/api/bybit/wallet-balance?name=${encodeURIComponent(name)}`)
    if (!res.ok) return null
    const json = await res.json()
    const account = json?.result?.list?.[0]
    if (!account) return null
    return {
      totalWalletBalance: account.totalWalletBalance ?? "0",
      totalMarginBalance: account.totalMarginBalance ?? "0",
      totalEquity: account.totalEquity ?? "0",
      totalAvailableBalance: account.totalAvailableBalance ?? "0",
      totalPerpUPL: account.totalPerpUPL ?? "0",
      coins: (account.coin || [])
        .filter((c: any) => c.coin)
        .map((c: any) => ({ coin: c.coin, equity: c.equity ?? "0", walletBalance: c.walletBalance ?? "0" })),
    }
  } catch {
    return null
  }
}

// 拉取 BTC 价格用于折算
async function fetchBtcPrice(): Promise<number> {
  try {
    const res = await fetch(
      "/api/bybit/market?endpoint=/v5/market/tickers&category=linear&symbol=BTCUSDT",
    )
    if (!res.ok) return 0
    const json = await res.json()
    return Number(json?.result?.list?.[0]?.lastPrice) || 0
  } catch {
    return 0
  }
}

const formatMoney = (value: number): string => {
  if (Number.isNaN(value)) return "0.00"
  return value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

// 调整模拟盘虚拟资金（adjustType: 0=增加/1=减少）
async function adjustDemoMoney(name: string, adjustType: number, amount: string): Promise<{ retCode: number; retMsg: string } | null> {
  try {
    const res = await fetch(`/api/bybit/demo-apply-money?name=${encodeURIComponent(name)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ adjustType, utaDemoApplyMoney: [{ coin: "USDT", amountStr: amount }] }),
    })
    return await res.json()
  } catch {
    return null
  }
}

function WalletCard() {
  const [data, setData] = useState<WalletData | null>(null)
  const [btcPrice, setBtcPrice] = useState(0)
  const [hidden, setHidden] = useState(false)
  const [loading, setLoading] = useState(true)
  const [mode, setMode] = useState("DEMO")
  const [adjustModal, setAdjustModal] = useState(false)
  const [amount, setAmount] = useState("")
  const [currentUsdt, setCurrentUsdt] = useState(0)
  const [adjusting, setAdjusting] = useState(false)

  // 当前交易凭证（与设置页/下单面板共享）
  const credentialName = useTradeStore((s) => s.credentialName)

  const load = async () => {
    setLoading(true)
    const [wallet, price] = await Promise.all([fetchWallet(credentialName), fetchBtcPrice()])
    setData(wallet)
    setBtcPrice(price)
    setLoading(false)
  }

  useEffect(() => {
    load()
    const timer = setInterval(load, 60000)
    return () => clearInterval(timer)
    // 凭证切换后立即重拉余额
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [credentialName])

  useEffect(() => {
    fetch("/api/bybit/mode")
      .then((r) => r.json())
      .then((j) => setMode(j.mode || "DEMO"))
      .catch(() => {})
  }, [])

  const isDemo = mode === "DEMO"

  // 打开调整弹窗时拉取当前 USDT 余额
  const openAdjustModal = async () => {
    const w = await fetchWallet(credentialName)
    const usdt = w?.coins.find((c) => c.coin === "USDT")?.walletBalance
    setCurrentUsdt(Number(usdt) || 0)
    setAmount("")
    setAdjustModal(true)
  }

  // 目标金额模式：自动计算差值并调用 demo-apply-money（USDT 精度为整数）
  const handleAdjust = async () => {
    const target = Number(amount)
    if (!target || target < 0 || !adjustModal) {
      toast.error("请输入有效的目标金额")
      return
    }
    const delta = target - currentUsdt
    if (Math.abs(delta) < 1) {
      toast.info("目标金额需与当前余额相差至少 1 USDT（支持整数精度）")
      return
    }
    const adjustType = delta > 0 ? 0 : 1 // 0=增加 1=减少
    const diffInt = Math.round(Math.abs(delta)) // USDT 精度为 1，取整
    setAdjusting(true)
    const r = await adjustDemoMoney(credentialName, adjustType, String(diffInt))
    setAdjusting(false)
    if (!r) {
      toast.error("请求失败，请检查后端")
    } else if (r.retCode === 0) {
      toast.success(`USDT 已${adjustType === 0 ? "增加" : "减少"} ${diffInt} → 约 ${target.toFixed(2)}`)
      setAdjustModal(false)
      setAmount("")
      load()
    } else {
      toast.error(`调整失败（${r.retCode}）: ${r.retMsg}`)
    }
  }

  const totalEquity = Number(data?.totalEquity) || 0
  const btcAmount = btcPrice > 0 ? totalEquity / btcPrice : 0
  const upnl = Number(data?.totalPerpUPL) || 0

  return (
    <div className="mx-auto w-full max-w-md">
      <Card className="rounded-3xl border-zinc-800 bg-zinc-900/70 p-6 shadow-xl backdrop-blur-sm">
        <div className="space-y-6">
          {/* 两个子账户余额卡 */}
          <div className="space-y-3">
            <Card className="rounded-2xl border-rose-500/20 bg-gradient-to-r from-rose-500/20 to-orange-500/10 p-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-black/20">
                    <Wallet className="h-4 w-4 text-rose-200" />
                  </div>
                  <span className="font-medium text-rose-50">资金账户</span>
                </div>
                <span className="font-semibold text-rose-50">
                  {hidden ? "****" : `$${formatMoney(Number(data?.totalWalletBalance) || 0)}`}
                </span>
              </div>
            </Card>
            <Card className="rounded-2xl border-indigo-500/20 bg-gradient-to-r from-indigo-500/20 to-purple-500/10 p-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-black/20">
                    <TrendingUp className="h-4 w-4 text-indigo-200" />
                  </div>
                  <span className="font-medium text-indigo-50">统一交易账户</span>
                </div>
                <span className="font-semibold text-indigo-50">
                  {hidden ? "****" : `$${formatMoney(Number(data?.totalMarginBalance) || 0)}`}
                </span>
              </div>
            </Card>
          </div>

          {/* 总余额 */}
          <div className="space-y-4 rounded-2xl border border-zinc-800 bg-zinc-900/50 px-2 py-6">
            <div className="flex items-center justify-between px-2">
              <div className="flex items-center gap-2">
                <div className="flex h-6 w-6 items-center justify-center rounded-full bg-zinc-700">
                  <div className="h-3 w-3 rounded-full bg-zinc-400" />
                </div>
                <span className="font-medium text-zinc-400">总权益</span>
                <button
                  onClick={() => setHidden(!hidden)}
                  className="text-zinc-500 transition-colors hover:text-zinc-300"
                >
                  <Eye className="h-4 w-4" />
                </button>
              </div>
              <button
                onClick={load}
                className="text-zinc-500 transition-transform hover:text-zinc-300"
                title="刷新"
              >
                <RefreshCw className={`h-5 w-5 ${loading ? "animate-spin" : ""}`} />
              </button>
            </div>
            <div className="space-y-2 px-2">
              <div className="text-4xl font-bold text-zinc-50">
                {loading ? "—" : hidden ? "****" : `$${formatMoney(totalEquity)}`}
              </div>
              <div className="flex items-center gap-2 text-orange-400">
                <Bitcoin className="h-4 w-4" />
                <span className="font-medium">{hidden ? "****" : `${btcAmount.toFixed(6)} BTC`}</span>
                <span className={`ml-auto text-xs ${upnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                  未实现盈亏 {upnl >= 0 ? "+" : ""}
                  {formatMoney(upnl)}
                </span>
              </div>
            </div>
          </div>

          {/* 操作按钮 */}
          <div className="flex gap-3">
            <button
              onClick={openAdjustModal}
              disabled={!isDemo}
              title={isDemo ? "调整模拟盘 USDT 余额（目标金额模式）" : "实盘模式下不可用，仅模拟盘支持"}
              className="flex h-12 flex-1 items-center justify-center gap-2 rounded-2xl border border-rose-600 bg-rose-500 text-sm font-medium text-white transition-colors hover:bg-rose-600 disabled:opacity-40"
            >
              <ArrowDown className="h-4 w-4" />
              充值
            </button>
            <button
              onClick={openAdjustModal}
              disabled={!isDemo}
              title={isDemo ? "调整模拟盘 USDT 余额（目标金额模式）" : "实盘模式下不可用，仅模拟盘支持"}
              className="flex h-12 flex-1 items-center justify-center gap-2 rounded-2xl border border-zinc-700 bg-zinc-800 text-sm font-medium text-zinc-300 transition-colors hover:bg-zinc-700 disabled:opacity-40"
            >
              <ArrowUp className="h-4 w-4" />
              提现
            </button>
            <button className="flex h-12 w-12 items-center justify-center rounded-2xl border border-zinc-700 bg-zinc-800 text-zinc-300 transition-colors hover:bg-zinc-700">
              <ArrowLeftRight className="h-4 w-4" />
            </button>
            <button className="flex h-12 w-12 items-center justify-center rounded-2xl border border-zinc-700 bg-zinc-800 text-zinc-300 transition-colors hover:bg-zinc-700">
              <Clock className="h-4 w-4" />
            </button>
          </div>

          {/* 币种明细 */}
          <div className="space-y-1 pt-2">
            {(data?.coins || []).map((c) => (
              <div
                key={c.coin}
                className="flex items-center gap-4 rounded-2xl border border-zinc-800 p-3 transition-colors hover:bg-zinc-800/50"
              >
                <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-zinc-700 bg-zinc-800">
                  <span className="text-sm font-bold text-zinc-200">{c.coin.slice(0, 1)}</span>
                </div>
                <div className="flex-1">
                  <h3 className="font-semibold text-zinc-100">{c.coin}</h3>
                  <p className="text-sm text-zinc-500">余额 {formatMoney(Number(c.walletBalance))}</p>
                </div>
                <div className="text-sm font-medium text-zinc-300">${formatMoney(Number(c.equity))}</div>
              </div>
            ))}
            {!loading && !data && (
              <div className="rounded-2xl border border-zinc-800 p-4 text-center text-sm text-zinc-500">
                无法加载钱包数据，请检查凭证配置
              </div>
            )}
          </div>

          {/* 模拟盘 USDT 目标金额调整弹窗 */}
          {adjustModal && (
            <div
              className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
              onClick={() => !adjusting && setAdjustModal(false)}
            >
              <div
                className="w-full max-w-sm rounded-2xl border border-zinc-800 bg-zinc-900 p-5 shadow-xl"
                onClick={(e) => e.stopPropagation()}
              >
                <div className="mb-4 flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-zinc-100">调整 USDT 余额（模拟盘）</h3>
                  <button
                    onClick={() => setAdjustModal(false)}
                    disabled={adjusting}
                    className="text-zinc-500 hover:text-zinc-300 disabled:opacity-40"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>

                <div className="mb-3 flex items-center justify-between rounded-xl border border-zinc-800 bg-zinc-950/60 px-3 py-2">
                  <span className="text-xs text-zinc-500">当前余额</span>
                  <span className="font-mono text-sm font-semibold text-zinc-100">
                    ${formatMoney(currentUsdt)}
                  </span>
                </div>

                <input
                  autoFocus
                  value={amount}
                  onChange={(e) => setAmount(e.target.value.replace(/[^0-9.]/g, ""))}
                  disabled={adjusting}
                  className="w-full rounded-xl border border-zinc-800 bg-zinc-950/60 px-3 py-2 font-mono text-sm text-zinc-200 outline-none focus:border-zinc-600"
                  placeholder="输入目标金额，如 5000"
                />

                {amount && Number(amount) >= 0 && (
                  <div className="mt-2 text-center text-xs">
                    {(() => {
                      const delta = Number(amount) - currentUsdt
                      const diff = Math.round(Math.abs(delta))
                      if (diff < 1) {
                        return <span className="text-zinc-500">目标与当前相差不足 1 USDT</span>
                      }
                      return delta > 0 ? (
                        <span className="text-emerald-400">将自动增加 {diff} USDT</span>
                      ) : (
                        <span className="text-rose-400">将自动减少 {diff} USDT</span>
                      )
                    })()}
                  </div>
                )}

                <button
                  onClick={handleAdjust}
                  disabled={adjusting}
                  className={`mt-3 flex w-full items-center justify-center gap-2 rounded-xl py-2.5 text-sm font-semibold text-white disabled:opacity-60 ${
                    Number(amount) >= currentUsdt
                      ? "bg-emerald-500 hover:bg-emerald-400"
                      : "bg-rose-500 hover:bg-rose-400"
                  }`}
                >
                  {adjusting && <Loader2 className="h-4 w-4 animate-spin" />}
                  确认调整
                </button>
              </div>
            </div>
          )}
        </div>
      </Card>
    </div>
  )
}

export default WalletCard
