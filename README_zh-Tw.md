# HyperVault Delta Bot v1.0.0

一個為 HyperLiquid 交易所設計的 delta-neutral（中性對沖）交易機器人，用於在現貨和永續市場創建和管理 delta-neutral 部位。

![Delta Bot 運作中](./assets/terminal-screenshot.png)
*Delta Bot 正在 HyperLiquid 交易所建立倉位*

## 功能

- 在現貨和永續市場實施 delta-neutral 交易策略
- 自動識別最佳資金費率以獲得最佳收益
- **[新]** 採用 Maker 訂單策略 (Post-Only) 執行交易，旨在賺取手續費返利而非支付交易費用
- **[新]** 自動化動態風險管理，定期檢查並重新平衡持倉，以嚴格維持 Delta 中性
- 監控和重新平衡倉位以維持 delta-neutral
- 用於遠程控制和監控的 RESTful API
- 處理訂單跟踪和管理
- 定期檢查以根據資金費率尋找更好的機會
- 帶有平倉功能的正常關機
- 全面的日誌記錄

## 核心交易策略更新

為了提升機器人的盈利能力與穩定性，我們引入了兩項關鍵的策略升級：

### 想法一：優化訂單執行 — Maker 策略

- **目標**：將機器人從一個「吃單者 (Taker)」轉變為「做市商 (Maker)」，旨在**賺取手續費返利**，而不是支付交易費用，從而開闢新的利潤來源。
- **執行邏輯**：
    1.  **被動下單**：在建立或關閉倉位時，機器人不再以確保快速成交的價格下單。相反，它會獲取訂單簿上最佳的買一價 (Best Bid) 和賣一價 (Best Ask)。
    2.  **Post-Only 訂單**：所有訂單都將作為「僅掛單 (Post-Only)」提交。這確保了我們的訂單只會進入訂單簿提供流動性，如果訂單會立即成交（成為 Taker），交易所將自動取消該訂單。
    3.  **自動重新掛單**：由於 Maker 訂單不保證立即成交，我們建立了一套智慧追蹤系統。如果訂單在特定時間內（例如 15 秒）未成交，機器人會自動取消該訂單，並根據最新的市場價格重新提交，確保我們的報價始終具有競爭力。

### 想法二：動態風險管理 — 自動再平衡

- **目標**：嚴格維持每個 Delta 中性倉位的風險為零，應對因市場價格波動導致的風險敞口。
- **執行邏輯**：
    1.  **定期監控**：機器人在主迴圈中會定期（例如每分鐘）檢查所有活躍的 Delta 中性倉位。
    2.  **價值計算**：它會計算每個倉位中「現貨部位的總價值」與「永續合約部位的總價值」。
    3.  **觸發再平衡**：理想情況下，這兩個價值應該是相等的。如果因為價格波動導致兩者價值的差異超過了設定的閾值（例如 5%），再平衡機制就會被觸發。
    4.  **自動微調**：機器人會自動計算需要調整的微小規模，並使用 Maker 訂單策略（參考想法一）執行反向操作（例如，賣出一點現貨，同時買回一點永續合約），將兩邊的價值重新拉平，恢復嚴格的 Delta 中性狀態。

這兩項更新將機器人從一個基礎的策略執行者，升級為一個能夠主動管理成本和風險的精密交易系統。

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
    "refresh_interval_sec": 60
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
- **分配設定:**
  - `spot_pct`: 分配給現貨倉位的資金百分比（例如 70%）
  - `perp_pct`: 分配給永續合約倉位的資金百分比（例如 30%）
  - `rebalance_threshold`: 重新平衡倉位的閾值（例如 0.05 = 5%）
- **交易設定:**
  - `refresh_interval_sec`: 以秒為單位的倉位刷新間隔
- **API 設定:**
  - `host`: API 伺服器的主機
  - `port`: API 伺服器的端口
  - `enabled`: 是否啟用 API 伺服器

### 2. **環境變數** - 身份驗證所需

這些環境變數用於與 HyperLiquid 進行身份驗證，必須設定：

- `HYPERLIQUID_PRIVATE_KEY`: 您在 HyperLiquid 上交易的私鑰
- `HYPERLIQUID_ADDRESS`: 您在 HyperLiquid 上的以太坊地址

使用環境變數的範例：
```bash
export HYPERLIQUID_PRIVATE_KEY={您的私鑰}
export HYPERLIQUID_ADDRESS={您的子帳戶交易地址}
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
- 定期檢查：每 60 秒（可在配置中調整）檢查一次
- 資金費率監控：在每小時的第 50 分鐘檢查資金費率
- 自動下單條件：當找到年化收益率 ≥ 5% 的機會時會自動創建 delta-neutral 部位

## 系統會自動執行以下操作：
- 創建部位：同時買入現貨和做空永續合約
- 切換部位：當當前部位收益率低於 5% 且有更好機會時，會自動關閉舊部位並創建新部位
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

- 首先開啟新的terminal執行 `python entrypoint.py` 來啟動後端 (必須在 `localhost:8080` 上運行)
- 接著再開啟另外一個terminal，導航到 `frontend` 目錄，然後執行 `npm start` (網址通常是 `http://localhost:3000`)。
- 為了將前端連接到 API，請在 `frontend` 目錄內創建一個 `.env` 文件，並添加以下行：
  ```
  REACT_APP_API_KEY=your_api_key
  ```
  如果您的 API 需要金鑰，請將 `your_api_key` 替換為您的實際 API 金鑰。如果 API 不需要金鑰，您可以將其留空。

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