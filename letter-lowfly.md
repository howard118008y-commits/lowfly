# LowFly 交接信

> 改寫：2026-11-02 22:40（台北）。這是現況快照，不是 changelog，歷史請看 `git log`。
> 放在 repo 根目錄而不是 `docs/`：`docs/` 是 GitHub Pages 網站根目錄，放進去會被當成公開網頁。本 repo 是 **PUBLIC**，這份信只寫技術資訊；私密細節用 `memory: <name>` 引用（位置是本機 `~/.claude/projects/...LowFly/memory/`）。

## 1. 當前狀態快照

| 項目 | 現況 | 重驗指令 |
|---|---|---|
| 程式 HEAD | `dfde239` feat: community good-price lines, deal notices…；其後只有排程掃描的 state commit | `git log --oneline -5` |
| 測試 | pytest 115 passed、node 22 pass、四份 JSON 合約檢查通過 | 見第 2 節「跑測試」 |
| 線上 PWA | v1.8.0；index 200；app.js 含 `dealKind`／`t-notes`／`天含行李均價` | `curl -s https://howard118008y-commits.github.io/lowfly/sw.js \| grep -o 'v1\.[0-9.]*'` |
| 排程掃描 | cron `17 1,7,13,19 * * *`（台北 09:17／15:17／21:17／03:17）；最近一次 workflow_dispatch 成功 | `gh run list --workflow=scan.yml --limit 3` |
| 線上資料 | 三條航線（順序：香港 → 澳門 → 東京）都還沒有基準：樣本 6／2／11，滿 15 筆才成立；好價線 4,500／5,000／9,000；目前最低含行李價 7,296／6,389／9,709，都還沒觸發 | `curl -s https://howard118008y-commits.github.io/lowfly/data/summary.json \| python3 -c "import json,sys;[print(r['id'],r['good_price'],r['baseline']['samples'],(r['cheapest_cached'] or {}).get('price')) for r in json.load(sys.stdin)['routes']]"` |

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
- 基準大約會在東京 11/4、香港 11/5、澳門 11/10 前後成立（各需 15 筆）。成立後半價推播才會開始；好價線已經在運作。
- Travelpayouts 快取很稀疏，詳見 memory: `lowfly-tp-cache-sparse`。

**可選、不急**：來源是 `LowFly 社群訂票心得 2026-11-02.md` 第四節的 #4～#7。
1. 掃描窗口從 30 天延長到 60 天，約 3 小時，要先實測快取命中率。
2. 推播加「同價位還有 N 個出發日」，約 3 小時。
3. 疑似錯價警示（低於基準 20%），約 1 小時。
4. 促銷月份（5～6 月、11～12 月）提高掃描頻率，約 1 小時。
5. 樂桃 MM、台灣虎航 IT、ZIPAIR ZG、香港航空 HX 的行李費目前用 1,500 估算，有空再查證。
6. App 圖示還是舊配色。

## 4. 等 Sir 本人處理

- 輪替 Telegram bot token。memory: `lowfly-token-rotation`
- SerpApi 卡在手機驗證：選用，不處理也能運作。
- 手機上把 PWA 開關兩次，換成 v1.8.0。
