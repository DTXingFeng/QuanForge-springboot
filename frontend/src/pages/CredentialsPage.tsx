import { useCallback, useEffect, useState } from "react"
import { KeyRound, Plus, Trash2, Eye, EyeOff, Copy, Check, ShieldCheck, Loader2 } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../components/ui/card"
import { Button } from "../components/ui/button"
import { Input } from "../components/ui/input"
import { Label } from "../components/ui/label"
import { Badge } from "../components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table"
import { useTradeStore } from "../store/tradeStore"

interface CredentialSummary {
  id: number
  name: string
  maskedApiKey: string
  createdAt: string
  updatedAt: string
}

interface CredentialDetail {
  id: number
  name: string
  apiKey: string
  apiSecret: string
  createdAt: string
  updatedAt: string
}

interface ApiError {
  status?: number
  detail?: string
}

async function fetchList(): Promise<CredentialSummary[]> {
  const res = await fetch("/api/credentials")
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

async function fetchDetail(id: number): Promise<CredentialDetail> {
  const res = await fetch(`/api/credentials/${id}`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

async function createCredential(body: { name: string; apiKey: string; apiSecret: string }): Promise<ApiError | null> {
  const res = await fetch("/api/credentials", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  if (res.ok) return null
  const data = await res.json().catch(() => ({}))
  return { status: res.status, detail: data.detail }
}

async function removeCredential(id: number): Promise<boolean> {
  const res = await fetch(`/api/credentials/${id}`, { method: "DELETE" })
  return res.ok || res.status === 204
}

const formatTime = (iso: string): string => {
  if (!iso) return "-"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString("zh-CN", { hour12: false })
}

function CredentialsPage() {
  const [list, setList] = useState<CredentialSummary[] | null>(null)
  const [loadError, setLoadError] = useState("")
  const [detail, setDetail] = useState<CredentialDetail | null>(null)
  const [showSecret, setShowSecret] = useState(false)
  const [copied, setCopied] = useState("")
  const credentialName = useTradeStore((s) => s.credentialName)

  const [name, setName] = useState("")
  const [apiKey, setApiKey] = useState("")
  const [apiSecret, setApiSecret] = useState("")
  const [formError, setFormError] = useState("")
  const [submitting, setSubmitting] = useState(false)

  const load = useCallback(async () => {
    try {
      setList(await fetchList())
      setLoadError("")
    } catch {
      setLoadError("加载凭证列表失败，请确认后端已启动")
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const openDetail = async (id: number) => {
    try {
      const d = await fetchDetail(id)
      setDetail(d)
      setShowSecret(false)
      setCopied("")
    } catch {
      setFormError("加载详情失败")
    }
  }

  const closeDetail = () => {
    setDetail(null)
    setShowSecret(false)
  }

  const copyText = async (key: string, text: string) => {
    await navigator.clipboard.writeText(text)
    setCopied(key)
    setTimeout(() => setCopied(""), 1500)
  }

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    setFormError("")
    if (!name.trim() || !apiKey.trim() || !apiSecret.trim()) {
      setFormError("请完整填写名称、API Key 与 API Secret")
      return
    }
    setSubmitting(true)
    const err = await createCredential({ name: name.trim(), apiKey: apiKey.trim(), apiSecret: apiSecret.trim() })
    setSubmitting(false)
    if (err) {
      setFormError(err.detail || (err.status === 409 ? "同名凭证已存在" : `创建失败（HTTP ${err.status}）`))
      return
    }
    setName("")
    setApiKey("")
    setApiSecret("")
    load()
  }

  const handleDelete = async (id: number, credentialName: string) => {
    if (!window.confirm(`确认删除凭证「${credentialName}」？此操作不可恢复。`)) return
    const ok = await removeCredential(id)
    if (ok) load()
  }

  return (
    <div className="p-6">
      <header className="mb-6">
        <h1 className="text-xl font-semibold">凭证管理</h1>
        <p className="mt-1 text-sm text-zinc-500">管理交易所 API 密钥，AES-256 加密存储</p>
      </header>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
        <Card className="border-zinc-800 bg-zinc-900/40">
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <div>
              <CardTitle className="text-sm flex items-center gap-2">
                <KeyRound className="h-4 w-4 text-emerald-400" />
                凭证列表
              </CardTitle>
              <CardDescription className="text-xs">API Key 仅展示脱敏值，点击行查看完整信息</CardDescription>
            </div>
          </CardHeader>
          <CardContent>
            {loadError ? (
              <p className="py-8 text-center text-sm text-red-400">{loadError}</p>
            ) : list === null ? (
              <div className="flex items-center justify-center gap-2 py-8 text-sm text-zinc-500">
                <Loader2 className="h-4 w-4 animate-spin" /> 加载中...
              </div>
            ) : list.length === 0 ? (
              <div className="py-8 text-center">
                <ShieldCheck className="mx-auto mb-2 h-8 w-8 text-zinc-600" />
                <p className="text-sm text-zinc-500">暂无凭证，请在右侧添加</p>
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow className="border-zinc-800">
                    <TableHead className="text-xs text-zinc-400">名称</TableHead>
                    <TableHead className="text-xs text-zinc-400">API Key（脱敏）</TableHead>
                    <TableHead className="text-xs text-zinc-400">更新时间</TableHead>
                    <TableHead className="text-xs text-zinc-400 text-right">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {list.map((c) => (
                    <TableRow key={c.id} className="border-zinc-800/60 cursor-pointer hover:bg-zinc-800/30" onClick={() => openDetail(c.id)}>
                      <TableCell className="font-medium">
                        <span className="inline-flex items-center gap-2">
                          {c.name}
                          {c.name === credentialName && <Badge variant="outline" className="text-[10px] text-emerald-400 border-emerald-500/30">使用中</Badge>}
                        </span>
                      </TableCell>
                      <TableCell className="font-mono text-xs text-zinc-400">{c.maskedApiKey}</TableCell>
                      <TableCell className="text-xs text-zinc-500">{formatTime(c.updatedAt)}</TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          className="text-zinc-500 hover:text-red-400"
                          onClick={(e) => {
                            e.stopPropagation()
                            handleDelete(c.id, c.name)
                          }}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <Card className="border-zinc-800 bg-zinc-900/40 h-fit">
          <CardHeader>
            <CardTitle className="text-sm flex items-center gap-2">
              <Plus className="h-4 w-4 text-emerald-400" />
              新增凭证
            </CardTitle>
            <CardDescription className="text-xs">名称需唯一，用于交易时指定使用哪套密钥</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleCreate} className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="cred-name" className="text-xs text-zinc-400">名称</Label>
                <Input
                  id="cred-name"
                  placeholder="如 my-demo-bybit"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="bg-zinc-950/60 border-zinc-800"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="cred-key" className="text-xs text-zinc-400">API Key</Label>
                <Input
                  id="cred-key"
                  placeholder="粘贴 API Key"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  className="bg-zinc-950/60 border-zinc-800 font-mono text-xs"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="cred-secret" className="text-xs text-zinc-400">API Secret</Label>
                <Input
                  id="cred-secret"
                  type="password"
                  placeholder="粘贴 API Secret"
                  value={apiSecret}
                  onChange={(e) => setApiSecret(e.target.value)}
                  className="bg-zinc-950/60 border-zinc-800 font-mono text-xs"
                />
              </div>
              {formError && <p className="text-xs text-red-400">{formError}</p>}
              <Button type="submit" className="w-full" disabled={submitting}>
                {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                {submitting ? "保存中..." : "保存凭证"}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>

      {detail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={closeDetail}>
          <Card className="w-full max-w-lg border-zinc-700 bg-zinc-900" onClick={(e) => e.stopPropagation()}>
            <CardHeader className="flex-row items-center justify-between space-y-0">
              <div>
                <CardTitle className="text-sm flex items-center gap-2">
                  <KeyRound className="h-4 w-4 text-emerald-400" />
                  凭证详情：{detail.name}
                </CardTitle>
                <CardDescription className="text-xs">完整密钥仅在此显示，不会再次展示</CardDescription>
              </div>
              <Button variant="ghost" size="icon-sm" onClick={closeDetail} className="text-zinc-400 hover:text-zinc-200">✕</Button>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1.5">
                <Label className="text-xs text-zinc-400">API Key</Label>
                <div className="flex items-center gap-2">
                  <code className="flex-1 truncate rounded-lg border border-zinc-800 bg-zinc-950/60 px-3 py-2 font-mono text-xs text-zinc-300">{detail.apiKey}</code>
                  <Button variant="outline" size="sm" onClick={() => copyText("key", detail.apiKey)}>
                    {copied === "key" ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
                  </Button>
                </div>
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-zinc-400">API Secret</Label>
                <div className="flex items-center gap-2">
                  <code className="flex-1 truncate rounded-lg border border-zinc-800 bg-zinc-950/60 px-3 py-2 font-mono text-xs text-zinc-300">
                    {showSecret ? detail.apiSecret : "•".repeat(Math.min(24, detail.apiSecret.length))}
                  </code>
                  <Button variant="ghost" size="icon-sm" onClick={() => setShowSecret(!showSecret)} className="text-zinc-400">
                    {showSecret ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => copyText("secret", detail.apiSecret)}>
                    {copied === "secret" ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
                  </Button>
                </div>
              </div>
              <p className="text-xs text-zinc-500">
                创建时间：{formatTime(detail.createdAt)}　·　更新时间：{formatTime(detail.updatedAt)}
              </p>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}

export default CredentialsPage
