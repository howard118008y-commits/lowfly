# 低飛 LowFly

桃園 TPE ⇄ 澳門 MFM，直飛來回、1 位成人、TWD。GitHub Actions 每天掃描四次；≤基準 50% 且經 Google Flights 驗證即以 Telegram 圖文通知，≤70% 收進每日摘要。PWA 放在 GitHub Pages 的 `main /docs`，免登入、免後端。

## 專案內容

依建置順序提供：核心掃描器 → Pillow 圖片與 Telegram 圖文 → 四份 JSON → 四分頁 PWA → Actions → 離線驗收測試。

只使用 SerpAPI、Travelpayouts 與 Telegram Bot API；Google Flights 連結僅供使用者自行查看／訂票，不是另一個 API。未接 Amadeus、Kiwi 或任何航空公司爬蟲。

## 本機安裝

需要 Python 3.12；Node.js 22 以上只用於前端測試，不是 App 執行依賴。

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

Windows 啟用虛擬環境請用 `.venv\Scripts\Activate.ps1`。

Ubuntu／GitHub runner 的中文字體：

```bash
sudo apt-get update
sudo apt-get install -y fonts-noto-cjk
```

字體預設位置為 `/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc` 與 `NotoSansCJK-Bold.ttc`。找不到時會警告並退回 DejaVu；若連 DejaVu 都缺少，使用 Pillow 預設字體。後兩種情況部分中文字可能缺字，但流程可繼續，整個繪圖失敗才改送文字。

## 先看模擬結果

不需金鑰、不連線、不發出 Telegram：

```bash
python -m lowfly.main --mock --force-digest --now '2026-11-02T09:30:00+08:00'
python scripts/check_exports.py out/mock/docs/data
python -m http.server 8000 --directory out/mock/docs
```

開啟 `http://localhost:8000/`。模擬狀態在 `out/mock/data/`、PWA 在 `out/mock/docs/`、PNG 在 `out/mock/out/`，均與正式資料隔離；頁面頂端有「模擬資料」標示。`out/` 不進版控。

只看文字且完全不寫檔：

```bash
PYTHONDONTWRITEBYTECODE=1 python -m lowfly.main --mock --dry-run --force-digest
```

`PYTHONDONTWRITEBYTECODE=1` 同時避免 Python 自行建立位元碼快取；程式的 dry-run 不寫 state、history、JSON、PNG 或模擬 App shell。

## 設定四個 GitHub Secrets

建立一個 GitHub repo，預設分支使用 `main`，上傳本專案的全部檔案，包含 `.github/`。

若使用 Git，先在 GitHub 建立空 repo，再於專案根目錄執行（把 URL 換成自己的 repo）：

```bash
git init -b main
git add .
git commit -m "feat: implement LowFly scanner and PWA"
git remote add origin https://github.com/<owner>/<repo>.git
git push -u origin main
```

前往 **Settings → Secrets and variables → Actions → New repository secret**：

| Secret | 內容 |
| --- | --- |
| `SERPAPI_API_KEY` | 自己帳戶的 SerpAPI 金鑰 |
| `TRAVELPAYOUTS_TOKEN` | Travelpayouts 個人檔案內的 Data API token |
| `TELEGRAM_BOT_TOKEN` | 既有 Telegram bot 的 token |
| `TELEGRAM_CHAT_ID` | 要接收通知的既有對話 chat ID |

金鑰只填 Secrets；不要放進 `config.yaml`、`docs/config.js`、Issue、截圖或公開 JSON。請先與既有 bot 開始對話，再填入正確 chat ID。

本機正式掃描可由自己的 shell 設定同名環境變數；本專案不會自動讀 `.env`。缺少任一來源金鑰就警告並跳過該來源；缺少 Telegram 設定只預覽文字與產生圖片，不把預覽標為已送達。

## GitHub Pages 設定

1. 開啟 repo 的 **Settings → Pages**。
2. **Source** 選 **Deploy from a branch**。
3. **Branch** 選 `main`，**Folder** 選 `/docs`，按 **Save**。
4. 等首次建置完成，網址為 `https://<owner>.github.io/<repo>/`。
5. 修改 `docs/config.js` 的 `owner`、`repo`，例如填入你剛建立的帳號與 repo 名稱；`branch` 維持 `main`。標準 Pages 網址也能自動推得 owner／repo，自訂網域必須填常數。
6. 在 **Settings → Actions → General → Workflow permissions** 允許工作流程寫入 repo；工作流程會明確要求 `contents: write` 與 `pages: write`。

GitHub 以 `GITHUB_TOKEN` 推送的 commit 不會自行觸發 Pages build，因此掃描工作流程在 push 成功後明確呼叫 GitHub 內建的 Pages build 端點；這是發布動作，機票資料來源仍只有規格指定的三個服務，不需新增 Secret 或 PAT。Pages 必須先依上述步驟啟用，否則最後的 Pages build 步驟會失敗並保留錯誤供檢查。

官方說明：

- [GITHUB_TOKEN 與 Pages 觸發限制](https://docs.github.com/en/actions/concepts/security/github_token)
- [Pages build 請求與 Pages write 權限](https://docs.github.com/en/rest/pages/pages#request-a-github-pages-build)

Pages 的啟用、帳戶方案與 repo 可見性依自己的 GitHub 帳戶為準；本專案沒有購買方案或任何自動付費動作。公開 repo／Pages 不得放入個資與金鑰。

## 開始雲端掃描

前往 **Actions → LowFly scan → Run workflow**，先使用 `mock` 看格式，再選 `test-telegram` 驗證真實推播，最後選 `normal`。

| mode | 動作 | 寫入正式資料 |
| --- | --- | --- |
| `normal` | 正式掃描與依門檻通知 | 是 |
| `dry-run` | 呼叫真實價格來源，只印通知，不畫圖、不存檔 | 否 |
| `test-telegram` | 只送一則測試文字 | 否 |
| `force-digest` | 正式掃描並強制送每日摘要 | 是 |
| `mock` | 假來源＋圖片＋PWA 預覽，結果保留成 Actions artifact | 否 |

手動執行可取消 `run_checks` 以略過離線檢查；排程仍執行檢查。排程 UTC `17 1,7,13,19 * * *`，即台北 09:17、15:17、21:17、03:17。Actions 排程可能延遲；免費公共 repo 長期無活動時，GitHub 可能停用排程，屆時在 Actions 重新啟用。

有更改才 commit `data/` 與 `docs/data/`，commit 訊息包含 `[skip ci]`，並在 push 前 rebase；衝突時明確失敗，不 force-push、不吞掉衝突。

## 額度與狀態

SerpAPI 依規格以 250／月、每日 8 次、保留 10 次安全額計算，單次最多 3 次；成功才計數，失敗立即停止本次後續精查。請勿讓同一金鑰同時被其他 repo 或工具共用，因為本專案只能追蹤自己的 state；`--dry-run` 仍會消耗供應商額度，但依規格不持久化計數，正式金鑰的 dry-run 應節制使用並核對供應商剩餘量。免費方案資格與實際剩餘額度以供應商帳戶為準。

`data/state.json`、`data/history.jsonl` 是正式資料，不應刪除或以模擬資料取代；刪除 state 會失去本地額度與去重記錄。毀損 state 會停止執行，避免無聲重置額度。`config.yaml` 改 cron 次數時，`schedule.runs_per_day` 必須同步調整。

Travelpayouts 是快取，只能進「待驗證」摘要；當次已成功精查但沒票，會移除舊的 Google 價格與摘要，不以過期神票繼續通知。基準暫缺時仍會清理摘要池，但不判斷折扣。Google 驗證過的摘要保留最多 7 天；通知紀錄保留至出發後 90 天。

每次摘要至多 5 筆；圖文 caption 長於 1024 字元會改短 caption 加完整文字訊息；繪圖或圖片傳送失敗會退回文字。只有 Telegram 確認成功才更新通知狀態。Telegram 沒有本專案可用的冪等鍵，若供應商實際收件但網路逾時，後續重試仍可能重複一次。

## JSON 與 PWA

| 檔案 | 用途 |
| --- | --- |
| `docs/data/summary.json` | 基準、全部好價、最低 Google 價、額度與設定 |
| `docs/data/pairs.json` | 完整 87 組日期；Google 價優先、其次快取、無資料為 null |
| `docs/data/history.json` | 每組最近 60 筆 `[時間, 價格, 來源]` |
| `docs/data/alerts.json` | 每一次通知、當時折扣、最新價與事後判定 |

四個檔案共用含時區的 `generated_at`，無金鑰、無 chat ID。原始歷史記錄保留各航班；通知回顧先取每次 Google 搜尋的最低價，避免把同次較貴航班誤當成漲價。過期組合 90 天後不再匯出，原始 JSONL 仍可自行稽核。

首次交付的 `docs/data/` 是空狀態，基準與價格為 null，頁面顯示等待首次掃描，不把模擬報價當成真實資料。要預覽完整 UI 請跑 `--mock`。

PWA 有首頁、87 格日曆與歷史曲線、通知紀錄、唯讀設定；資料超過 8 小時會標示「資料可能過期」。App shell 採 cache-first，JSON 採 network-first；四份 JSON 批次時間不同時保留上一份一致快取。快取依 Pages 子路徑區分，清除本 App 不會刪除同網域其他專案。前端全相對路徑、無 CDN、無前端帳號或 token。

設定頁可清除離線快取；更新 HTML／JS／CSS／圖示時需一起提高 `docs/sw.js` 的 `VERSION`。離線只提供上次載入的資料，不會在手機背景查票或推播；通知仍由 Telegram 提供。

## 加入手機主畫面

- iPhone：在 **Safari** 開啟 Pages 網址 → **分享** → **加入主畫面** → **加入**。
- Android：在 **Chrome** 開啟 Pages 網址 → 右上 **選單** → **安裝應用程式**／**加到主畫面**。
- 第一次請保持連線載入資料，之後離線可看最後一次快取與時間；iOS 或瀏覽器可能清理久未使用的網站資料。

## 本機測試

```bash
python -m pytest -q
node --check docs/app.js
node --check docs/utils.js
node --check docs/config.js
node --check docs/sw.js
node --test tests/frontend.test.cjs
python scripts/check_exports.py
```

只跑規格第 9 節 1～16 項：

```bash
python -m pytest -q tests/test_acceptance.py
```

測試全面封鎖真實網路，來源與 Telegram 都以假的函式／HTTP 回應注入；不消耗 API 額度、不傳真通知。驗收 13、14 重新開啟產出的 PNG 檢查 1200×675，驗收 16 同時驗字體備援與改用 sendMessage。前端另執行真實 Service Worker 程式的模擬快取測試。

重製圖示：

```bash
python scripts/generate_icons.py
```

## 重要設計取捨

- 原生 JS＋SVG：免建置、免 CDN，App shell 可以完整離線。
- `Pillow` 為唯一繪圖依賴：卡片與 87 格熱力圖不需 matplotlib。
- 模擬與正式目錄隔離：避免假價格污染額度、去重或公開資料。
- 以正式規格第 12 節補充覆蓋附錄：通知保留 90 天、四份 JSON 獨立匯出、設定頁只讀。
- 圖片失敗才退文字：保留可讀通知而不阻塞掃描。
- 缺 Telegram 憑證不計已發送：補好憑證後仍能收到第一則通知。
- 90 天通知事件另保留 `alert_history`：同一日期多次降價推播也能逐筆回顧。
- 額外 `pages: write` 僅用發布 build：保留既定 `main /docs` 與四個 Secrets。

## 來源文件

- [SerpAPI Google Flights](https://serpapi.com/google-flights-api)
- [Travelpayouts Aviasales Data API](https://support.travelpayouts.com/hc/en-us/articles/203956163-Aviasales-Data-API)
- [Telegram Bot API sendPhoto](https://core.telegram.org/bots/api#sendphoto)

完整檔案樹見 `FILE_TREE.txt`；逐檔完整內容另以交付的完整原始碼檔案提供，PNG 原始位元組亦附 Base64，不使用省略內容。

自行重製交付包：

```bash
python scripts/package_source.py --output ../release
```
