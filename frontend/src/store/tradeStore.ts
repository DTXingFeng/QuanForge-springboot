import { create } from "zustand"

// 交易操作共享状态：持仓刷新信号（下单/平仓后 bump 触发持仓表刷新）
interface TradeStore {
  positionsRefreshKey: number
  bumpPositionsRefresh: () => void
  symbol: string
  setSymbol: (s: string) => void
  // 当前交易使用的凭证标识（由 useCredentialInit 自动初始化，设置页可手动切换）
  credentialName: string
  setCredentialName: (n: string) => void
}

export const useTradeStore = create<TradeStore>((set) => ({
  positionsRefreshKey: 0,
  bumpPositionsRefresh: () => set((s) => ({ positionsRefreshKey: s.positionsRefreshKey + 1 })),
  symbol: "BTCUSDT",
  setSymbol: (s) => set({ symbol: s.toUpperCase() }),
  // 默认值保持与旧约定一致，避免存量配置失效
  credentialName: "my-demo-bybit",
  setCredentialName: (n) => set({ credentialName: n }),
}))
