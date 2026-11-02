# 低飛 LowFly — 建置規格書（給 AI 實作者）

> 這份文件是要交給 AI（例如 GPT）直接生成專案用的。
> 第 0 節是給 AI 的工作指示；第 1～10 節是已經拍板、經過查證與測試的設計；附錄 A 是一份已通過 12 個單元測試的 Python 參考實作，可直接沿用或改寫。

---

## 0. 給 AI 實作者的指示

1. **你的角色**：資深後端／自動化工程師。目標是交付一個「能跑、能通知、能自己維護狀態」的完整專案，不是教學文章。
2. **語言**：所有回覆與文件用繁體中文；程式識別字用英文。
3. **已拍板的事不要重問**（第 2 節決策紀錄）。第 2 節以外若真的需要使用者決定，**一律用選擇題**（2～4 個選項，標出你推薦的那個），一次問完，不要分散在對話各處。
4. **交付型態已決定（第 12 節）**：一個 repo、兩個部分——
   - **機器人**：GitHub Actions 排程掃描 ＋ Telegram **圖＋文** 推播（第 7、8 節）
   - **PWA 手機 App**：GitHub Pages 靜態網站，資料由 Actions 匯出成 JSON（第 12 節）
   前端技術堆由你決定，但必須符合第 12.5 節的限制；選定後用一句話說明理由，不用問使用者。
5. **輸出格式**：完整檔案樹 ＋ 每個檔案的完整內容（不要用「…略」），再附安裝步驟與測試指令。長度不夠就分段輸出，但每個檔案必須完整。建議輸出順序：核心機器人（可直接沿用附錄 A）→ 圖片產生與 Telegram 圖文推播 → JSON 匯出 → PWA → 工作流程 → 測試。
6. **不得假設不存在的服務**：Google Flights 沒有官方 API；Amadeus Self-Service API 已於 2026-07-17 關閉；Kiwi.com Tequila API 僅開放 B2B 合作夥伴；Skyscanner／Trip.com／航空公司官網沒有公開 API。本專案只用第 4 節列出的三個外部服務。
7. **第 5 節的演算法與第 9 節的驗收測試是硬規格**：實作完成後必須通過第 9 節全部測試；附錄 A 的 `tests/test_logic.py` 可直接當測試檔。
8. 使用者是台灣人、懂程式與資料分析、重視成本效益與可驗證的紀錄。不用解釋基礎概念，但每個設計取捨請用一句話說明理由。

---

## 1. 一句話需求

> 定期掃描桃園⇄澳門直飛來回機票，用 Google Flights 的「典型價格區間」當平均價格基準，找到便宜一半以上的票立刻用 Telegram 通知我；便宜三成以上的票放進每日摘要。零成本、跑在雲端、不用自己開機器。

---

## 2. 決策紀錄（已拍板，不要重問）

| # | 項目 | 決定 | 理由 |
|---|---|---|---|
| 1 | 程式名稱 | **低飛 LowFly** | 低價機票 ＋ 低空飛行掃描 |
| 2 | 航線 | 桃園 TPE ⇄ 澳門 MFM，**只看直飛**，來回，1 位成人，幣別 TWD | 直飛航空只有長榮、澳門航空、台灣虎航、星宇四家，基準價一致性高 |
| 3 | 掃描窗口 | 未來 30 天的出發日，最快「後天」出發（min_lead_days=2），住 3／4／5 晚 | 29 個出發日 × 3 種住宿 ＝ **87 組日期組合** |
| 4 | 資料來源 | Travelpayouts（免費寬掃）＋ SerpAPI Google Flights（精查＋典型區間） | 兩者都免費；社群體感價延後到 v2 |
| 5 | 基準價 | Google `typical_price_range` 的**中點**，取最近 45 天觀測的中位數 | 客觀、可驗證；v2 預留混合權重（自有歷史、社群） |
| 6 | 通知分級 | ≤ 基準 **50%** 立刻推播；≤ 基準 **70%** 進每日摘要 | 50% 的票一年可能只有幾次，70% 讓程式有存在感 |
| 7 | 推播前提 | **立刻推播必須經 Google Flights（SerpAPI）驗證**；Travelpayouts 快取價只能進摘要並標「待驗證」 | 快取可能是幾天前的價格，避免假神票 |
| 8 | 執行環境 | GitHub Actions，一天 4 次（台北 09:17／15:17／21:17／03:17） | 免費、不用伺服器；狀態由 Actions commit 回 repo |
| 9 | 語言與依賴 | Python 3.12；只依賴 `requests`、`PyYAML` | 少依賴、好維護 |
| 10 | Telegram | 沿用使用者既有的 bot，從環境變數 `TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID` 讀 | 不另建 bot |
| 11 | SerpAPI 額度 | 免費 250 次／月 → 每天 8 次；每天 3 次保留給候選驗證；月底保留 10 次安全額；12 小時內驗證過且快取價未再降者不重驗 | 額度是唯一真正的瓶頸 |
| 12 | 去重 | 同一組日期已推播過，只有「再便宜 ≥3%」或「超過 48 小時」才重發 | 避免洗版 |
| 13 | 每日摘要 | 當地 09:00 之後的第一次執行發送，一天一則，即使沒有好價也發（兼心跳） | 確認程式活著 |
| 14 | App 形式 | **PWA**（加到手機主畫面），同時保留 Telegram 推播 | 不用上架、免費、iPhone／Android 通用 |
| 15 | 推播內容 | **一張簡單的圖 ＋ 簡短文字**（Telegram `sendPhoto` ＋ caption），不要長篇 | 使用者只要一眼看到重點；細節到 App 看 |
| 16 | App 功能 | 儀表板、87 組日期價格熱力圖＋單組歷史曲線、通知紀錄與事後回顧、設定頁（唯讀＋GitHub 編輯深連結）；細節見第 12 節，**不需再問使用者** | 使用者要求細節由實作者決定 |
| 17 | App 資料與主機 | GitHub Pages 靜態站（main 分支 `/docs` 目錄），Actions 每次掃描後匯出 JSON 到 `docs/data/` | 零後端、零成本；機票價格不是私密資料 |
| 18 | 前端技術堆 | 由實作者選，限制見第 12.5 節（手機優先、無後端、離線可看上次資料、零或極簡建置） | — |

---

## 3. 系統架構（漏斗）

```
每次執行（一天 4 次）
│
├─ 1. 產生 87 組（出發日, 回程日）
├─ 2. Travelpayouts 寬掃：抓涵蓋月份的整月快取價 → 每組日期取最低價（tp_best）
├─ 3. 用既有觀測算基準價 baseline（第 5.4 節）
├─ 4. 挑選本次要用 SerpAPI 精查的組合（第 5.3 節，受額度限制）
├─ 5. SerpAPI 精查 → 每組取最低價（verified）＋ 記錄 typical_price_range
├─ 6. 重新計算 baseline（剛拿到新區間）
├─ 7. 分級通知（第 5.5 節）＋ 維護每日摘要池（第 5.6 節）
├─ 8. 若到時間 → 送每日摘要（第 7.2 節）
├─ 9. 寫回 data/state.json、追加 data/history.jsonl
├─ 10. 匯出 PWA 用的 JSON 到 docs/data/（第 12.2 節）
└─ 11. Actions 把 data/ 與 docs/data/ 一起 commit；GitHub Pages 自動更新
```

---

## 4. 外部服務合約

### 4.1 SerpAPI — Google Flights（精查層，免費 250 次／月）

- `GET https://serpapi.com/search.json`
- 參數：

| 參數 | 值 |
|---|---|
| engine | `google_flights` |
| departure_id / arrival_id | `TPE` / `MFM` |
| outbound_date / return_date | `YYYY-MM-DD` |
| type | `1`（來回） |
| currency | `TWD` |
| hl / gl | `zh-tw` / `tw`（航空公司名稱會是中文） |
| adults | `1` |
| stops | `1`（只要直飛；0=不限） |
| api_key | 環境變數 `SERPAPI_API_KEY` |

- 回應中會用到的欄位：
  - `best_flights[]` 與 `other_flights[]`：每筆有 `price`（**來回總價**，1 位成人）、`flights[]`（航段；長度 1 代表直飛；`flights[0].airline` 是航空公司名）
  - `price_insights`：`lowest_price`、`price_level`（`low`／`typical`／`high`）、`typical_price_range: [low, high]`、`price_history: [[timestamp, price], …]`（約 60 天）
  - `search_metadata.google_flights_url`：可點的 Google Flights 連結，用在通知裡
- 錯誤：HTTP 200 但 body 有 `"error"` 欄位（例如額度用完）→ 視為失敗，**不計入額度**，本次停止再呼叫 SerpAPI，其餘流程照常。
- 第一次真實呼叫請在 log 印出 `typical_price_range`，確認是來回總價的區間（桃園–澳門直飛來回合理值約 NT$ 6,000～12,000）。

### 4.2 Travelpayouts（Aviasales）Data API — 寬掃層，免費

- `GET https://api.travelpayouts.com/aviasales/v3/prices_for_dates`
- 參數：`origin=TPE`、`destination=MFM`、`departure_at=YYYY-MM`（整月）、`one_way=false`、`direct=true`、`currency=twd`、`sorting=price`、`unique=false`、`limit=1000`、`page=1`、`token=`（環境變數 `TRAVELPAYOUTS_TOKEN`）
- 回應：`{ "success": true, "data": [ { "price", "airline"(IATA 碼), "flight_number", "departure_at"(ISO datetime), "return_at", "transfers", "return_transfers", "duration", "link"(相對路徑，前面接 `https://www.aviasales.com`) } ] }`
- 語意：**來自全球使用者搜尋的快取價，保存 2～7 天**，不是即時報價。桃園–澳門搜尋量不大，可能只有部分日期有資料；沒資料時程式要能退回純 SerpAPI 輪詢。
- 失敗（網路錯誤、`success=false`）→ 回傳空清單，不中斷流程。
- 航空 IATA → 中文：BR 長榮航空、NX 澳門航空、IT 台灣虎航、JX 星宇航空、CI 中華航空。

### 4.3 Telegram Bot API

- 圖＋文（主要用法）：`POST https://api.telegram.org/bot{TOKEN}/sendPhoto`，multipart：`chat_id`、`photo`（PNG 檔）、`caption`（HTML，**≤ 1024 字元**）、`parse_mode=HTML`
- 純文字（備援）：`POST …/sendMessage`，JSON：`{ "chat_id", "text": "<HTML>", "parse_mode": "HTML", "disable_web_page_preview": true }`
- 規則：圖片產生失敗 → 退回 sendMessage 送同樣文字；caption 超過 1024 → 圖片配短 caption，完整文字另發一則 sendMessage。
- 文字內的航空公司名、URL 要做 HTML escape。
- 沒有 token／chat_id 或 `--dry-run` 時，把文字印在 stdout、圖片存到 `out/` 目錄代替送出。

---

## 5. 核心演算法（硬規格，逐條實作）

### 5.1 日期組合
```
for lead in [min_lead_days .. days_ahead]:        # 2..30
    out = today + lead
    for n in stay_nights:                          # [3,4,5]
        pairs.append((out, out + n))
pair_key = f"{out}_{back}"                         # "2026-11-14_2026-11-17"
months_covering = pairs 出發日跨到的所有 YYYY-MM（給 Travelpayouts 用）
```
`today` 用設定檔的時區（Asia/Taipei）。

### 5.2 SerpAPI 額度
```
狀態：serpapi.{month, used_month, day, used_day}，月份／日期變了就歸零
per_run_cap    = ceil(daily_budget / runs_per_day) + 1        # 8/4 → 3
remaining_day  = daily_budget - used_day
remaining_month= monthly_quota - monthly_safety - used_month   # 250-10-used
budget_this_run= max(0, min(per_run_cap, remaining_day, remaining_month))
```
每次成功呼叫 `used_day += 1`、`used_month += 1`；失敗不計。

### 5.3 挑選本次要精查的組合
```
1. 候選 cands：
     若已有 baseline：tp_best 中 price/baseline ≤ thresholds.digest 的組合，依價格由低到高
     若還沒有 baseline（剛啟動）：tp_best 依價格由低到高（為了盡快拿到典型區間）
2. 跳過「最近才驗證過」的候選：
     pairs[k].last_serpapi 在 reverify_hours(12h) 內，且 tp 價格 > last_price × (1 - min_drop_ratio)
3. 從 cands 取最多 min(reserve_for_candidates=3, budget_this_run) 個
4. 剩餘額度用輪詢補滿：所有 87 組依 (last_serpapi 或 "", pair_key) 排序
     → 從沒查過的優先、最久沒查的次之、同條件出發日近的優先；跳過已選的
```

### 5.4 基準價
```
ranges = state.typical_ranges 中 at 在最近 lookback_days(45) 內、low/high 皆存在者
若 ranges 為空 → baseline = None（本次不通知，摘要寫「尚未取得基準」）
g_low  = median(low), g_high = median(high)
google = {low: g_low, mid: (g_low+g_high)/2, high: g_high}[baseline.google_stat]   # 預設 mid
own    = median(pairs[*].last_price)，只採 last_source == "serpapi" 且在 lookback 內者（v2 用）
social = None（v2）
value  = Σ(component × weight) / Σ(weight)，只對「有值且 weight>0」的成分正規化
         v1 權重：google_typical 1.0、own_history 0.0、social 0.0
ratio(price) = price / value
```

### 5.5 分級與去重
```
對每個本次 Google 驗證過的組合 (key, best_offer)：
  r = ratio(price)
  if r ≤ instant(0.50) and should_alert(key, price): 送「立刻推播」，alerts[key] = {price, at}
  if r ≤ digest(0.70): 摘要池[key] = offer + {ratio, verified: True, at}
  elif key in 摘要池: 刪除（驗證後其實不便宜）

對每個 Travelpayouts 組合但本次未驗證者：
  if r ≤ digest and 摘要池[key] 不是已驗證項：摘要池[key] = offer + {ratio, verified: False, at}
  （絕不觸發立刻推播）

should_alert(key, price):
  沒推播過 → True
  price ≤ 上次推播價 × (1 - 0.03) → True
  距上次推播 > 48 小時 → True
  否則 False
```

### 5.6 摘要池維護（每次執行都做）
- 刪除：出發日已過；未驗證項但這次 Travelpayouts 快取裡已經沒有它；已驗證項超過 7 天沒再驗證。
- 基準價更新後，重算池中每項的 `ratio`。
- 摘要池**不按日期清空**——昨天下午找到、今天還有效的好價要出現在今天的摘要。

### 5.7 狀態持久化
`data/state.json`：
```json
{
  "version": 1,
  "serpapi": {"month": "2026-11", "used_month": 12, "day": "2026-11-02", "used_day": 3},
  "pairs": {
    "2026-11-14_2026-11-17": {
      "last_serpapi": "ISO8601", "last_price": 5812, "last_airline": "台灣虎航", "last_url": "…", "last_source": "serpapi",
      "min_price": 5812, "min_at": "ISO8601", "price_level": "low",
      "tp_price": 5727, "tp_airline": "長榮航空", "tp_url": "…", "tp_at": "ISO8601"
    }
  },
  "typical_ranges": [{"at": "ISO8601", "pair": "key", "low": 7200, "high": 10000, "level": "low", "lowest": 5812}],
  "alerts": {"2026-11-14_2026-11-17": {"price": 3980, "at": "ISO8601"}},
  "digest_pool": {"items": {"key": {"…offer 欄位…", "ratio": 0.46, "verified": true, "at": "ISO8601"}}},
  "last_digest_date": "2026-11-02",
  "stats": {"alerts_sent": 0, "digests_sent": 0, "runs": 0}
}
```
- 出發日已過的 `pairs`／`alerts` 每次清掉；`typical_ranges` 只保留最後 400 筆。
- `data/history.jsonl`：每行一筆觀測 `{source, outbound, inbound, price, currency, airline, direct, url, observed_at, pair_key, nights}`。
  只記錄 SerpAPI 回傳的每筆航班，以及 Travelpayouts **價格有變動** 的組合（避免檔案暴增）。
- `--dry-run` 時不寫任何檔案。

---

## 6. 設定檔（`config.yaml`，完整內容見附錄 A）

旋鈕：`route.*`、`window.{days_ahead, min_lead_days, stay_nights}`、`thresholds.{instant, digest}`、
`baseline.{google_stat, lookback_days, min_observations, weights}`、`sources.serpapi.{monthly_quota, monthly_safety, daily_budget, reserve_for_candidates, reverify_hours}`、
`schedule.runs_per_day`、`digest.{hour_local, top_n}`、`dedupe.{min_drop_ratio, cooldown_hours}`。
改 cron 次數時 `schedule.runs_per_day` 要一起改。

---

## 7. 訊息模板（Telegram HTML，逐字照用）

### 7.1 立刻推播
```
🔥 <b>低飛 LowFly｜神票 ≤50%</b>
桃園 ⇄ 澳門 直飛來回（3 晚）
出發 11/14（六） → 回程 11/17（二）
<b>NT$ 3,980</b>（基準 NT$ 8,600，-54%）
航空：台灣虎航
Google 價位：low｜典型區間 NT$ 7,200～10,000
👉 <a href="…google_flights_url…">Google Flights 查看／訂票</a>
```
日期格式 `M/D（週）`，週用「一二三四五六日」；金額 `NT$ 3,980`；百分比 `-54%`（`(ratio-1)*100`，四捨五入到整數）。

### 7.2 每日摘要
```
📬 <b>低飛 LowFly｜每日摘要</b> 11/2（一）
桃園 ⇄ 澳門 直飛來回，未來 30 天、3～5 晚
基準價 <b>NT$ 8,600</b>（Google 典型區間 NT$ 7,200～10,000，近 45 天 12 筆）

目前好價（≤70%）：
• 11/14（六）→11/17（二） <b>NT$ 5,812</b>（-32%）台灣虎航 ✅已驗證 <a href="…">連結</a>
• 11/1（日）→11/5（四） <b>NT$ 5,727</b>（-33%）長榮航空 ⏳待驗證（Aviasales 快取） <a href="…">連結</a>
…另有 2 筆

目前已驗證最低：11/20（五）→11/23（一） NT$ 5,812（-32%，台灣虎航）
SerpAPI 本月 12/250｜Travelpayouts 快取 46 組日期
```
- 依 ratio 由低到高，最多 `digest.top_n`（5）筆；沒有好價時改印「目前沒有低於基準 70% 的票。」
- 沒有基準時印「基準價：尚未取得 Google 典型區間（程式剛啟動或 SerpAPI 額度用完）」。

### 7.3 測試訊息（`--test-telegram`）
```
✈️ <b>低飛 LowFly</b> 測試訊息
桃園 ⇄ 澳門｜2026-11-02 09:30
bot 設定正確，之後的通知會出現在這裡。
```

### 7.4 推播圖片（簡單、一眼看懂；Pillow 產生 PNG）

共同規格：1200×675、白底或淺底、字體 **Noto Sans CJK**（workflow 安裝 `fonts-noto-cjk`，程式從 `/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc` 載入，找不到就退回 DejaVu 並在 log 警告）。不要花俏，只要大字清楚。

**7.4.1 立刻推播卡片**（配第 7.1 節文字當 caption）
```
┌──────────────────────────────────────────────┐
│ 低飛 LowFly                        🔥 神票    │  ← 左上標題，右上標籤（綠底白字）
│                                              │
│ 桃園 ⇄ 澳門 直飛來回 · 3 晚                   │
│ 11/14（六） → 11/17（二）                     │
│                                              │
│ NT$ 3,980                        -54%        │  ← 價格 120px 粗體；折扣 72px 綠色
│ 基準 NT$ 8,600 · 台灣虎航                     │
│                                              │
│ ▁▂▃▅▆▇█  (該組日期的 price_history 迷你曲線)   │  ← 有 price_history 才畫，沒有就省略
└──────────────────────────────────────────────┘
```

**7.4.2 每日摘要熱力圖**（配第 7.2 節文字當 caption；超過 1024 字元時另發文字訊息）
- 標題列：`低飛 LowFly · 每日摘要 11/2（一） · 基準 NT$ 8,600`
- 主體：**29 欄（出發日）× 3 列（3／4／5 晚）** 的格子，每格依 `ratio` 上色：
  ≤0.50 深綠、≤0.70 綠、≤0.85 淺綠、≤1.00 灰、>1.00 淡紅、沒資料 白底虛線框；格內印價格千位數（如 `5.8k`），已驗證加小勾
- 欄標：日期 `11/4`，週末欄底色淡黃
- 底列：`SerpAPI 本月 12/250 · Travelpayouts 46 組 · 更新 11/2 09:17`
- `ratio` 來源：該組 `last_price`（Google 驗證）優先，其次 `tp_price`（快取）

**7.4.3 檔案**：圖片存 `out/alert_<pair_key>.png`、`out/digest_<date>.png`；`out/` 進 `.gitignore`，不 commit。

---

## 8. 執行方式

### 8.1 CLI（`python -m lowfly.main`）
| 旗標 | 行為 |
|---|---|
| （無） | 正式執行：打 API、送通知、寫 state／history |
| `--dry-run` | 打 API，但通知印在 stdout、不寫檔 |
| `--mock` | 用內建假資料取代兩個 API（不需金鑰），固定埋幾張神票與好價供檢視格式 |
| `--force-digest` | 不管時間，立刻送每日摘要 |
| `--test-telegram` | 只送一則測試訊息 |
| `-v` | debug log |

缺少環境變數時：警告並跳過對應來源，不要 crash。

### 8.2 GitHub Actions（`.github/workflows/scan.yml`）
- `schedule: cron "17 1,7,13,19 * * *"`（UTC → 台北 09:17／15:17／21:17／03:17）
- `workflow_dispatch` 的 `mode` 輸入：`normal / dry-run / test-telegram / force-digest / mock`
- `permissions: contents: write`；`concurrency: lowfly-scan`
- 步驟：checkout → setup-python 3.12 → `sudo apt-get install -y fonts-noto-cjk` → `pip install -r requirements.txt` → 依 mode 執行（內含 JSON 匯出，第 12.2 節）→ `git add data/ docs/data/` 有變更才 commit（訊息含 `[skip ci]`）→ `git pull --rebase --autostash` → push
- 4 個 Secrets：`SERPAPI_API_KEY`、`TRAVELPAYOUTS_TOKEN`、`TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`
- 依賴：`requests`、`PyYAML`、`Pillow`（只為了畫圖；不要引入 matplotlib 以外的重依賴，matplotlib 也可不用）
- GitHub Pages：repo Settings → Pages → Source = `Deploy from a branch`，Branch = `main`，Folder = `/docs`。Actions 每次 commit `docs/data/*.json` 後 Pages 自動重新發佈（約 1 分鐘）。

---

## 9. 驗收測試（全部必須通過；附錄 A 的 `tests/test_logic.py` 已實作）

所有測試以假的 SerpAPI／Travelpayouts 函式注入，不打真 API。固定時間 2026-11-02（一）09:30 台北，典型區間 (7200, 10000) → 基準 8,600。

| # | Given | When | Then |
|---|---|---|---|
| 1 | today=11/2、30 天、lead 2、住 [3,4,5] | 產生日期組合 | 87 組；第一組 (11/4, 11/7)；最後一組 (12/2, 12/7)；涵蓋月份 ["2026-11","2026-12"] |
| 2 | — | 格式化 | `2026-11-14`→`11/14（六）`；3980→`NT$ 3,980`；0.46→`-54%` |
| 3 | 沒有任何典型區間 | 算基準 | None |
| 4 | 區間 (7000,10000)、(7400,10000) | 算基準 | median low 7200、high 10000 → 8,600 |
| 5 | 只有 60 天前的區間 | 算基準 | None（超過 lookback） |
| 6 | 權重 google 0.5／own 0.5，區間 (7200,10000)，自有驗證價 7000、9000 | 算基準 | (8600+8000)/2 |
| 7 | 第一次執行，無基準；TP 有 5200、6100、8900 三組 | 執行 | SerpAPI 恰好 3 次；前兩次是 5200、6100 那兩組；基準 8600；09:30 → 摘要已送；used_day=3 |
| 8 | 有基準；TP 說某組 3,900，Google 驗證是 8,500 | 執行 | 立刻推播 0 則；該組不在摘要池 |
| 9 | 有基準；TP 3,900、Google 3,980 | 執行三次：同價 1 小時後；再降到 3,700 | 第一次推播 1 則（含「神票」「NT$ 3,980」「-54%」「長榮航空」）；第二次 0 則；第三次 1 則 |
| 10 | 有基準；今日額度已用完 8 次；TP 有 5500、5900 兩組 | 執行（強制摘要） | SerpAPI 0 次；摘要池兩項皆 verified=False；摘要含「待驗證」「目前好價」；下次 TP 快取消失 → 摘要池清空 |
| 11 | 本月已用 240 次 | 執行 | SerpAPI 0 次（250−10 安全額） |
| 12 | SerpAPI 函式丟例外「run out of searches」 | 執行 | 0 次成功、errors 1 筆、used_day 仍為 0、流程不中斷 |
| 13 | 有基準、有一張神票 | 產生推播卡片 | `out/alert_<key>.png` 存在、1200×675、能被 Pillow 重新開啟；caption 與第 7.1 節一致且 ≤1024 字元 |
| 14 | 87 組中 10 組有 `last_price`、20 組有 `tp_price`、其餘無資料 | 產生摘要熱力圖 | PNG 存在、1200×675；無資料格不會導致例外 |
| 15 | 執行完一次掃描 | 匯出 JSON | `docs/data/summary.json`、`pairs.json`、`history.json`、`alerts.json` 皆存在、符合第 12.2 節 schema、`generated_at` 為本次時間；`pairs.json` 恰好 87 筆 |
| 16 | Pillow 字體檔不存在 | 產生圖片 | 不 crash，退回預設字體並 log 警告；若整個畫圖失敗，Telegram 改用 sendMessage 送文字 |

---

## 10. 已知限制與不可違反的原則

1. Travelpayouts 覆蓋率不保證；沒資料時退回純 SerpAPI 輪詢（87 組約 11 天輪完）。
2. Google Flights 價格可能比航空官網慢 15～30 分鐘；LCC 官網快閃促銷不一定反映（v2）。
3. 典型區間是 Google 對該組日期的判斷，旺季會整體上移；「-50%」是相對當下的。
4. **不訂票**，只給 Google Flights 連結。
5. **絕不**用 Travelpayouts 快取價觸發立刻推播。
6. **絕不**超過 SerpAPI 月額度；失敗不計額度但要停止當次後續呼叫。
7. 任何外部 API 失敗都不能讓程式 crash 或亂發通知；log 清楚即可。

---

## 11. v2 路線圖（不在本次交付範圍，但架構要預留）

1. 月報回顧：推播命中率（推播時的折扣 vs. 事後同組日期走勢），校準思維。
2. 社群校正價：PTT 站內搜尋「澳門 機票」、背包客棧港澳版 → `baseline.weights.social`。
3. 免費寬掃：`faster-flights`（Python 爬 Google Flights）每天全掃 87 組，SerpAPI 只留驗證。
4. LCC 官網促銷頁監控。
5. 多航線：`route` 改 list，額度按航線分配。
6. App 內直接改門檻／航線（用 fine-grained PAT 透過 GitHub Contents API 寫回 `config.yaml`）。

---

## 12. App 格式（PWA，硬規格）

### 12.1 定位
手機上的「低飛儀表板」：Telegram 推播負責**叫你看**，App 負責**讓你看清楚**。
沒有登入、沒有後端、沒有寫入；所有資料是 Actions 匯出的靜態 JSON。加到主畫面後像原生 App，離線時顯示上次載入的資料並標示時間。

### 12.2 資料合約（Actions 每次掃描後匯出到 `docs/data/`，由 `lowfly/export.py` 產生）

所有檔案 UTF-8 JSON，都有 `generated_at`（ISO8601，含時區）。

**`summary.json`** — 儀表板首頁用
```json
{
  "generated_at": "2026-11-02T09:17:40+08:00",
  "app": "低飛 LowFly", "route": {"origin": "TPE", "destination": "MFM", "label": "桃園 ⇄ 澳門"},
  "window": {"days_ahead": 30, "min_lead_days": 2, "stay_nights": [3, 4, 5]},
  "thresholds": {"instant": 0.5, "digest": 0.7},
  "baseline": {"value": 8600, "google_low": 7200, "google_high": 10000, "n_ranges": 12, "lookback_days": 45},
  "budget": {"serpapi_used_month": 12, "serpapi_quota": 250, "serpapi_used_day": 3, "serpapi_daily": 8, "tp_pairs": 46},
  "deals": [
    {"pair_key": "2026-11-14_2026-11-17", "outbound": "2026-11-14", "inbound": "2026-11-17", "nights": 3,
     "price": 5812, "ratio": 0.676, "airline": "台灣虎航", "verified": true, "at": "2026-11-02T09:17:40+08:00", "url": "https://www.google.com/travel/flights?…"}
  ],
  "cheapest_verified": {"pair_key": "…", "price": 5812, "ratio": 0.676, "airline": "台灣虎航", "url": "…"},
  "stats": {"alerts_sent": 2, "digests_sent": 9, "runs": 38}
}
```
`deals` ＝ 摘要池全部項目，依 ratio 升冪。

**`pairs.json`** — 熱力圖用，**恰好 87 筆**，沒資料的組合也要有（價格欄為 null）
```json
{
  "generated_at": "…",
  "baseline": 8600,
  "pairs": [
    {"pair_key": "2026-11-04_2026-11-07", "outbound": "2026-11-04", "inbound": "2026-11-07", "nights": 3,
     "price": 8700, "source": "serpapi", "ratio": 1.012, "airline": "長榮航空", "verified": true,
     "checked_at": "2026-11-01T21:17:00+08:00", "price_level": "typical", "tp_price": 8900, "url": "…"}
  ]
}
```
`price`／`source`：有 `last_price` 用 Google 驗證價，否則用 `tp_price`，都沒有則 null；`ratio` 隨之。

**`history.json`** — 單組日期的歷史曲線用；由 `data/history.jsonl` 彙整，每組日期保留最近 60 個觀測點
```json
{"generated_at": "…", "series": {"2026-11-14_2026-11-17": [["2026-10-30T09:17:00+08:00", 6100, "travelpayouts"], ["2026-11-01T15:17:00+08:00", 5812, "serpapi"]]}}
```

**`alerts.json`** — 通知紀錄與事後回顧
```json
{"generated_at": "…", "alerts": [
  {"pair_key": "2026-11-14_2026-11-17", "alerted_at": "…", "price_at_alert": 3980, "ratio_at_alert": 0.463, "baseline_at_alert": 8600,
   "latest_price": 4200, "min_price_after": 3980, "outbound": "2026-11-14", "inbound": "2026-11-17", "airline": "台灣虎航",
   "verdict": "低點"}
]}
```
`verdict`：`latest_price ≥ price_at_alert × 1.05` → 「低點」；`latest_price ≤ price_at_alert × 0.95` → 「還有更低」；其餘「持平」；出發日已過 → 「已結束」。
為了做這個回顧，`state.json` 的 `alerts[key]` 要多存 `baseline_at_alert`、`ratio`、`airline`、`outbound`、`inbound`；**已推播的組合出發日過了也保留 90 天**（第 5.7 節的清理規則對 `alerts` 改為 90 天）。

### 12.3 畫面（四個分頁，底部 tab bar）

1. **首頁**：基準價卡（值、Google 區間、觀測數）→ 「目前好價」清單（同每日摘要，每筆：日期、晚數、價格、折扣、航空、✅／⏳、「Google Flights」按鈕開新分頁）→ 額度列（SerpAPI 月／日、Travelpayouts 組數）→ 更新時間（相對時間，如「12 分鐘前」；超過 8 小時變橘色警示「資料可能過期」）。
2. **日曆**：29 欄 × 3 列熱力圖，配色與第 7.4.2 節相同，可橫向捲動；點一格 → 底部彈出該組日期：價格、來源、驗證時間、Google 價位、歷史曲線（`history.json`）、Google Flights 按鈕。上方可切換「只看 ≤70%」篩選。
3. **紀錄**：`alerts.json` 清單，每筆顯示推播價、當時折扣、現在價、事後判定（低點／還有更低／持平／已結束）；頂部統計：推播總數、「低點」比例（＝程式命中率）。
4. **設定**：唯讀顯示 `summary.json` 裡的航線、窗口、門檻、額度設定；一顆按鈕「在 GitHub 編輯 config.yaml」（深連結到 `https://github.com/<owner>/<repo>/edit/main/config.yaml`，owner／repo 寫在 `docs/config.js` 常數）；一顆「清除離線快取」。

### 12.4 PWA 必備
- `docs/manifest.webmanifest`：`name` 低飛 LowFly、`short_name` 低飛、`display: standalone`、`theme_color`、`background_color`、192／512 icon（SVG 畫一個簡單紙飛機＋向下箭頭即可，再轉 PNG；不要用任何既有品牌圖）。
- `docs/sw.js`：App shell（HTML／CSS／JS／icon）cache-first；`data/*.json` network-first、失敗退回 cache；版本字串變更時清舊 cache。
- iOS 補丁：`apple-touch-icon`、`apple-mobile-web-app-capable`、安全區 `env(safe-area-inset-*)`。
- 手機優先：寬 360～430px 為主要版面；深色模式跟隨系統。
- 所有金額 `NT$ 5,812`、日期 `11/14（六）`、折扣 `-32%`，與 Telegram 一致。

### 12.5 前端技術堆的限制（由實作者選，符合即可）
- 純靜態：GitHub Pages 能直接服務，**不得**需要伺服器端程式。
- 建置：零建置（單檔 HTML ＋ 原生 JS ＋ CDN 圖表庫）**或**極簡建置（Vite 之類，但產物要 commit 到 `docs/`，Actions 不另跑 build）。
- 相依：圖表可用 Chart.js／uPlot／手刻 SVG；不要引入需要後端或帳號的服務。
- 路徑：所有資源用相對路徑（Pages 會在 `/<repo>/` 子路徑下）。
- 可測：至少一個靜態檢查（JSON schema 驗證或 `node --check`）放進 workflow 可選步驟。

### 12.6 安裝到手機
README 要寫：iPhone Safari → 分享 → 加入主畫面；Android Chrome → 選單 → 安裝應用程式。Pages 網址格式 `https://<owner>.github.io/<repo>/`。

---

## 附錄 A：參考實作（Python 3.12，已通過第 9 節全部測試）

以下每個檔案都是完整內容，檔名即路徑。這是**核心機器人**（掃描、額度、基準、分級、純文字 Telegram），已通過第 9 節測試 1～12。
在此之上你還要補齊（第 9 節測試 13～16）：

1. `lowfly/render.py`：第 7.4 節的兩種 PNG（Pillow）。
2. `lowfly/notifier.py`：加 `send_photo(png_path, caption_html)`，含 1024 字元與失敗退回規則（第 4.3 節）；`scanner.py` 的 `_send_instant` 與 `_maybe_digest` 改為先畫圖再 `send_photo`。
3. `lowfly/export.py`：第 12.2 節四個 JSON 寫到 `docs/data/`；`main.py` 在 `save_state` 之後呼叫（`--dry-run` 不寫）。
4. `scanner.py`：`alerts[key]` 多存 `baseline_at_alert`、`ratio`、`airline`、`outbound`、`inbound`；`_prune_pairs` 對 `alerts` 改為出發日過後保留 90 天。
5. `.github/workflows/scan.yml`：加 `sudo apt-get install -y fonts-noto-cjk`、`git add data/ docs/data/`。
6. `requirements.txt`：加 `Pillow>=10`。
7. `docs/`：整個 PWA（第 12.3～12.5 節）。

若改寫成其他語言或架構，行為必須與第 5、7、9、12 節一致。
