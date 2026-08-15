import { CheckCircle2, Circle, Clock } from "lucide-react"
import { cn } from "../../lib/utils"

export interface TimelineItemData {
  /** 主标题 */
  name: string
  /** 时间文本 */
  timestamp: string
  /** 是否已完成（影响节点高亮） */
  isCompleted?: boolean
  /** 附加描述行 */
  description?: string
  /** 右侧附加内容（徽章等由调用方渲染） */
  badge?: React.ReactNode
  /** 点击跳转 */
  href?: string
}

interface NewsTimelineProps {
  items: TimelineItemData[]
  className?: string
}

/**
 * 垂直时间线（改编自 21st.dev order-tracking 组件）。
 * 用于快讯流：节点 = 源图标，标题 = 快讯标题，时间戳 = 发布时间。
 */
export function NewsTimeline({ items, className }: NewsTimelineProps) {
  if (items.length === 0) {
    return <p className="text-sm text-zinc-500">暂无内容</p>
  }
  return (
    <div className={cn("w-full", className)}>
      {items.map((step, index) => {
        const row = (
          <div key={index} className="flex">
            <div className="flex flex-col items-center">
              {step.isCompleted ? (
                <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-400/80" />
              ) : (
                <Circle className="h-5 w-5 shrink-0 text-zinc-600" />
              )}
              {index < items.length - 1 && (
                <div
                  className={cn("w-[1.5px] grow", {
                    "bg-emerald-400/40": items[index + 1].isCompleted,
                    "bg-zinc-800": !items[index + 1].isCompleted,
                  })}
                />
              )}
            </div>
            <div className="ml-3 grow pb-5">
              <div className="flex items-start gap-2">
                <p className="grow text-sm font-medium leading-snug text-zinc-200">
                  {step.name}
                </p>
                {step.badge}
              </div>
              <div className="mt-1 flex items-center gap-2">
                <Clock className="size-3 text-zinc-600" />
                <p className="text-xs text-zinc-500">{step.timestamp}</p>
              </div>
              {step.description && (
                <p className="mt-1.5 text-xs leading-relaxed text-zinc-500">
                  {step.description}
                </p>
              )}
            </div>
          </div>
        )
        return step.href ? (
          <a key={index} href={step.href} target="_blank" rel="noreferrer" className="block transition-colors hover:bg-zinc-800/20 rounded-lg">
            {row}
          </a>
        ) : (
          row
        )
      })}
    </div>
  )
}
