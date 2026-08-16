import { useCallback, useEffect, useState } from "react"
import { Globe, Network, Save, Trash2, Loader2, CheckCircle2, AlertTriangle, KeyRound, Bot, Zap, Send } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../components/ui/card"
import { Button } from "../components/ui/button"
import { Input } from "../components/ui/input"
import { Label } from "../components/ui/label"
import { Badge } from "../components/ui/badge"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select"
import { useTradeStore } from "../store/tradeStore"

interface ProxyConfig {
  type: string
  host: string
  port: number
  username: string | null
  password: string | null
  enabled: boolean
  useForAi?: boolean | null
}

interface CredentialSummary {
  id: number
  name: string
  maskedApiKey: string
}

interface AiConfigState {
  baseUrl: string
  apiKey: string
  model: string
  enabled: boolean
  watchSymbols: string
  scanIntervalMinutes: number
  changeThresholdPct: number
  newsKeywordOn: boolean
  leverage: number
  minMovePct: number
  strategyNote: string
}

const DEFAULT_AI: AiConfigState = {
  baseUrl: "https://api.openai.com/v1",
  apiKey: "",
  model: "gpt-4o-mini",
  enabled: false,
  watchSymbols: "BTCUSDT,ETHUSDT",
  scanIntervalMinutes: 10,
  changeThresholdPct: 2,
  newsKeywordOn: true,
  leverage: 100,
  minMovePct: 0.1,
  strategyNote: "",
}

const AI_PRESETS = [
  { label: "OpenAI", baseUrl: "https://api.openai.com/v1", model: "gpt-4o-mini" },
  { label: "智谱 GLM", baseUrl: "https://open.bigmodel.cn/api/paas/v4", model: "glm-4-flash" },
  { label: "DeepSeek", baseUrl: "https://api.deepseek.com/v1", model: "deepseek-chat" },
  { label: "Groq", baseUrl: "https://api.groq.com/openai/v1", model: "llama-3.3-70b-versatile" },
]

const DEFAULT_PROXY: ProxyConfig = { type: "HTTP", host: "", port: 7890, username: null, password: null, enabled: false, useForAi: true }

async function fetchProxy(): Promise<ProxyConfig | null> {
  const res = await fetch("/api/proxy")
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

async function saveProxy(body: ProxyConfig): Promise<boolean> {
  const res = await fetch("/api/proxy", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  return res.ok
}

async function deleteProxy(): Promise<boolean> {
  const res = await fetch("/api/proxy", { method: "DELETE" })
  return res.ok || res.status === 204
}

async function fetchMode(): Promise<string> {
  const res = await fetch("/api/bybit/mode")
  if (!res.ok) return "DEMO"
  const json = await res.json()
  return json.mode || "DEMO"
}

async function setMode(mode: string): Promise<string> {
  const res = await fetch("/api/bybit/mode", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const json = await res.json()
  return json.mode
}

async function fetchCredentials(): Promise<CredentialSummary[]> {
  const res = await fetch("/api/credentials")
  if (!res.ok) return []
  return res.json()
}

async function fetchAiConfig(): Promise<AiConfigState & { apiKeySet: boolean }> {
  const res = await fetch("/api/ai/config")
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

async function saveAiConfig(body: AiConfigState): Promise<Response> {
  return fetch("/api/ai/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
}

function SettingsPage() {
  const [mode, setModeState] = useState<string>("DEMO")
  const [modeBusy, setModeBusy] = useState(false)
  const [modeError, setModeError] = useState("")

  const [proxy, setProxy] = useState<ProxyConfig>(DEFAULT_PROXY)
  const [proxyLoaded, setProxyLoaded] = useState(false)
  const [proxySaving, setProxySaving] = useState(false)
  const [proxyMessage, setProxyMessage] = useState<{ ok: boolean; text: string } | null>(null)
  // 当前交易凭证（与交易页共享）
  const credentialName = useTradeStore((s) => s.credentialName)
  const setCredentialName = useTradeStore((s) => s.setCredentialName)
  const [credentialList, setCredentialList] = useState<CredentialSummary[]>([])
  const [credentialLoaded, setCredentialLoaded] = useState(false)

  // AI 服务与盯盘配置
  const [ai, setAi] = useState<AiConfigState>(DEFAULT_AI)
  const [aiKeySet, setAiKeySet] = useState(false)
  const [aiSaving, setAiSaving] = useState(false)
  const [aiMessage, setAiMessage] = useState<{ ok: boolean; text: string } | null>(null)

  // Telegram 机器人
  const [tg, setTg] = useState<{ tokenSet: boolean; maskedToken: string; chatId: string; enabled: boolean; bound: boolean }>({ tokenSet: false, maskedToken: "", chatId: "", enabled: false, bound: false })
  const [tgForm, setTgForm] = useState<{ token: string; chatId: string; enabled: boolean }>({ token: "", chatId: "", enabled: false })
  const [tgSaving, setTgSaving] = useState(false)
  const [tgMessage, setTgMessage] = useState<{ ok: boolean; text: string } | null>(null)

  const load = useCallback(async () => {
    try {
      setModeState(await fetchMode())
    } catch {
      setModeState("DEMO")
    }
    try {
      const p = await fetchProxy()
      setProxy(p ?? DEFAULT_PROXY)
    } catch {
      setProxyMessage({ ok: false, text: "加载代理配置失败" })
    } finally {
      setProxyLoaded(true)
    }
    try {
      setCredentialList(await fetchCredentials())
    } finally {
      setCredentialLoaded(true)
    }
    try {
      const cfg = await fetchAiConfig()
      setAiKeySet(cfg.apiKeySet)
      setAi({
        baseUrl: cfg.baseUrl,
        apiKey: "",
        model: cfg.model,
        enabled: cfg.enabled,
        watchSymbols: cfg.watchSymbols,
        scanIntervalMinutes: cfg.scanIntervalMinutes,
        changeThresholdPct: cfg.changeThresholdPct,
        newsKeywordOn: cfg.newsKeywordOn,
        leverage: cfg.leverage ?? 100,
        minMovePct: cfg.minMovePct ?? 0.1,
        strategyNote: cfg.strategyNote ?? "",
      })
    } catch {
      // AI 配置加载失败保持默认
    }
    try {
      const t = await fetch("/api/tg/config").then((r) => r.json())
      setTg(t)
      setTgForm({ token: "", chatId: t.chatId ?? "", enabled: t.enabled })
    } catch {
      // TG 配置加载失败保持默认
    }
  }, [])

  const saveTg = async () => {
    setTgSaving(true)
    setTgMessage(null)
    try {
      const res = await fetch("/api/tg/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ botToken: tgForm.token, chatId: tgForm.chatId, enabled: tgForm.enabled }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const saved = await res.json()
      setTg(saved)
      setTgForm((f) => ({ ...f, token: "" }))
      setTgMessage({ ok: true, text: saved.enabled ? "TG 配置已保存，轮询已生效" : "TG 配置已保存（机器人未启用）" })
    } catch (err) {
      setTgMessage({ ok: false, text: err instanceof Error ? err.message : "保存失败" })
    } finally {
      setTgSaving(false)
    }
  }

  const testTg = async () => {
    setTgMessage(null)
    try {
      const res = await fetch("/api/tg/test", { method: "POST" })
      const json = await res.json().catch(() => null)
      setTgMessage(res.ok && json?.ok
        ? { ok: true, text: "测试消息已发送，去 Telegram 查看" }
        : { ok: false, text: json?.message || `发送失败 HTTP ${res.status}` })
    } catch {
      setTgMessage({ ok: false, text: "网络错误" })
    }
  }

  const handleSaveAi = async (e: React.FormEvent) => {
    e.preventDefault()
    setAiSaving(true)
    setAiMessage(null)
    try {
      const res = await saveAiConfig(ai)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const saved = await res.json()
      setAiKeySet(saved.apiKeySet)
      setAi((a) => ({ ...a, apiKey: "" }))
      setAiMessage({ ok: true, text: "AI 配置已保存" })
    } catch (err) {
      setAiMessage({ ok: false, text: err instanceof Error ? err.message : "保存失败" })
    } finally {
      setAiSaving(false)
    }
  }

  useEffect(() => {
    load()
  }, [load])

  const handleSwitchMode = async (next: string) => {
    setModeBusy(true)
    setModeError("")
    try {
      const m = await setMode(next)
      setModeState(m)
    } catch {
      setModeError("切换失败，请确认后端已启动")
    } finally {
      setModeBusy(false)
    }
  }

  const handleSaveProxy = async (e: React.FormEvent) => {
    e.preventDefault()
    setProxySaving(true)
    setProxyMessage(null)
    const ok = await saveProxy(proxy)
    setProxySaving(false)
    setProxyMessage(ok ? { ok: true, text: "代理配置已保存并即时生效" } : { ok: false, text: "保存失败" })
  }

  const handleDeleteProxy = async () => {
    if (!window.confirm("确认清空代理配置？之后请求将走直连。")) return
    const ok = await deleteProxy()
    if (ok) {
      setProxy(DEFAULT_PROXY)
      setProxyMessage({ ok: true, text: "代理已清空，请求将直连" })
    }
  }

  return (
    <div className="p-6">
      <header className="mb-6">
        <h1 className="text-xl font-semibold">设置</h1>
        <p className="mt-1 text-sm text-zinc-500">交易模式与代理配置</p>
      </header>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="border-zinc-800 bg-zinc-900/40 h-fit">
          <CardHeader>
            <CardTitle className="text-sm flex items-center gap-2">
              <KeyRound className="h-4 w-4 text-emerald-400" />
              交易凭证
            </CardTitle>
            <CardDescription className="text-xs">交易页使用的凭证，切换后立即生效</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {!credentialLoaded ? (
              <div className="flex items-center gap-2 py-2 text-sm text-zinc-500">
                <Loader2 className="h-4 w-4 animate-spin" /> 加载中...
              </div>
            ) : credentialList.length === 0 ? (
              <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2.5 text-xs text-amber-400">
                暂无凭证，请先到「凭证管理」页添加 API 密钥。
              </div>
            ) : (
              <>
                <div className="flex items-center gap-3 rounded-lg border border-zinc-800 bg-zinc-950/60 p-4">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-emerald-500/15 ring-1 ring-inset ring-emerald-500/30">
                    <KeyRound className="h-5 w-5 text-emerald-400" />
                  </div>
                  <div className="flex-1">
                    <p className="text-sm font-medium">当前凭证</p>
                    <p className="truncate text-xs text-zinc-500" title={credentialName}>{credentialName}</p>
                  </div>
                  <Badge className="bg-emerald-500/15 text-emerald-400 border-emerald-500/30">使用中</Badge>
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs text-zinc-400">切换凭证</Label>
                  <Select value={credentialName} onValueChange={(v) => v && setCredentialName(v)}>
                    <SelectTrigger className="bg-zinc-950/60 border-zinc-800">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {credentialList.map((c) => (
                        <SelectItem key={c.id} value={c.name}>
                          {c.name}（{c.maskedApiKey}）
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </>
            )}
          </CardContent>
        </Card>

        <Card className="border-zinc-800 bg-zinc-900/40 h-fit">
          <CardHeader>
            <CardTitle className="text-sm flex items-center gap-2">
              <Globe className="h-4 w-4 text-emerald-400" />
              交易模式
            </CardTitle>
            <CardDescription className="text-xs">切换 Bybit API 端点，实时生效</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center gap-3 rounded-lg border border-zinc-800 bg-zinc-950/60 p-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-emerald-500/15 ring-1 ring-inset ring-emerald-500/30">
                <Globe className="h-5 w-5 text-emerald-400" />
              </div>
              <div className="flex-1">
                <p className="text-sm font-medium">当前模式</p>
                <p className="text-xs text-zinc-500">
                  {mode === "DEMO" ? "虚拟盘（api-demo.bybit.com）" : "实盘（api.bybit.com）"}
                </p>
              </div>
              <Badge className={mode === "DEMO" ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" : "bg-rose-500/15 text-rose-400 border-rose-500/30"}>
                {mode}
              </Badge>
            </div>
            <div className="flex gap-2">
              <Button
                variant={mode === "DEMO" ? "default" : "outline"}
                className="flex-1"
                disabled={modeBusy || mode === "DEMO"}
                onClick={() => handleSwitchMode("DEMO")}
              >
                {modeBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                切换虚拟盘
              </Button>
              <Button
                variant={mode === "REAL" ? "destructive" : "outline"}
                className="flex-1"
                disabled={modeBusy || mode === "REAL"}
                onClick={() => handleSwitchMode("REAL")}
              >
                {modeBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <AlertTriangle className="h-4 w-4" />}
                切换实盘
              </Button>
            </div>
            {modeError && <p className="text-xs text-red-400">{modeError}</p>}
            <p className="text-xs text-zinc-600">⚠️ 实盘模式使用真实资金，下单前请仔细确认。</p>
          </CardContent>
        </Card>

        <Card className="border-zinc-800 bg-zinc-900/40 h-fit">
          <CardHeader>
            <CardTitle className="text-sm flex items-center gap-2">
              <Network className="h-4 w-4 text-emerald-400" />
              代理配置
            </CardTitle>
            <CardDescription className="text-xs">HTTP / SOCKS 代理，保存后即时生效</CardDescription>
          </CardHeader>
          <CardContent>
            {!proxyLoaded ? (
              <div className="flex items-center justify-center gap-2 py-8 text-sm text-zinc-500">
                <Loader2 className="h-4 w-4 animate-spin" /> 加载中...
              </div>
            ) : (
              <form onSubmit={handleSaveProxy} className="space-y-4">
                <div className="grid grid-cols-[120px_1fr] gap-3">
                  <div className="space-y-1.5">
                    <Label className="text-xs text-zinc-400">类型</Label>
                    <Select
                      value={proxy.type}
                      onValueChange={(v) => v && setProxy({ ...proxy, type: v })}
                    >
                      <SelectTrigger className="bg-zinc-950/60 border-zinc-800">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="HTTP">HTTP</SelectItem>
                        <SelectItem value="SOCKS">SOCKS</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="proxy-host" className="text-xs text-zinc-400">主机</Label>
                    <Input
                      id="proxy-host"
                      placeholder="如 127.0.0.1"
                      value={proxy.host}
                      onChange={(e) => setProxy({ ...proxy, host: e.target.value })}
                      className="bg-zinc-950/60 border-zinc-800"
                    />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="proxy-port" className="text-xs text-zinc-400">端口</Label>
                    <Input
                      id="proxy-port"
                      type="number"
                      min={1}
                      max={65535}
                      value={proxy.port}
                      onChange={(e) => setProxy({ ...proxy, port: Number(e.target.value) })}
                      className="bg-zinc-950/60 border-zinc-800"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="proxy-user" className="text-xs text-zinc-400">用户名（可选）</Label>
                    <Input
                      id="proxy-user"
                      placeholder="无需认证可留空"
                      value={proxy.username ?? ""}
                      onChange={(e) => setProxy({ ...proxy, username: e.target.value || null })}
                      className="bg-zinc-950/60 border-zinc-800"
                    />
                  </div>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="proxy-pass" className="text-xs text-zinc-400">密码（可选，加密存储）</Label>
                  <Input
                    id="proxy-pass"
                    type="password"
                    placeholder="无需认证可留空"
                    value={proxy.password ?? ""}
                    onChange={(e) => setProxy({ ...proxy, password: e.target.value || null })}
                    className="bg-zinc-950/60 border-zinc-800"
                  />
                </div>
                <label className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={proxy.enabled}
                    onChange={(e) => setProxy({ ...proxy, enabled: e.target.checked })}
                    className="h-4 w-4 rounded border-zinc-700 bg-zinc-900 accent-emerald-500"
                  />
                  启用代理
                </label>
                <label className="flex items-start gap-2 text-sm text-zinc-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={proxy.useForAi !== false}
                    onChange={(e) => setProxy({ ...proxy, useForAi: e.target.checked })}
                    className="mt-0.5 h-4 w-4 rounded border-zinc-700 bg-zinc-900 accent-emerald-500"
                  />
                  <span>
                    AI 与快讯请求也走代理
                    <span className="ml-1 text-xs text-zinc-500">
                      （关闭后仅 Bybit 走代理；用智谱/DeepSeek 等国内 AI 时建议关闭，直连更快）
                    </span>
                  </span>
                </label>
                {proxyMessage && (
                  <p className={`text-xs ${proxyMessage.ok ? "text-emerald-400" : "text-red-400"}`}>{proxyMessage.text}</p>
                )}
                <div className="flex gap-2">
                  <Button type="submit" className="flex-1" disabled={proxySaving}>
                    {proxySaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                    保存代理
                  </Button>
                  <Button type="button" variant="outline" onClick={handleDeleteProxy} className="text-zinc-400">
                    <Trash2 className="h-4 w-4" />
                    清空
                  </Button>
                </div>
              </form>
            )}
          </CardContent>
        </Card>

        <Card className="border-zinc-800 bg-zinc-900/40 h-fit lg:col-span-2">
          <CardHeader>
            <CardTitle className="text-sm flex items-center gap-2">
              <Bot className="h-4 w-4 text-indigo-400" />
              AI 服务与自动盯盘
            </CardTitle>
            <CardDescription className="text-xs">
              OpenAI 兼容接口（OpenAI / 智谱 / DeepSeek / Groq / 本地 Ollama 均可），Key 加密存储
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSaveAi} className="space-y-4">
              <div className="flex flex-wrap gap-1.5">
                {AI_PRESETS.map((p) => (
                  <button
                    key={p.label}
                    type="button"
                    onClick={() => setAi((a) => ({ ...a, baseUrl: p.baseUrl, model: p.model }))}
                    className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
                      ai.baseUrl === p.baseUrl
                        ? "bg-indigo-500/20 text-indigo-300 ring-1 ring-inset ring-indigo-500/40"
                        : "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
                    }`}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
              <div className="grid gap-3 md:grid-cols-3">
                <div className="space-y-1.5">
                  <Label htmlFor="ai-url" className="text-xs text-zinc-400">Base URL</Label>
                  <Input
                    id="ai-url"
                    value={ai.baseUrl}
                    onChange={(e) => setAi({ ...ai, baseUrl: e.target.value })}
                    className="bg-zinc-950/60 border-zinc-800 font-mono text-xs"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="ai-model" className="text-xs text-zinc-400">模型</Label>
                  <Input
                    id="ai-model"
                    value={ai.model}
                    onChange={(e) => setAi({ ...ai, model: e.target.value })}
                    className="bg-zinc-950/60 border-zinc-800 font-mono text-xs"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="ai-key" className="text-xs text-zinc-400">
                    API Key {aiKeySet && <span className="text-emerald-500">（已配置，留空则不修改）</span>}
                  </Label>
                  <Input
                    id="ai-key"
                    type="password"
                    placeholder={aiKeySet ? "••••••••" : "sk-..."}
                    value={ai.apiKey}
                    onChange={(e) => setAi({ ...ai, apiKey: e.target.value })}
                    className="bg-zinc-950/60 border-zinc-800 font-mono text-xs"
                  />
                </div>
              </div>
              <div className="rounded-xl border border-zinc-800 bg-zinc-950/40 p-4 space-y-4">
                <label className="flex items-center gap-2 text-sm text-zinc-200 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={ai.enabled}
                    onChange={(e) => setAi({ ...ai, enabled: e.target.checked })}
                    className="h-4 w-4 rounded border-zinc-700 bg-zinc-900 accent-indigo-500"
                  />
                  开启自动盯盘
                  <span className="text-xs text-zinc-500">
                    （异动触发才调用 AI，按扫描间隔检查，token 消耗可控）
                  </span>
                </label>
                <div className="grid gap-3 md:grid-cols-4">
                  <div className="space-y-1.5 md:col-span-2">
                    <Label htmlFor="ai-symbols" className="text-xs text-zinc-400">盯盘品种（逗号分隔）</Label>
                    <Input
                      id="ai-symbols"
                      value={ai.watchSymbols}
                      onChange={(e) => setAi({ ...ai, watchSymbols: e.target.value })}
                      className="bg-zinc-950/60 border-zinc-800 font-mono text-xs"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="ai-interval" className="text-xs text-zinc-400">扫描间隔（分钟）</Label>
                    <Input
                      id="ai-interval"
                      type="number"
                      min={1}
                      max={1440}
                      value={ai.scanIntervalMinutes}
                      onChange={(e) => setAi({ ...ai, scanIntervalMinutes: Number(e.target.value) })}
                      className="bg-zinc-950/60 border-zinc-800"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="ai-threshold" className="text-xs text-zinc-400">异动阈值（%）</Label>
                    <Input
                      id="ai-threshold"
                      type="number"
                      min={0.5}
                      max={50}
                      step={0.5}
                      value={ai.changeThresholdPct}
                      onChange={(e) => setAi({ ...ai, changeThresholdPct: Number(e.target.value) })}
                      className="bg-zinc-950/60 border-zinc-800"
                    />
                  </div>
                </div>
                <label className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={ai.newsKeywordOn}
                    onChange={(e) => setAi({ ...ai, newsKeywordOn: e.target.checked })}
                    className="h-4 w-4 rounded border-zinc-700 bg-zinc-900 accent-indigo-500"
                  />
                  快讯关键词也触发分析（暴跌/监管/ETF 等命中时）
                </label>
              </div>
              <div className="rounded-xl border border-indigo-500/20 bg-indigo-500/5 p-4 space-y-4">
                <div className="flex items-center gap-2">
                  <Zap className="h-4 w-4 text-amber-400" />
                  <p className="text-sm font-medium text-zinc-200">策略偏好</p>
                  <span className="text-xs text-zinc-500">（注入 AI 提示词，让研判贴合你的风格）</span>
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  <div className="space-y-1.5">
                    <Label htmlFor="ai-leverage" className="text-xs text-zinc-400">惯用杠杆（倍）</Label>
                    <Input
                      id="ai-leverage"
                      type="number"
                      min={1}
                      max={200}
                      value={ai.leverage}
                      onChange={(e) => setAi({ ...ai, leverage: Number(e.target.value) })}
                      className="bg-zinc-950/60 border-zinc-800"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="ai-minmove" className="text-xs text-zinc-400">
                      盈利目标下限（%）
                    </Label>
                    <Input
                      id="ai-minmove"
                      type="number"
                      min={0.01}
                      max={10}
                      step={0.01}
                      value={ai.minMovePct}
                      onChange={(e) => setAi({ ...ai, minMovePct: Number(e.target.value) })}
                      className="bg-zinc-950/60 border-zinc-800"
                    />
                    <p className="text-[11px] leading-relaxed text-zinc-500">
                      止盈目标距入场至少该幅度，用于覆盖手续费
                      （Bybit taker 往返约 0.11%，设 0.12 以上才有利润空间）
                    </p>
                  </div>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="ai-note" className="text-xs text-zinc-400">
                    策略备注（可选，随每次研判发给 AI）
                  </Label>
                  <textarea
                    id="ai-note"
                    value={ai.strategyNote}
                    onChange={(e) => setAi({ ...ai, strategyNote: e.target.value })}
                    placeholder="如：只在流动性好的时段交易；重要数据公布前后不下单；胜率优先，宁可错过…"
                    rows={2}
                    maxLength={1000}
                    className="w-full rounded-lg border border-zinc-800 bg-zinc-950/60 px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-indigo-500/50 focus:outline-none"
                  />
                </div>
                <p className="text-[11px] leading-relaxed text-zinc-500">
                  {ai.leverage} 倍杠杆下，价格每变动 {ai.minMovePct}% 对应保证金盈亏约
                  {" "}{(ai.leverage * ai.minMovePct).toFixed(1)}%——AI 以「损失可控」为先：
                  方向倾向成立即可出手，止损放结构失效位并标注单笔最大亏损，止盈至少覆盖手续费，
                  另给动态管理预案（跌破离场 / 守住持有）。
                </p>
              </div>
              {aiMessage && (
                <p className={`text-xs ${aiMessage.ok ? "text-emerald-400" : "text-red-400"}`}>
                  {aiMessage.text}
                </p>
              )}
              <Button type="submit" disabled={aiSaving}>
                {aiSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                保存 AI 配置
              </Button>
            </form>
          </CardContent>
        </Card>

        <Card className="border-zinc-800 bg-zinc-900/40 h-fit lg:col-span-2">
          <CardHeader>
            <CardTitle className="text-sm flex items-center gap-2">
              <Send className="h-4 w-4 text-sky-400" />
              Telegram 机器人
            </CardTitle>
            <CardDescription className="text-xs">
              公网任意环境接收告警推送、远程下指令；长轮询模式无需公网 IP，token 加密存储
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="rounded-lg border border-zinc-800 bg-zinc-950/40 p-3 text-xs leading-relaxed text-zinc-400">
                <p className="text-zinc-300">三步接入：</p>
                <p>1. Telegram 里找 <span className="font-mono text-sky-300">@BotFather</span> 发 <span className="font-mono">/newbot</span>，拿到 token 填到下面并保存</p>
                <p>2. 给你的机器人发一条 <span className="font-mono">/start</span>（绑定你的账号，之后只有你能指挥它）</p>
                <p>3. 回来点「发送测试消息」验证</p>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="tg-token" className="text-xs text-zinc-400">
                    Bot Token {tg.tokenSet && <span className="text-emerald-500">（已配置，留空则不修改）</span>}
                  </Label>
                  <Input
                    id="tg-token"
                    type="password"
                    placeholder={tg.tokenSet ? tg.maskedToken : "123456:ABC-DEF..."}
                    value={tgForm.token}
                    onChange={(e) => setTgForm({ ...tgForm, token: e.target.value })}
                    className="bg-zinc-950/60 border-zinc-800 font-mono text-xs"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="tg-chat" className="text-xs text-zinc-400">
                    Chat ID {tg.bound ? <span className="text-emerald-500">（已绑定）</span> : <span className="text-amber-500">（给机器人发 /start 自动绑定）</span>}
                  </Label>
                  <Input
                    id="tg-chat"
                    value={tgForm.chatId}
                    onChange={(e) => setTgForm({ ...tgForm, chatId: e.target.value })}
                    placeholder="自动捕获，无需手填"
                    className="bg-zinc-950/60 border-zinc-800 font-mono text-xs"
                  />
                </div>
              </div>
              <label className="flex items-start gap-2 text-sm text-zinc-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={tg.enabled}
                  onChange={(e) => setTgForm({ ...tgForm, enabled: e.target.checked })}
                  className="mt-0.5 h-4 w-4 rounded border-zinc-700 bg-zinc-900 accent-sky-500"
                />
                <span>
                  启用机器人（轮询指令 + 告警/结算推送）
                  <span className="ml-1 text-xs text-zinc-500">
                    （同一 token 只能一处启用：Pi 与本机 dev 勿同时开，否则 TG 返回 409 冲突）
                  </span>
                </span>
              </label>
              {tgMessage && (
                <p className={`text-xs ${tgMessage.ok ? "text-emerald-400" : "text-red-400"}`}>{tgMessage.text}</p>
              )}
              <div className="flex gap-2">
                <Button onClick={saveTg} disabled={tgSaving} className="flex-1">
                  {tgSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                  保存 TG 配置
                </Button>
                <Button variant="outline" onClick={testTg} disabled={!tg.tokenSet || !tg.bound}>
                  <Send className="h-4 w-4" />
                  发送测试消息
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

export default SettingsPage
