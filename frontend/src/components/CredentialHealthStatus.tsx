import { useCallback, useEffect, useRef, useState } from "react"
import { Link } from "react-router-dom"
import { useTradeStore } from "../store/tradeStore"

interface Health {
  status: string
  level: string
  message: string
  environment: string
  checkedAt: number | null
  retCode: number | null
  stale: boolean
  expiresAt?: string | null
  remainingDays?: number | null
  readOnly?: boolean | null
  tradePermissionConfigured?: boolean | null
}

export function CredentialHealthStatus({ id, mode = "DEMO", autoCheck = false }: { id: number; mode?: string; autoCheck?: boolean }) {
  const [health, setHealth] = useState<Health | null>(null)
  const [busy, setBusy] = useState(false)
  const sequence = useRef(0)
  const pending = useRef(false)
  const load = useCallback(async (validate: boolean) => {
    if (pending.current) return
    pending.current = true
    const token = ++sequence.current
    setBusy(true)
    try {
      const request = async (probe: boolean): Promise<Health> => {
        const response = await fetch(`/api/credentials/${id}/${probe ? "validate" : "health"}?mode=${mode}`, { method: probe ? "POST" : "GET" })
        if (!response.ok) throw new Error("health unavailable")
        return response.json()
      }
      let result = await request(validate)
      if (!validate && autoCheck && (result.status === "NOT_CHECKED" || result.stale)) result = await request(true)
      if (token === sequence.current) setHealth(result)
      if (validate) window.dispatchEvent(new Event("qfs-credential-health-updated"))
    } catch {
      if (token === sequence.current) setHealth({ status: "CHECK_UNAVAILABLE", level: "warning", message: "检测服务不可用，暂时无法判断密钥是否有效", environment: mode, checkedAt: null, retCode: null, stale: true })
    } finally {
      if (token === sequence.current) { pending.current = false; setBusy(false) }
    }
  }, [id, mode, autoCheck])

  useEffect(() => {
    setHealth(null)
    pending.current = false
    void load(false)
    const refresh = () => { if (!document.hidden) void load(false) }
    const timer = autoCheck ? window.setInterval(refresh, 15000) : undefined
    window.addEventListener("qfs-credentials-changed", refresh)
    window.addEventListener("qfs-credential-health-updated", refresh)
    document.addEventListener("visibilitychange", refresh)
    return () => {
      ++sequence.current
      pending.current = false
      if (timer) window.clearInterval(timer)
      window.removeEventListener("qfs-credentials-changed", refresh)
      window.removeEventListener("qfs-credential-health-updated", refresh)
      document.removeEventListener("visibilitychange", refresh)
    }
  }, [load, autoCheck])

  const color = health?.level === "error" ? "border-rose-500/40 bg-rose-500/10 text-rose-200" : health?.level === "success" ? "border-emerald-500/20 bg-emerald-500/5 text-emerald-300" : "border-amber-500/30 bg-amber-500/5 text-amber-200"
  const remainingHours = health?.expiresAt ? Math.max(0, Math.floor((new Date(health.expiresAt).getTime() - Date.now()) / 3600000)) : null
  return <div role={health?.level === "error" ? "alert" : "status"} data-testid={`credential-health-${id}`} className={`flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2 text-xs ${color}`}>
    <div>
      <span className="font-medium">{mode === "DEMO" ? "Demo 模拟盘" : "Real 实盘"}密钥：{health?.message ?? "正在读取检测状态…"}</span>
      {health?.retCode != null && health.retCode !== 0 && <span className="ml-2">错误码 {health.retCode}</span>}
      {health?.checkedAt && <div className="mt-1 opacity-70">最近检测：{new Date(health.checkedAt).toLocaleString("zh-CN", { hour12: false })}{health.stale ? "（结果已陈旧）" : ""}</div>}
      {health?.expiresAt && <div className="mt-1">到期时间：{new Date(health.expiresAt).toLocaleString("zh-CN", { hour12: false })}（剩余约 {remainingHours} 小时）</div>}
      {health?.remainingDays === 0 && <div className="mt-1 opacity-70">Bybit 剩余天数显示为 0；是否到期以精确时间为准。</div>}
      {(health?.readOnly === true || health?.tradePermissionConfigured === false) && <div className="mt-1">该密钥未配置合约下单权限。</div>}
    </div>
    <button type="button" disabled={busy} onClick={(event) => { event.stopPropagation(); void load(true) }} className="shrink-0 rounded border border-current/30 px-2 py-1 disabled:opacity-50">
      {busy ? "检测中…" : "重新检测"}
    </button>
  </div>
}

export default function CredentialHealthBanner() {
  const name = useTradeStore((state) => state.credentialName)
  const [selected, setSelected] = useState<{ id: number; mode: string } | null>(null)
  const [error, setError] = useState("")
  useEffect(() => {
    let active = true
    setSelected(null)
    const load = async () => {
      if (document.hidden) return
      try {
        const [list, modeResponse] = await Promise.all([fetch("/api/credentials"), fetch("/api/bybit/mode")])
        if (!list.ok || !modeResponse.ok) throw new Error("unavailable")
        const credentials: { id: number; name: string }[] = await list.json()
        const { mode } = await modeResponse.json()
        const match = credentials.find((item) => item.name === name)
        if (active) {
          setSelected(match ? { id: match.id, mode } : null)
          setError(match ? "" : "当前交易凭证不存在，请到凭证管理选择或添加；未进行密钥有效性验证")
        }
      } catch { if (active) setError("无法读取当前交易凭证状态，请检查后端连接") }
    }
    void load()
    const timer = window.setInterval(load, 15000)
    window.addEventListener("qfs-credentials-changed", load)
    return () => { active = false; window.clearInterval(timer); window.removeEventListener("qfs-credentials-changed", load) }
  }, [name])
  return <div className="border-b border-zinc-800 px-6 py-3">
    <div className="mb-1 flex justify-between text-xs text-zinc-400"><span>当前交易凭证：{name}</span><Link to="/credentials" className="underline">凭证管理</Link></div>
    {error ? <div role="alert" className="text-xs text-amber-300">{error}</div> : selected ? <CredentialHealthStatus key={`${selected.id}:${selected.mode}`} id={selected.id} mode={selected.mode} autoCheck /> : <div className="text-xs text-zinc-500">正在读取凭证状态…</div>}
  </div>
}
