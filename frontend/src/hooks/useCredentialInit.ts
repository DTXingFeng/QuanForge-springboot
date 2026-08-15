import { useEffect } from "react"
import { useTradeStore } from "../store/tradeStore"

/** 旧约定下的默认凭证名，用于兼容存量配置 */
const LEGACY_DEFAULT = "my-demo-bybit"

/**
 * 应用启动时自动选定「当前交易凭证」：
 * - 当前凭证名已存在 → 保持不变
 * - 仅一条凭证 → 自动选中
 * - 存在 my-demo-bybit（旧约定） → 选中它，保持兼容
 * - 多条且都不匹配 → 选第一条
 * - 无凭证 → 保持现状（交易页会提示凭证不存在）
 *
 * 在 AppLayout 挂载时调用一次，返回当前凭证名供展示。
 */
export function useCredentialInit(): string {
  const credentialName = useTradeStore((s) => s.credentialName)
  const setCredentialName = useTradeStore((s) => s.setCredentialName)

  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const res = await fetch("/api/credentials")
        if (!res.ok) return
        const list: { name: string }[] = await res.json()
        if (!alive || list.length === 0) return
        const names = list.map((c) => c.name)
        if (names.includes(credentialName)) return // 当前名有效，保持
        const next = names.includes(LEGACY_DEFAULT) ? LEGACY_DEFAULT : names[0]
        setCredentialName(next)
      } catch {
        // 后端不可达时保持现状，交易页会提示
      }
    })()
    return () => {
      alive = false
    }
    // 仅挂载时初始化一次；用户可在设置页手动切换
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return credentialName
}
