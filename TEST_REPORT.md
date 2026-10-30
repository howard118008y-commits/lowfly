# LowFly 驗收結果

本次以 Python 3.12、假 SerpAPI／Travelpayouts／Telegram 回應驗收；測試會攔截真實網路。以下「通過」指本機可重現驗收，不代表已設定帳戶、已成功推播到真實聊天或已在 GitHub 執行。

## 規格第 9 節

固定時間 `2026-11-02T09:30:00+08:00`；Google 典型區間 7,200～10,000；基準 8,600。

| # | 驗收 | 結果 |
| --- | --- | --- |
| 1 | 87 組日期、首末日期、跨月列表 | 通過 |
| 2 | 繁中日期、金額、折扣 | 通過 |
| 3 | 無典型區間時基準為 None | 通過 |
| 4 | 區間上下界各取中位數，基準 8,600 | 通過 |
| 5 | 忽略 60 天前區間 | 通過 |
| 6 | Google 與自有觀測混合基準 8,300 | 通過 |
| 7 | 啟動候選優先、成功三次、09:30 發摘要 | 通過 |
| 8 | TP 3,900／Google 8,500 不推播、不進摘要 | 通過 |
| 9 | 同價去重、再降價重發、模板關鍵文字 | 通過 |
| 10 | 每日額度滿時只用待驗證摘要；快取消失移除 | 通過 |
| 11 | 月用量 240 時不再呼叫 | 通過 |
| 12 | SerpAPI 例外不計成功、停止本次後續呼叫 | 通過 |
| 13 | 神票 PNG 可重新開啟、1200×675、完整 caption 相符且 ≤1024 | 通過 |
| 14 | 10 格 Google／20 格快取／57 格無資料仍可產 PNG | 通過 |
| 15 | 四份 JSON、時間一致、完整 87 筆與資料合約 | 通過 |
| 16 | 缺字體仍產圖並警告；畫圖失敗真的改呼叫 sendMessage | 通過 |

## 追加驗證

Python 共 57 項通過，包含上面 16 項與 41 項邊界／失敗備援檢查：每日四次合計最多 8 次、月末精確停在 240、日月重置、12 小時候選不繞回重驗、48 小時與 3% 邊界、摘要一次／強制、空驗證清除舊價、來源失敗、caption 超限、Telegram HTTP／body／連線失敗、90 天保留、60 點歷史、dry-run 零寫入、模擬隔離、毀損狀態不歸零、workflow cron／權限／模式／回寫合約。

Node.js 共 10 項通過：格式與 Telegram 一致、六種配色、HTML／URL 安全、相對時間、批次一致性、Pages 相對路徑與圖示、Service Worker JSON network-first／斷線 fallback、shell cache-first、舊版快取清除範圍、首次離線 503。

四個 JS 檔的 `node --check` 通過；四份實際空狀態 JSON 的合約檢查通過；模擬掃描匯出的 JSON 合約檢查通過。

## 畫面檢查

- 開啟兩種模擬 PNG：中文可讀、價格與折扣清楚、圖像為 1200×675。
- Chromium 本機預覽：首頁、87 格日曆、單組詳情／SVG 曲線、通知紀錄、唯讀設定可操作。
- 以 360／390／430px 寬 iframe 檢查手機排版：底部分頁可用、熱力圖在自身容器橫捲、設定值可換行。
- 歷史曲線同一時間有多家航空時，採 Google 最低價優先，避免同次不同報價形成誤導的直線漲跌。

## 尚需在使用者環境驗證

真實 SerpAPI 典型區間與帳戶額度、Travelpayouts 覆蓋率、Telegram 實際送達、GitHub Actions push／Pages build、iPhone／Android 真機加入主畫面均未啟用；README 已提供完整設定與測試步驟。本次沒有讀取或填入使用者金鑰、沒有購買服務、沒有發送真通知、沒有發布網站。

## 重現指令

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
node --check docs/app.js
node --check docs/utils.js
node --check docs/config.js
node --check docs/sw.js
node --test tests/frontend.test.cjs
python scripts/check_exports.py
python -m lowfly.main --mock --force-digest --now '2026-11-02T09:30:00+08:00'
python scripts/check_exports.py out/mock/docs/data
```


## UI 1.1.0 精簡介面驗收（2026-10-30）

- 沿用原專案；本次只調整 PWA 呈現、原創圖示配色與前端測試，不改機票來源、門檻、Secrets 或正式資料。
- Python 57 項全過；前端由 10 項增加至 13 項，全過；四份 JSON 合約檢查通過。
- 新增驗證：未驗證快取不能成為主卡、最低票價不重複且其他日期可展開、首次離線能顯示可恢復的錯誤。
- 瀏覽器實測：360／390／430px 無橫向溢出；全部 87 組日曆可選；點格開詳情、展開歷史、好價篩選與更多頁收合正常。
- 深色樣式以同份 CSS 的測試副本強制啟用後目視確認；正式版維持跟隨系統。
- 預覽票價均來自隔離的本機 mock，不代表真實來源或 Telegram 驗證成功。

## 部署檢查修正（2026-10-30）

- Actions 在任何掃描前檢查模式所需 Secrets；缺少時以失敗結束，只輸出缺少的名稱，不更新正式資料。
- 新增六種模式／就緒狀態組合的 Bash 實際執行測試，確認 mock 不需金鑰、Telegram 與 dry-run 僅需要各自設定、正式掃描缺設定會失敗，且不輸出測試值。
- Python 63 項全過；前端 13 項全過。這是離線驗收，不代表已完成真實查價。
