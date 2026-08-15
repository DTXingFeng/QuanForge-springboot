import { BrowserRouter, Routes, Route } from "react-router-dom"
import { Toaster } from "./components/ui/sonner"
import AppLayout from "./layouts/AppLayout"
import DashboardPage from "./pages/DashboardPage"
import TradePage from "./pages/TradePage"
import NewsAiPage from "./pages/NewsAiPage"
import CredentialsPage from "./pages/CredentialsPage"
import SettingsPage from "./pages/SettingsPage"
import HistoryPage from "./pages/HistoryPage"

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/trade" element={<TradePage />} />
          <Route path="/news-ai" element={<NewsAiPage />} />
          <Route path="/credentials" element={<CredentialsPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
      </Routes>
      <Toaster richColors position="top-right" />
    </BrowserRouter>
  )
}

export default App
