import NewsFeed from "../components/trading/NewsFeed"
import AiAlertPanel from "../components/trading/AiAlertPanel"

/**
 * 快讯与 AI 盯盘页：从交易页拆出的完整页面。
 * 左栏快讯流（全高滚动），右栏 AI 研判（KPI + 状态 + 告警流）。
 */
function NewsAiPage() {
  return (
    <div className="flex h-full flex-col p-6">
      <header className="mb-6">
        <h1 className="text-xl font-semibold">快讯与 AI</h1>
        <p className="mt-1 text-sm text-zinc-500">四源快讯聚合 · AI 盯盘研判</p>
      </header>
      <div className="grid min-h-0 flex-1 gap-6 xl:grid-cols-2">
        <NewsFeed />
        <AiAlertPanel />
      </div>
    </div>
  )
}

export default NewsAiPage
