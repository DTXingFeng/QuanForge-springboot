import { Bot } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "./card"
import { cn } from "../../lib/utils"

interface KpiData {
  label: string
  value: string
  /** 值颜色类名 */
  tone?: string
  /** 附加说明 */
  hint?: string
}

/**
 * 统计 KPI 卡片行（参考 21st.dev Stats 组件风格，深色终端配色）。
 */
export function KpiRow({ items, className }: { items: KpiData[]; className?: string }) {
  return (
    <div className={cn("grid gap-4 sm:grid-cols-2 lg:grid-cols-4", className)}>
      {items.map((k) => (
        <Card key={k.label} className="border-zinc-800 bg-zinc-900/40">
          <CardContent className="p-4">
            <p className="text-xs text-zinc-500">{k.label}</p>
            <p className={cn("mt-1.5 font-mono text-xl font-semibold", k.tone || "text-zinc-100")}>
              {k.value}
            </p>
            {k.hint && <p className="mt-0.5 text-[11px] text-zinc-600">{k.hint}</p>}
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

interface AiStatusCardProps {
  enabled: boolean
  modelName: string
  watchSymbols: string
  scanInterval: number
  className?: string
}

/** AI 盯盘状态卡（页头右侧） */
export function AiStatusCard({ enabled, modelName, watchSymbols, scanInterval, className }: AiStatusCardProps) {
  return (
    <Card className={cn("border-zinc-800 bg-zinc-900/40", className)}>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Bot className="size-4 text-indigo-400" />
          AI 盯盘状态
          <span
            className={cn(
              "ml-auto rounded px-1.5 py-0.5 text-[10px] font-medium ring-1 ring-inset",
              enabled
                ? "bg-emerald-500/15 text-emerald-400 ring-emerald-500/30"
                : "bg-zinc-500/15 text-zinc-400 ring-zinc-500/30",
            )}
          >
            {enabled ? "运行中" : "未开启"}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-1 pt-0">
        <p className="font-mono text-xs text-zinc-400">{modelName || "-"}</p>
        <p className="text-[11px] text-zinc-600">
          盯盘 {watchSymbols || "-"} · 每 {scanInterval || "-"} 分钟 · 建议前先查持仓
        </p>
      </CardContent>
    </Card>
  )
}
