import WalletCard from "../components/trading/WalletCard"
import KLineChart from "../components/trading/KLineChart"
import OrderPanel from "../components/trading/OrderPanel"
import PositionsTable from "../components/trading/PositionsTable"
import OpenOrdersTable from "../components/trading/OpenOrdersTable"

function TradePage() {
  return (
    <div className="p-6">
      <header className="mb-6">
        <h1 className="text-xl font-semibold">交易</h1>
        <p className="mt-1 text-sm text-zinc-500">合约交易工作台</p>
      </header>
      <div className="grid gap-6 xl:grid-cols-[400px_minmax(0,1fr)]">
        <div className="space-y-6">
          <WalletCard />
          <OrderPanel />
        </div>
        <div className="min-w-0 space-y-6">
          <KLineChart />
          <OpenOrdersTable />
          <PositionsTable />
        </div>
      </div>
    </div>
  )
}

export default TradePage
