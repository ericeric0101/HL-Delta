# HyperVault Delta Bot v1.0.0

一個為 HyperLiquid 交易所設計的 delta-neutral（中性對沖）交易機器人，用於在現貨和永續市場創建和管理 delta-neutral 部位。

![Delta Bot 運作中](./assets/terminal-screenshot.png)
*Delta Bot 正在 HyperLiquid 交易所建立倉位*

## 功能

- 在現貨和永續市場實施 delta-neutral 交易策略
- 自動識別最佳資金費率以獲得最佳收益
- **[新]** 永久紀錄所有交易訂單與每小時的資產快照至 Supabase 雲端資料庫
- **[新]** 前端儀表板升級，新增「交易紀錄」分頁，清晰呈現所有歷史交易
- 採用 Maker 訂單策略 (Post-Only) 執行交易，旨在賺取手續費返利而非支付交易費用
- 自動化動態風險管理，定期檢查並重新平衡持倉，以嚴格維持 Delta 中性
- 整合利潤再投資機制，在完成交易週期後自動將利潤滾入本金，實現複利增長
- 監控和重新平衡倉位以維持 delta-neutral
- 用於遠程控制和監控的 RESTful API
- 處理訂單跟踪和管理
- 定期檢查以根據資金費率尋找更好的機會
- 帶有平倉功能的正常關機
- 全面的日誌記錄

## 核心功能更新：交易紀錄與儀表板

為了讓使用者能夠更好地追蹤、分析交易表現與資產變化，我們引入了一套完整的永久紀錄系統與前端儀表板升級。

### 第一階段：永久交易紀錄系統 (Supabase 整合)

- **目標**：解決原本日誌 (`delta.log`) 無法永久保存、難以分析的問題，建立一個專業、可靠的交易紀錄資料庫。
- **技術方案**：
    1.  **引入 Supabase**：我們選擇了 Supabase (一個基於 PostgreSQL 的後端即服務平台) 作為我們的資料庫。它提供了強大的查詢能力、高擴展性、即時數據同步及可靠的安全性。
    2.  **雙重紀錄機制**：
        - **交易訂單 (`trade_logs`)**：系統中每一次的下單嘗試 (包含開倉、平倉、再平衡等)，其詳細資訊都會被即時記錄到 `trade_logs` 資料表中。
        - **資產快照 (`account_snapshots`)**：為了追蹤整體資產變化，系統會**每小時**為您的帳戶拍攝一次「快照」，記錄當時的總資產價值、現貨與合約帳戶價值等關鍵數據，並存入 `account_snapshots` 資料表。
- **如何啟用**：此功能為選用，但強烈建議啟用。您需要在 Supabase 建立專案與資料表，並在您的 `.env` 檔案中設定 `SUPABASE_URL` 和 `SUPABASE_KEY` 環境變數 (詳見「設定」一節)。

### 第二階段：前端儀表板升級

- **目標**：將後端儲存的數據以最清晰、直觀的方式呈現給使用者，改善操作體驗。
- **介面更新**：
    1.  **全新的分頁設計**：為了避免在單一頁面無限滾動，我們將儀表板重構為分頁式設計，包含「**總覽**」和「**交易紀錄**」兩個主要分頁。
    2.  **交易紀錄表格**：在「交易紀錄」分頁中，我們建立了一個功能完善的表格，用於顯示所有歷史交易。表格支援**分頁瀏覽**，讓您即使在交易量巨大時也能輕鬆查閱。
    3.  **後端驅動**：此表格的數據來自我們在後端建立的 `/api/status/trade-history` API 端點，確保了數據的安全與一致性。

## 核心交易策略更新

為了提升機器人的盈利能力與穩定性，我們引入了三項關鍵的策略升級：

### 想法一：混合 Maker-Taker 策略：兼顧成本與效率

- **目標**：將機器人從單純的「做市商 (Maker)」升級為一個更聰明的交易執行者，它既會嘗試**賺取手續費返利**，又能在必要時果斷出手以**確保交易成功率**，完美結合了低成本與高效率。
- **執行邏輯**：現在，每一次開倉或平倉都是一個兩階段的作戰計畫：
    1.  **第一階段：嘗試 Maker (成本最優)**
        - 程式會優先以「只做 Maker (Post-Only)」的方式提交訂單，爭取以零成本甚至負成本（賺取返利）完成交易。
        - 在提交掛單後，程式會**等待 5 秒**，觀察訂單能否在此黃金時間內被市場自然撮合。
        - 如果訂單完全成交，任務即以最優成本完成。

    2.  **第二階段：切換 Taker (效率最高)**
        - 如果 5 秒後 Maker 訂單**未能完全成交**，或是一開始提交就被交易所拒絕，系統會立即判定「耐心等待」的時機已過。
        - 它會**自動撤銷所有未成交的 Maker 掛單**，並立即轉為 Taker 模式，以「吃單限價單 (Immediate-or-Cancel)」的方式提交新訂單，確保部位能夠被**立即建立或關閉**。

- **全程原子性保險**：在上述兩個階段的任何一步，我們之前建立的**緊急回滾機制**都全程待命。如果發生任何單邊訂單被意外瞬間成交的極端情況，系統會立刻提交反向的**市價單**來將其平倉，嚴格杜絕任何未對沖的風險敞口。

### 想法二：動態風險管理 — 自動再平衡

- **目標**：嚴格維持每個 Delta 中性倉位的風險為零，應對因市場價格波動導致的風險敞口。
- **執行邏輯**：
    1.  **定期監控**：機器人在主迴圈中會定期（例如每分鐘）檢查所有活躍的 Delta 中性倉位。
    2.  **價值計算**：它會計算每個倉位中「現貨部位的總價值」與「永續合約部位的總價值」。
    3.  **觸發再平衡**：理想情況下，這兩個價值應該是相等的。如果因為價格波動導致兩者價值的差異超過 `trading.delta_threshold_pct`（例如預設 5%），再平衡機制就會被觸發。
    4.  **自動微調**：機器人會自動計算需要調整的微小規模，並使用 Maker 訂單策略（參考想法一）執行反向操作（例如，賣出一點現貨，同時買回一點永續合約），將兩邊的價值重新拉平，恢復嚴格的 Delta 中性狀態。

### 主迴圈運作流程（持倉中時會做什麼？）

新的狀態機以 `trading.heartbeat_sec`（預設 3 秒）為節奏，在每次心跳內依序執行：

1. **同步帳戶與行情**：更新現貨／永續持倉、訂單簿與最新資金費率（支援 EMA 平滑）。
2. **判斷狀態**：辨識是否為空倉、Delta 中性、單腿（僅剩現貨或僅剩永續）、再平衡、平倉或錯誤復原。
3. **單腿補救與再平衡**：當偵測到單腿或 Δ 偏離超過 `delta_threshold_pct` 時，僅針對需要的一側下單，若連續 `max_retries` 失敗則改為迅速平倉。
4. **收益評估與換倉**：持倉時若年化資金費率跌破 `funding_replace_threshold_pct`，且已達 `min_hold_minutes`，會先平舊倉再於冷卻 (`cooldown_after_replace_minutes`) 結束後尋找下一個標的。
5. **空倉開倉判斷**：當完全沒有部位且最佳標的年化資金費率高於 `funding_open_threshold_pct` 時，依序建立現貨與永續腿，並在單腿失敗時自動回滾。

因此，當我們已有部位時，Bot 的目標是「維持 Delta 中性、當收益變差就換標的」，而不是不停嘗試開新的 Delta 組合。

### 想法三：利潤再投資 — 自動複利

- **目標**：讓機器人能夠自動地將已實現的利潤重新投入到交易中，逐步擴大倉位規模，實現長期複利增長。
- **運作機制**：此功能並非在產生微小利潤時就立刻加倉，而是以一種更宏觀、高效的方式運作：
    1.  **利潤累積**：在一個倉位的持有期間，透過資金費率賺取的利潤會靜靜地累積在帳戶中，增加總帳戶價值。
    2.  **觸發時機**：再投資的真正觸發點，是當機器人**結束當前完整的倉位週期**（例如，為了切換到一個資金費率更高的幣種而平倉），並**準備建立一個全新的倉位**時。
    3.  **自動擴大規模**：在建立新倉位前，機器人會重新評估**包含已實現利潤的最新帳戶總價值**。然後，它會基於這個新的、更大的總資本來計算下一個倉位的規模。
- **優勢**：這種設計避免了為零星利潤進行的頻繁、不經濟的微小交易，只在必要時才調整規模，從而以低成本、自動化的方式實現了利潤的複利增長。

這三項更新將機器人從一個基礎的策略執行者，升級為一個能夠主動管理成本、風險和資本增長的精密交易系統。

## 設定

該機器人結合使用配置文件和環境變數：

### 1. **配置文件** (config.json) - 主要設定

設定機器人的首選方法是通過 `config.json` 文件，它控制著機器人的大部分行為：

```json
{
  "general": {
    "debug": false,
    "tracked_coins": ["BTC", "ETH", "HYPE", "USDC"],
    "autostart": true
  },
  "allocation": {
    "spot_pct": 70,
    "perp_pct": 30,
    "rebalance_threshold": 0.05
  },
  "trading": {
    "refresh_interval_sec": 60,
    "heartbeat_sec": 3,
    "min_spot_balance_to_open": 50,
    "target_perp_leverage": 1.0,
    "delta_threshold_pct": 5.0,
    "min_rebalance_interval_sec": 5,
    "max_retries": 3,
    "slippage_cap_bps": 15,
    "fee_bps": 2,
    "min_qty": 0.001,
    "price_tick": 0.001,
    "qty_step": 0.001,
    "funding_refresh_sec": 60,
    "funding_use_ema": true,
    "funding_ema_alpha": 0.3,
    "funding_check_minute": 50,
    "funding_open_threshold_pct": 10.0,
    "funding_replace_threshold_pct": 20.0,
    "min_hold_minutes": 60,
    "cooldown_after_replace_minutes": 30,
    "use_post_only_for_entry": true,
    "use_post_only_for_hedge": false,
    "rebalance_order_type": "passive_then_ioc",
    "min_position_value_usd": 10.0
  },
  "api": {
    "host": "0.0.0.0",
    "port": 8080,
    "enabled": true
  }
}
```

設定部分：
- **一般設定:**
  - `debug`: 啟用詳細的調試日誌
  - `tracked_coins`: 要跟踪和交易的代幣列表
  - `autostart`: 是否自動開始交易
- **交易設定 (`trading`):**
  - `heartbeat_sec`: 狀態機心跳間隔，預設 3 秒；所有持倉偵測與補救都在此節奏內完成。
  - `refresh_interval_sec`: 保留舊設定以兼容舊流程，目前僅作回退用途。
  - `min_spot_balance_to_open`: 開倉前保留在現貨帳戶的最低 USDC 金額。
  - `target_perp_leverage`: 計算永續腿名目金額時的目標槓桿，上限新倉規模。
  - `delta_threshold_pct`: 名目價值偏離超過此百分比即觸發再平衡。
  - `min_rebalance_interval_sec`: 兩次再平衡之間的最短間隔，避免過度觸發。
  - `max_retries`: 單腿補救 / 再平衡的最大重試次數，超過後改為平掉現有腿。
  - `slippage_cap_bps`: 下單時允許的滑點上限（基於最佳買賣價）。
  - `fee_bps`: 預估手續費，供名目計算與紀錄使用。
  - `min_qty`, `price_tick`, `qty_step`: 若交易所未回傳最小下單量或步進單位，可在此強制指定。
  - `funding_refresh_sec`: 每次向 Hyperliquid REST 取得 predictedFunding 的秒數。
  - `funding_use_ema` / `funding_ema_alpha`: 是否啟用 EMA 平滑以及權重；預設啟用 α=0.3。
  - `funding_check_minute`: 仍保留每小時例行檢查的時間點。
  - `funding_open_threshold_pct`: 空倉時若最佳標的年化資金費率高於此值才會開倉。
  - `funding_replace_threshold_pct`: 持倉時若當前收益率低於此值才會觸發換倉。
  - `min_hold_minutes`: 最小持倉時間，避免在剛開倉後立即換倉。
  - `cooldown_after_replace_minutes`: 換倉完成後的冷卻期。
  - `use_post_only_for_entry`: 是否在進場／開倉使用 post only。
  - `use_post_only_for_hedge`: 是否在補腿時使用 post only（預設禁用以避免拒單）。
  - `rebalance_order_type`: `passive_then_ioc` 代表先用限價嘗試，未成交再降級成 IOC。
  - `min_position_value_usd`: 單腿名目價值若低於此金額（USDC），視為零倉位並忽略。
- **分配設定:**
  - `spot_pct`: 分配給現貨倉位的資金百分比（例如 70%）。
  - `perp_pct`: 分配給永續合約倉位的資金百分比（例如 30%）。
  - `rebalance_threshold`: 若仍使用舊版比例再平衡，這裡保持支援；新版改以 `delta_threshold_pct` 為主。
- **API 設定:**
  - `host`: API 伺服器的主機
  - `port`: API 伺服器的端口
  - `enabled`: 是否啟用 API 伺服器

### 2. **環境變數** - 身份驗證與功能啟用所需

這些環境變數用於與 HyperLiquid 進行身份驗證及啟用額外功能，必須設定在您的 `.env` 檔案中。

- `HYPERLIQUID_PRIVATE_KEY`: **(必需)** 您在 HyperLiquid 上交易的私鑰。
- `HYPERLIQUID_ADDRESS`: **(必需)** 您在 HyperLiquid 上的以太坊地址。
- `API_SECRET_KEY`: **(必需)** 用於保護後端 API 的金鑰，前端連線時需使用相同的金鑰。
- `SUPABASE_URL`: **(選用, 建議)** 您的 Supabase 專案 URL，用於啟用永久交易紀錄功能。
- `SUPABASE_KEY`: **(選用, 建議)** 您的 Supabase 專案 `service_role` 金鑰，用於啟用永久交易紀錄功能。

使用環境變數的範例 (`.env` 檔案內容):
```bash
HYPERLIQUID_PRIVATE_KEY=您的私鑰
HYPERLIQUID_ADDRESS=您的子帳戶交易地址
API_SECRET_KEY=您設定的API金鑰

# 選用，但強烈建議用於紀錄交易
SUPABASE_URL=您的Supabase專案URL
SUPABASE_KEY=您的Supabase專案ServiceRole金鑰
```

## 快速入門

1. 複製儲存庫
2. 設定用於身份驗證的環境變數
3. 自定義 `config.json` 以符合您期望的交易參數
4. 運行範例腳本以測試您的設定：
```bash
python example.py
```
- 系統會檢查 config.json 中的 autostart 設定，如果設為 true（預設值），機器人會自動開始交易。

## 一旦啟動，系統會進入主要監控循環：
- **心跳頻率**：依 `heartbeat_sec`（預設 3 秒）運行狀態機，更新倉位並執行補腿/再平衡。
- **資金費率監控**：依 `funding_refresh_sec` 收集最新 predicted funding；`funding_check_minute` 保留逐小時檢查。
- **自動開倉條件**：當最佳幣種年化資金費率 ≥ `funding_open_threshold_pct` 且未處於冷卻/最小持倉期間時，自動建立 Delta 中性部位。

## 系統會自動執行以下操作：
- 創建部位：同時買入現貨和做空永續合約
- 切換部位：當當前部位收益率低於 `funding_replace_threshold_pct` 且市場存在更好機會時，會自動關閉舊部位並創建新部位
- 訂單追蹤：自動監控訂單執行狀態

**注意 1**：如果想要手動控制而非自動交易，可以在 `config.json` 中將 autostart 設為 false，然後通過 API 端點手動控制機器人的啟動和停止。

**注意 2**：當您設定 "autostart": false 時，後端服務會正常啟動，API伺服器也會運行，但交易機器人本身的核心邏輯會處於「待命」狀態。

日誌中的 `Call start() manually to begin.` 這句話的意思是「請手動呼叫 start() 函數來開始運作」。這裡的「呼叫」並不是指在終端機輸入一個新的指令，而是指透過 API 來向正在運行的後端程式下達「開始」的指令。
   1. 啟動後端服務 (`python entrypoint.py`)。
   2. 啟動前端服務 (`cd frontend && npm start`)。
   3. 在瀏覽器中打開 `http://localhost:3000`。
   4. 在儀表板右上角的「Account Overview」區塊，您會看到一個綠色的 "Start" 按鈕。
   5. 點擊這個 "Start" 按鈕。

點擊按鈕後，前端會發送一個 POST 請求到後端的 `/api/bot/start` 端點，後端收到請求後就會呼叫 `start()` 函數，您的機器人便會開始執行交易邏輯。

5. 啟動機器人：
```bash
python Delta.py
```

## 建置

使用以下指令建置 Docker 映像檔：

```bash
./build.sh
```

這將創建兩個映像檔：
- `hypervault-tradingbot:delta` (最新版本)
- `hypervault-tradingbot:delta-1.0.0` (版本標籤)

## API 端點

該機器人提供一個 RESTful API 用於遠程控制和監控：

### 機器人控制
- `GET /api/bot/state`: 獲取機器人當前狀態
- `POST /api/bot/start`: 啟動機器人的交易操作
- `POST /api/bot/stop`: 停止機器人的交易操作
- `POST /api/bot/close-position/{coin}`: 關閉特定倉位
- `POST /api/bot/create-position/{coin}`: 為特定代幣創建倉位

### 狀態與監控
- `GET /api/status`: 獲取機器人及其倉位的當前狀態
- `GET /api/status/funding-rates`: 獲取所有追蹤代幣的當前資金費率
- `GET /api/status/positions`: 獲取所有當前倉位

### 設定
- `GET /api/config`: 獲取機器人當前設定
- `POST /api/config/update`: 更新機器人設定
- `GET /api/config/tracked-coins`: 獲取追蹤的代幣列表
- `POST /api/config/add-coin/{coin}`: 將代幣添加到追蹤列表
- `POST /api/config/remove-coin/{coin}`: 從追蹤列表中移除代幣

## 使用方式

1. 從 `.env.example` 創建一個 `.env` 文件，並填入您的憑證
2. 調整 `config.json` 以符合您期望的交易參數
3. 建置並運行 Docker 容器：

```bash
docker run -d \
  --name delta-bot \
  -p 8080:8080 \
  --env-file .env \
  hypervault-tradingbot:delta-1.0.0
```

## 本專案配備前端UI讓使用者更方便地追蹤bot運作

本專案包含一個 React 前端應用程式，提供視覺化的儀表板來監控機器人狀態。

- **分頁式介面**：儀表板現在分為「**總覽**」和「**交易紀錄**」兩個主要分頁。
  - **總覽**：顯示機器人即時狀態、帳戶概覽、目前倉位、設定管理及即時日誌等核心監控資訊。
  - **交易紀錄**：展示所有被永久儲存的歷史交易訂單，並支援分頁瀏覽。

- **啟動方式**：
  1. 開啟新的 terminal 執行 `python entrypoint.py` 來啟動後端 (必須在 `localhost:8080` 上運行)。
  2. 接著再開啟另外一個 terminal，導航到 `frontend` 目錄，然後執行 `npm start` (網址通常是 `http://localhost:3000`)。

- **連接設定**：
  為了將前端連接到後端 API，請在 `frontend` 目錄內創建一個 `.env` 文件，並填入您在後端設定的 `API_SECRET_KEY`：
  ```
  REACT_APP_API_KEY=您設定的API金鑰
  ```

## HyperVault 交易生態系統 (即將推出！)

Delta 機器人是 HyperVault 綜合交易生態系統的一部分。我們的完整平台將讓您能夠：

- 一鍵部署多個機器人
- 利用我們的機器學習引擎自動優化您的交易設定
- 使用包括此 Delta-Neutral 機器人和我們的造市機器人在內的專業機器人
- 透過我們的高級儀表板監控您的表現，其功能包括：
  - 即時倉位管理
  - 收益可視化與分析
  - 最新倉位跟踪和績效指標

HyperVault 專為尋求簡化自動化交易的新手和需要強大客製化功能的老手而設計。

## Delta-Neutral 策略

Delta 機器人實施一種資本高效的策略：
- 做多現貨倉位以賺取資金費率
- 做空永續期貨倉位以對沖價格風險
- 當資金費率變化時自動切換到更好的機會

該系統的目標是 70/30 的現貨與永續合約分配比例，以實現最佳的資本效率。

## 版本控制

### 目前版本: 1.1.0

**發行說明:**
- 初始版本，具有核心的 delta-neutral 功能
- 與 HyperVault 交易機器人平台完全整合
- 基於 API 的控制和監控
- 自動檢測最佳資金機會

## Star 歷史

[![Star History Chart](https://api.star-history.com/svg?repos=cgaspart/HL-Delta&type=Date)](https://www.star-history.com/#cgaspart/HL-Delta&Date)

## 授權

MIT 授權

Copyright (c) 2024

特此免費授予任何人獲取本軟體及相關文檔文件（“軟體”）副本的權利，可以不受限制地處理本軟體，包括但不限於使用、複製、修改、合併、發布、分發、再授權和/或銷售本軟體的副本，並允許獲得本軟體的人員這樣做，但須符合以下條件：

上述版權聲明和本許可聲明應包含在本軟體的所有副本或主要部分中。

本軟體“按原樣”提供，不提供任何明示或暗示的擔保，包括但不限於對適銷性、特定用途適用性和非侵權性的擔保。在任何情況下，作者或版權持有人均不對任何索賠、損害或其他責任承擔任何責任，無論是在合同訴訟、侵權行為或其他方面，由本軟體或與本軟體的使用或其他交易引起或與之相關。

## 免責聲明

本軟體僅供教育目的使用。使用風險自負。交易加密貨幣涉及重大的虧損風險，不適合所有投資者。
