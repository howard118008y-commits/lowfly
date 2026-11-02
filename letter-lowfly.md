# LowFly 交接信

> 改寫：2026-11-02 22:50（台北）。這是現況快照，不是 changelog，歷史請看 `git log`。
> 放在 repo 根目錄而不是 `docs/`：`docs/` 是 GitHub Pages 網站根目錄，放進去會被當成公開網頁。本 repo 是 **PUBLIC**，這份信只寫技術資訊；私密細節用 `memory: <name>` 引用（位置是本機 `~/.claude/projects/...LowFly/memory/`）。

## 1. 當前狀態快照

| 項目 | 現況 | 重驗指令 |
|---|---|---|
| 程式 HEAD | `36db74f` feat: 60-day window, promo-month scans, same-price dates, suspect-fare note；其後只有排程掃描的 state commit | `git log --oneline -5` |
| 測試 | pytest 121 passed、node 22 pass、四份 JSON 合約檢查通過 | 見第 2 節「跑測試」 |
| 線上 PWA | v1.9.0；app.js 含 `促銷月加跑`；圖示改登機證配色（墨藍底 #1B2430） | `curl -s https://howard118008y-commits.github.io/lowfly/sw.js \| grep -o 'v1\.[0-9.]*'` |
| 排程掃描 | cron `17 1,7,13,19 * * *`（台北 09:17／15:17／21:17／03:17）＋促銷月（5、6、11、12 月）第二條 `17 4,10,16,22 * 5,6,11,12 *`，合計每 3 小時；最近一次 workflow_dispatch 成功 | `gh run list --workflow=scan.yml --limit 3` |
| 線上資料 | 掃描窗口 60 天；TP 26 組（30 天內 19、31～60 天 7）。東京基準已成立 12,116（17 筆）；香港、澳門樣本 6／3，滿 15 筆才成立；好價線 4,500／5,000／9,000；目前最低含行李價 7,296／6,389／9,709，都還沒觸發 | `curl -s https://howard118008y-commits.github.io/lowfly/data/summary.json \| python3 -c "import json,sys;[print(r['id'],r['good_price'],r['baseline']['samples'],(r['cheapest_cached'] or {}).get('price')) for r in json.load(sys.stdin)['routes']]"` |

**今天上線的功能**（細節請看 commit message）：
- 登機證票根 UI，顯示真實航班欄位。
- 不含行李與含行李兩種價格並列。
- 近 30 天含行李均價（`baseline.average_days`）。
- 社群好價線（`routes[].good_price_twd`）：沒有基準也會推播。
- 優惠須知（`notices`）：同時出現在推播、每日摘要、票根和好價清單。
- 新的 Telegram 格式：標題先寫航線和含行李總價。

## 2. 可複用資產與程序

- **跑測試**：venv 建在 session 的 scratchpad，不要建在 iCloud 資料夾。
  ```bash
  python3 -m venv "$SCRATCH/venv" && "$SCRATCH/venv/bin/pip" install -q -r requirements-dev.txt
  PYTHONDONTWRITEBYTECODE=1 "$SCRATCH/venv/bin/python" -m pytest -q -p no:cacheprovider
  node --test tests/frontend.test.cjs
  "$SCRATCH/venv/bin/python" scripts/check_exports.py
  ```
- **改了匯出欄位以後**：要用正式 state 重新匯出 `docs/data`，和程式放在同一個 commit；否則掃描前的合約檢查會失敗。memory: `lowfly-export-field-reexport`
  ```bash
  git pull --rebase && "$SCRATCH/venv/bin/python" -c "import sys;sys.path.insert(0,'.');from datetime import datetime;from zoneinfo import ZoneInfo;from lowfly.config import load_config;from lowfly.export import export_all;from lowfly.state import load_state,read_history;export_all(load_config(),load_state(),datetime.now(ZoneInfo('Asia/Taipei')).replace(microsecond=0),read_history())"
  ```
- **改了前端以後**：`docs/sw.js` 的 `VERSION` 一定要往上加。手機的 PWA 要開關兩次才會換到新版。
- **上線流程**：
  1. `git push`
  2. `gh workflow run scan.yml`
  3. `gh run watch <id> --exit-status`
  4. 等 `gh api repos/howard118008y-commits/lowfly/pages/builds/latest -q .status` 變成 `built`
  5. curl 線上檔案確認
- **測試隔離**：`tests/conftest.py` 的 `cfg` 預設把託運設成 0kg、也不帶好價線。行李相關測試寫在 `tests/test_baggage.py`，好價線和須知寫在 `tests/test_deal_notices.py`，兩者都各自設定。
- **所有數字都在 `config.yaml`**：好價線、須知、行李費表、均價天數，程式裡不寫死。
- **私人報告**：`LowFly 競品分析 2026-11-02.md`、`LowFly 社群訂票心得 2026-11-02.md` 已經列在 `.git/info/exclude`，**不要提交**。
- **查社群的管道**：PTT 可以直接 curl；Facebook 要 Sir 自己在 Chrome 登入。memory: `community-research-channels`

## 3. 未竟任務

**觀察中（不用寫程式）**
- 香港、澳門基準預計 11/5～11/10 前後成立（各需 15 筆，60 天窗口會加快）。成立後半價推播才會開始；好價線已經在運作。
- 促銷月第二條 cron 首次觸發在台北 11/3 00:17，確認 `gh run list --workflow=scan.yml --event schedule` 有出現。
- Travelpayouts 快取很稀疏，詳見 memory: `lowfly-tp-cache-sparse`。

**2026-11-02 已完成**（原「可選」六項）：60 天窗口（實測 31～60 天多 7 組、+37%，摘要圖超過 31 天分兩段）、推播「同價位（≤本票 +5%）還有 N 個出發日」、疑似錯價須知（總價 ≤ 基準 20% 置頂，`notices.suspect_error`）、促銷月每天 8 次、行李費查證、App 圖示換色。

**剩下的小洞**
- 香港航空 HX 行李費仍用 1,500 估算：官網對 headless 瀏覽器跳滑動驗證，最低票種含不含託運未證實（第三方說含 23kg，互相矛盾）。Sir 用手機訂位頁看一次即可定案。
- 樂桃 930、虎航 950 來自比價站（官網 JS 讀不到）；ZIPAIR 1,200 是官網費率表。

## 4. 等 Sir 本人處理

- 輪替 Telegram bot token。memory: `lowfly-token-rotation`
- SerpApi 卡在手機驗證：選用，不處理也能運作。
- 手機上把 PWA 開關兩次，換成 v1.9.0（新圖示要刪掉主畫面捷徑重新加入才會換）。
