# QF-S Paper Lab v5.1 replacement

**ROLLED BACK at the user's explicit request on 2026-11-15 (Hong Kong time).** The Pi again runs the original JAR and original UI, with all six legacy services/timers restored to their recorded activation/enablement states. The new PAPER worker is stopped and disabled; its experiment data and local development files are retained. The original database was never restored from an older snapshot or overwritten. See `rollback-result.json` for observed verification. Do not redeploy this replacement without a new user instruction.

User authorization on 2026-11-15: design the replacement and directly replace the Raspberry Pi version. No further approval for routine deployment steps is needed. Keep real funds, credentials and old trade histories untouched.

Delivery: current Spring Boot + React application, a standard-library Python public-market PAPER worker, a fresh SQLite paper ledger, visible costs/positions/data health/strategy validation state, and reversible systemd release switching on the original port 40702.

The new worker does not consume the old AI feed, call an LLM, import credentials or contain an exchange order API. Legacy scheduling and signed account writes are disabled in the paper-only release; a route guard blocks legacy account APIs. Existing databases and original JAR/configuration are privately backed up and retained. New app metadata and paper databases use new paths.

Frozen research candidates on XRPUSDT five-minute data:

1. Trend pullback: hourly EMA20/60 trend, five-minute price reclaims EMA20 after a pullback, symmetrical long/short rules.
2. Failed breakout: five-minute high/low sweeps the previous 12-bar range and closes inside, conditional on a weak hourly EMA/ATR trend score.
3. Regime selector: applies the first rule in a strong trend and the second in a weak trend. Whole selector must be replayed, not assembled from the best historical portions.
4. Cash baseline.

Rules, signal timing, risk, fees and samples are registered before retrieving the new five-minute research data. No parameter search. Historical research does not certify forward profitability. The initial deployed system is explicitly EXPERIMENTAL PAPER, never labeled profitable solely because it runs or passes software tests.

Research outcome: all three direction candidates failed the frozen 90-day/three-window comparison (24 cases including cash and doubled costs). They remain recorded and are NOT enabled. The direction worker and ledger are research utilities, not the deployed entry point.

The deployed entry point is `paper_vnext_carry_worker.py`: one 20 USDT total-capital XRP spot-long/equal-coins perpetual-short PAPER pair, with full initial cash reserve for the short (1x), explicit bid/ask and depth, 0.10% spot and 0.055% perpetual fees per side, 0.05% adverse slippage per leg, and tick/quantity rounding. Enter only when current indicated funding is positive, then manage risk rather than repeatedly switching on the fee sign. Maximum NAV drawdown is 3%; the short-equity margin buffer exits below 25% of mark notional. A gap that exhausts isolated cash makes the result invalid, never a fabricated successful liquidation. Funding uses settled public rates and a disclosed settlement-minute mark-open approximation. State, pending settlements and immutable events survive restart.

The older 90-day fixed-entry XRP reference showed +0.08001448 USDT (+0.02919709 with doubled fees/slippage). This was exploratory asset selection, not a holdout. It did not use the new positive-indicated-rate entry, current quote fills or 25% buffer; it therefore DOES NOT validate the deployed rules. Forward profitability is explicitly NOT PASSED. No claim of an investable edge follows from these small returns.

Proxy is a single source: reuse the existing program `proxy_config` singleton, preserving host/port/enabled and optional authentication. The Java paper API publishes a mode-600 local runtime file for the Python worker; credential values are never returned by the paper UI. Workers do not inherit or substitute Windows proxy settings. Ordinary changes in the program proxy editor are reloaded on the next polling cycle.

Architecture choices: feature folders; typed relative REST client; five-second status polling; no new auth system on this existing private-LAN app; same-origin checks for paper controls; structured errors. Paper state is separate from legacy JPA metadata. UI has one clear experimental dashboard rather than account credential/trading controls.

Implementation/verification order: frozen strategy and red tests -> shared replay/forward signal logic -> quote execution/persistence/funding tests -> public historical capture and fixed comparison -> backend/route guard -> responsive paper dashboard -> fresh builds and isolated packaged smoke -> readonly old-account/position and service check -> private backup -> deploy release -> verify new UI/worker/ledger/account-route blocking -> preserve rollback and record observed evidence.

Do not stop an account manager over unverified existing exchange exposure. Check Java and the inactive shadow account with signed GET only before replacing the manager. Do not create test exchange orders or flatten unknown positions automatically. Other projects/services on the Pi are outside scope.
