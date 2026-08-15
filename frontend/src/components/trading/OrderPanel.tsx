import { useEffect, useState } from "react"
import { toast } from "sonner"
import { Settings2, Send, CheckCircle2 } from "lucide-react"
import { useTradeStore } from "../../store/tradeStore"
import SymbolSelect from "./SymbolSelect"

interface OrderResult {
  orderId: string
  orderLinkId: string
  retCode: number
  retMsg: string
}

// Bybit linear 合约 taker 手续费率（官方固定 0.055%，API 不返回）
const TAKER_FEE_RATE = 0.00055

interface TradeSpec {
  minOrderQty: string
  maxOrderQty: string
  qtyStep: string
  maxMktOrderQty: string
}

// 可用余额（USDT）与当前价格、合约规格
async function fetchAvailableUsdt(name: string): Promise<number> {
  const res = await fetch(`/api/bybit/wallet-balance?name=${encodeURIComponent(name)}`)
  const json = await res.json()
  const account = json?.result?.list?.[0]
  const coin = account?.coin?.find((c: { coin: string }) => c.coin === "USDT")
  // 优先取 USDT 的可用余额，字段缺失时退回账户总可用余额
  const avail = Number(coin?.availableBalance ?? account?.totalAvailableBalance ?? 0)
  return Number.isFinite(avail) ? avail : 0
}

async function fetchTickerPrice(symbol: string): Promise<number> {
  const res = await fetch(`/api/bybit/market?endpoint=/v5/market/tickers&category=linear&symbol=${symbol}`)
  const json = await res.json()
  return Number(json?.result?.list?.[0]?.lastPrice ?? 0)
}

async function fetchTradeSpec(symbol: string): Promise<TradeSpec | null> {
  const res = await fetch(`/api/bybit/market?endpoint=/v5/market/instruments-info&category=linear&symbol=${symbol}`)
  const json = await res.json()
  const lot = json?.result?.list?.[0]?.lotSizeFilter
  if (!lot) return null
  return { minOrderQty: lot.minOrderQty, maxOrderQty: lot.maxOrderQty, qtyStep: lot.qtyStep, maxMktOrderQty: lot.maxMktOrderQty }
}

// 设置杠杆（买卖侧一致）
async function saveLeverageRequest(name: string, symbol: string, leverage: string): Promise<boolean> {
  try {
    const res = await fetch(`/api/bybit/set-leverage?name=${encodeURIComponent(name)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ category: "linear", symbol, buyLeverage: leverage, sellLeverage: leverage }),
    })
    const json = await res.json()
    return json.retCode === 0 || json.retCode === 110043 // 110043 = 杠杆未变化，视为成功
  } catch {
    return false
  }
}

// 下单
async function placeOrder(name: string, body: Record<string, string>): Promise<OrderResult | null> {
  try {
    const res = await fetch(`/api/bybit/create-order?name=${encodeURIComponent(name)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
    return (await res.json()) as OrderResult
  } catch {
    return null
  }
}

function OrderPanel() {
  const [side, setSide] = useState<"Buy" | "Sell">("Buy")
  const [orderType, setOrderType] = useState<"Market" | "Limit">("Market")
  const symbol = useTradeStore((s) => s.symbol)
  const credentialName = useTradeStore((s) => s.credentialName)
  const [qty, setQty] = useState("0.001")
  const [price, setPrice] = useState("")
  const [leverage, setLeverage] = useState("100")
  const [submitting, setSubmitting] = useState(false)
  const [levSaving, setLevSaving] = useState(false)
  const [availableUsdt, setAvailableUsdt] = useState(0)
  const [markPrice, setMarkPrice] = useState(0)
  const [spec, setSpec] = useState<TradeSpec | null>(null)
  const bumpPositionsRefresh = useTradeStore((s) => s.bumpPositionsRefresh)

  const isBuy = side === "Buy"

  // 拉取余额/价格/合约规格（币种、凭证或杠杆变化时刷新）
  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const sym = symbol.trim().toUpperCase()
        if (!sym) return
        const [usdt, price, s] = await Promise.all([fetchAvailableUsdt(credentialName), fetchTickerPrice(sym), fetchTradeSpec(sym)])
        if (!alive) return
        setAvailableUsdt(usdt)
        setMarkPrice(price)
        setSpec(s)
      } catch {
        // 拉取失败时保持旧值
      }
    }
    load()
    const timer = window.setInterval(load, 15000)
    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [symbol, leverage, credentialName])

  // 最大可开数量：可用余额×杠杆÷现价，预扣 taker 手续费，向下取整到 qtyStep，不超过市价/限价最大单
  const maxOpenQty = (() => {
    if (!spec || !markPrice || !availableUsdt) return null
    const lev = Number(leverage)
    if (!lev || lev < 1) return null
    // 保证金占用 = 名义/杠杆 + 名义×费率，令其 ≤ 可用余额，解出名义上限
    const maxNotional = (availableUsdt * lev) / (1 + lev * TAKER_FEE_RATE)
    const step = Number(spec.qtyStep)
    const maxByBalance = maxNotional / markPrice
    const floored = step > 0 ? Math.floor(maxByBalance / step) * step : maxByBalance
    // 市价单另有最大市价单量限制，取两者较小值
    const limit = orderType === "Market" && Number(spec.maxMktOrderQty) > 0 ? Math.min(Number(spec.maxOrderQty), Number(spec.maxMktOrderQty)) : Number(spec.maxOrderQty)
    const capped = Math.min(floored, limit)
    const decimals = (String(step).split(".")[1] || "").length
    return Number(capped.toFixed(decimals))
  })()

  // 当前输入数量的预计手续费 = 名义价值 × taker 费率
  const estFee = (() => {
    const q = Number(qty)
    if (!q || q <= 0 || !markPrice) return null
    return q * markPrice * TAKER_FEE_RATE
  })()

  const minOrderQty = spec ? Number(spec.minOrderQty) : null

  const handleLeverage = async () => {
    const lev = leverage.trim()
    if (!lev || Number(lev) < 1) {
      toast.error("杠杆必须 ≥ 1")
      return
    }
    setLevSaving(true)
    const ok = await saveLeverageRequest(credentialName, symbol.trim() || "BTCUSDT", lev)
    setLevSaving(false)
    if (ok) toast.success(`杠杆已设置为 ${lev}x`)
    else toast.error("杠杆设置失败")
  }

  const handleSubmit = async () => {
    const sym = symbol.trim().toUpperCase()
    const q = qty.trim()
    if (!sym || !q || Number(q) <= 0) {
      toast.error("请填写有效的合约与数量", { duration: 8000 })
      return
    }
    if (orderType === "Limit" && (!price.trim() || Number(price) <= 0)) {
      toast.error("限价单需要填写价格", { duration: 8000 })
      return
    }
    // 本地预校验：超过最大可开直接拦截，避免到 Bybit 才被拒
    if (maxOpenQty !== null && Number(q) > maxOpenQty + 1e-9) {
      toast.error(`数量超过最大可开 ${maxOpenQty} ${sym}，请降低数量`, { duration: 8000 })
      return
    }
    setSubmitting(true)
    const body: Record<string, string> = {
      category: "linear",
      symbol: sym,
      side,
      orderType,
      qty: q,
      positionIdx: "0",
      timeInForce: orderType === "Limit" ? "GTC" : "IOC",
    }
    if (orderType === "Limit") body.price = price.trim()
    const result = await placeOrder(credentialName, body)
    setSubmitting(false)
    if (!result) {
      toast.error("请求失败，请检查后端与代理", { duration: 8000 })
      return
    }
    if (result.retCode === 0) {
      toast.success(`下单成功 orderId: ${result.orderId}`, { duration: 8000 })
      bumpPositionsRefresh()
    } else if (result.retCode === 110007) {
      // 可用余额不足
      toast.error("可用余额不足，无法开新仓。请降低数量或充值模拟盘资金", {
        description: `(${result.retCode}) ${result.retMsg}`,
        duration: 10000,
      })
    } else {
      toast.error(`下单失败（${result.retCode}）: ${result.retMsg}`, { duration: 8000 })
    }
  }

  return (
    <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40">
      <div className="border-b border-zinc-800 px-4 py-3">
        <h2 className="text-sm font-semibold text-zinc-200">合约下单</h2>
      </div>

      <div className="space-y-4 p-4">
        {/* 方向与类型 */}
        <div className="grid grid-cols-2 gap-2">
          <button
            onClick={() => setSide("Buy")}
            className={`rounded-xl py-2.5 text-sm font-semibold transition-all ${
              isBuy ? "bg-emerald-500 text-white shadow-lg shadow-emerald-500/25" : "bg-zinc-800/80 text-zinc-400 hover:bg-zinc-800"
            }`}
          >
            买入 / 做多
          </button>
          <button
            onClick={() => setSide("Sell")}
            className={`rounded-xl py-2.5 text-sm font-semibold transition-all ${
              !isBuy ? "bg-rose-500 text-white shadow-lg shadow-rose-500/25" : "bg-zinc-800/80 text-zinc-400 hover:bg-zinc-800"
            }`}
          >
            卖出 / 做空
          </button>
        </div>

        {/* 合约与类型 */}
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="mb-1.5 block text-xs text-zinc-500">合约</label>
            <SymbolSelect />
          </div>
          <div>
            <label className="mb-1.5 block text-xs text-zinc-500">订单类型</label>
            <select
              value={orderType}
              onChange={(e) => setOrderType(e.target.value as "Market" | "Limit")}
              className="w-full rounded-xl border border-zinc-800 bg-zinc-950/60 px-3 py-2 text-sm text-zinc-200 outline-none focus:border-zinc-600"
            >
              <option value="Market">市价</option>
              <option value="Limit">限价</option>
            </select>
          </div>
        </div>

        {/* 数量与价格 */}
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="mb-1.5 block text-xs text-zinc-500">数量</label>
            <input
              value={qty}
              onChange={(e) => setQty(e.target.value)}
              className="w-full rounded-xl border border-zinc-800 bg-zinc-950/60 px-3 py-2 font-mono text-sm text-zinc-200 outline-none focus:border-zinc-600"
              placeholder="0.001"
            />
          </div>
          {orderType === "Limit" && (
            <div>
              <label className="mb-1.5 block text-xs text-zinc-500">价格</label>
              <input
                value={price}
                onChange={(e) => setPrice(e.target.value)}
                className="w-full rounded-xl border border-zinc-800 bg-zinc-950/60 px-3 py-2 font-mono text-sm text-zinc-200 outline-none focus:border-zinc-600"
                placeholder="65000"
              />
            </div>
          )}
        </div>

        {/* 开仓限制提示 */}
        <div className="space-y-1 rounded-xl border border-zinc-800/80 bg-zinc-950/40 px-3 py-2">
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-zinc-500">最小开仓</span>
            <span className="font-mono text-zinc-300">{minOrderQty !== null ? `${minOrderQty} ${symbol}` : "-"}</span>
          </div>
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-zinc-500">最大可开（已扣手续费）</span>
            {maxOpenQty !== null ? (
              <button
                onClick={() => setQty(String(maxOpenQty))}
                title="点击填入最大数量"
                className="font-mono text-emerald-400 transition-colors hover:text-emerald-300"
              >
                {maxOpenQty} {symbol}
              </button>
            ) : (
              <span className="font-mono text-zinc-300">-</span>
            )}
          </div>
          {markPrice > 0 && (
            <div className="flex items-center justify-between text-[11px]">
              <span className="text-zinc-500">可用保证金</span>
              <span className="font-mono text-zinc-300">{availableUsdt.toLocaleString("en-US", { maximumFractionDigits: 2 })} USDT</span>
            </div>
          )}
          {estFee !== null && (
            <div className="flex items-center justify-between text-[11px]">
              <span className="text-zinc-500">预计手续费（0.055%）</span>
              <span className="font-mono text-amber-400/90">{estFee.toLocaleString("en-US", { maximumFractionDigits: 4 })} USDT</span>
            </div>
          )}
        </div>

        {/* 杠杆 */}
        <div className="flex items-end gap-2">
          <div className="flex-1">
            <label className="mb-1.5 block text-xs text-zinc-500">杠杆</label>
            <div className="flex items-center gap-2">
              <input
                value={leverage}
                onChange={(e) => setLeverage(e.target.value)}
                className="w-full rounded-xl border border-zinc-800 bg-zinc-950/60 px-3 py-2 font-mono text-sm text-zinc-200 outline-none focus:border-zinc-600"
                placeholder="100"
              />
              <span className="text-sm text-zinc-500">x</span>
              <button
                onClick={handleLeverage}
                disabled={levSaving}
                className="rounded-xl border border-zinc-700 px-3 py-2 text-sm text-zinc-300 transition-colors hover:bg-zinc-800 disabled:opacity-50"
                title="设置杠杆"
              >
                <Settings2 className={`size-4 ${levSaving ? "animate-spin" : ""}`} />
              </button>
            </div>
          </div>
        </div>

        {/* 提交 */}
        <button
          onClick={handleSubmit}
          disabled={submitting}
          className={`flex w-full items-center justify-center gap-2 rounded-xl py-3 text-sm font-semibold text-white transition-all disabled:opacity-60 ${
            isBuy
              ? "bg-emerald-500 shadow-lg shadow-emerald-500/25 hover:bg-emerald-400"
              : "bg-rose-500 shadow-lg shadow-rose-500/25 hover:bg-rose-400"
          }`}
        >
          {submitting ? <Settings2 className="size-4 animate-spin" /> : isBuy ? <Send className="size-4" /> : <CheckCircle2 className="size-4" />}
          {isBuy ? "买入开多" : "卖出开空"}
        </button>
        <p className="text-center text-[11px] text-zinc-600">市价单以 IOC 成交，限价单以 GTC 挂单</p>
      </div>
    </div>
  )
}

export default OrderPanel
