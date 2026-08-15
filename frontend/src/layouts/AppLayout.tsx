import { NavLink, Outlet } from "react-router-dom"
import {
  LayoutDashboard,
  CandlestickChart,
  KeyRound,
  Settings,
  Zap,
  History,
  Newspaper,
} from "lucide-react"
import { cn } from "../lib/utils"
import { useCredentialInit } from "../hooks/useCredentialInit"

const NAV_ITEMS = [
  { to: "/", label: "仪表盘", icon: LayoutDashboard, end: true },
  { to: "/trade", label: "交易", icon: CandlestickChart, end: false },
  { to: "/news-ai", label: "快讯与 AI", icon: Newspaper, end: false },
  { to: "/history", label: "历史记录", icon: History, end: false },
  { to: "/credentials", label: "凭证管理", icon: KeyRound, end: false },
  { to: "/settings", label: "设置", icon: Settings, end: false },
]

function AppLayout() {
  // 挂载时自动选定当前交易凭证（唯一一条 / 旧约定名 / 第一条）
  const credentialName = useCredentialInit()

  return (
    <div className="flex h-screen bg-[#0a0a0f] text-zinc-100">
      <aside className="flex w-60 shrink-0 flex-col border-r border-zinc-800/80 bg-[#0d0d14]">
        <div className="flex h-16 items-center gap-2.5 border-b border-zinc-800/80 px-5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-500/20 ring-1 ring-indigo-500/40">
            <Zap className="h-4.5 w-4.5 text-indigo-400" />
          </div>
          <div className="leading-tight">
            <div className="text-sm font-semibold tracking-wide">QuanForge</div>
            <div className="text-[11px] text-zinc-500">AI 量化交易台</div>
          </div>
        </div>

        <nav className="flex-1 space-y-1 overflow-y-auto p-3">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-indigo-500/15 text-indigo-300 ring-1 ring-inset ring-indigo-500/30"
                    : "text-zinc-400 hover:bg-zinc-800/60 hover:text-zinc-100"
                )
              }
            >
              <item.icon className="h-4 w-4" />
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-zinc-800/80 p-4">
          <div className="rounded-lg bg-zinc-800/40 px-3 py-2.5 ring-1 ring-inset ring-zinc-700/50">
            <div className="text-[11px] text-zinc-500">交易凭证</div>
            <div className="mt-0.5 truncate text-xs font-medium text-emerald-400" title={credentialName}>
              {credentialName}
            </div>
          </div>
        </div>
      </aside>

      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  )
}

export default AppLayout
