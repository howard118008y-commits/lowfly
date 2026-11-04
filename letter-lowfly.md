# LowFly 交接信

> 改寫：2026-11-04 09:00（台北），原因：11/2～11/4 新增 60 天窗口、1～2 晚、促銷月加跑、行情分頁、單程拼接，舊版快照已過期。這是現況快照，不是 changelog，歷史請看 `git log`。
> 放在 repo 根目錄而不是 `docs/`：`docs/` 是 GitHub Pages 網站根目錄，放進去會被當成公開網頁。本 repo 是 **PUBLIC**，這份信只寫技術資訊；私密細節用 `memory: <name>` 引用（位置是本機 `~/.claude/projects/...LowFly/memory/`）。

## 1. 當前狀態快照

| 項目 | 現況 | 重驗指令 |
|---|---|---|
| 程式 | 最新功能 commit `2f2ab3c` feat: splice two one-way fares into round trips；之後只有排程 state commit 與文件 | `git log --oneline -8` |
| 測試 | pytest 130 passed、node 24 pass、四份 JSON 合約檢查通過 | 見第 2 節「跑測試」 |
| 線上 PWA | v1.11.0；index 200；app.js 含 `兩張單程`、`renderMarket` | `curl -s https://howard118008y-commits.github.io/lowfly/sw.js \| grep -o 'v1\.[0-9.]*'` |
| 排程掃描 | `17 1,7,13,19 * * *`（台北 09:17／15:17／21:17／03:17）＋促銷月（5、6、11、12 月）`17 4,10,16,22 * 5,6,11,12 *`，11 月起每 3 小時一次 | `gh run list --workflow=scan.yml --limit 3` |
| GitHub secrets | `TELEGRAM_BOT_TOKEN`（11/4 輪替）、`TELEGRAM_CHAT_ID`、`TRAVELPAYOUTS_TOKEN`；沒有 `SERPAPI_API_KEY`，所以以 Travelpayouts 快取模式運作 | `gh secret list` |
| 線上資料（11/4 08:45） | 窗口 60 天；住宿 香港／澳門 1～5 晚、東京 1／2／4／5／6 晚；TP 有價組合 191（其中 159 為單程拼接）。三條航線基準都已成立：香港 8,035／澳門 6,782／東京 11,318；好價線 4,500／5,000／9,000；最低含行李價 7,038／5,916／8,684；已推播 1 則（東京 8,684，星宇去＋虎航回） | `curl -s https://howard118008y-commits.github.io/lowfly/data/summary.json \| python3 -c "import json,sys;d=json.load(sys.stdin);print(d['generated_at'],d['budget']['tp_pairs']);[print(r['id'],r['baseline']['value'],r['good_price'],(r['cheapest_cached'] or {}).get('price')) for r in d['routes']]"` |

**目前功能**（細節看各 commit message）：
- 登機證票根、不含／含行李並列、近 30 天均價、社群好價線、優惠須知（航空公司規則、深夜抵達）。
- 60 天掃描窗口，住宿 1～5 晚（含 2天1夜、3天2夜）；每日摘要圖超過 31 天時分成兩段。
- 推播附「同價位（≤本票 +5%）還有 N 個出發日」；總價 ≤ 基準 20% 時置頂「疑似錯價」須知。
- 促銷月每天掃 8 次；SerpApi 每輪上限跟著改用 `runs_per_day()`。
- **單程拼接**（`sources.travelpayouts.one_way`）：去程、回程各取每天最低價拼成來回，比來回快取便宜或來回沒資料時採用，標 `split: true`；行李費依各段航空公司計算。
- **行情分頁**（第五個 tab）：過去 3／6 個月＝`state.market_daily` 每日含行李均價（自 11/2 起累積，保留 190 天）；未來 3／6 個月＝每天一次抓未來 6 個出發月份的 TP 快取（`state.market`）；外部參考只有 Kayak 過去 12 個月最便宜／最貴月份（`config.yaml market.reference`）。

## 2. 可複用資產與程序

- **跑測試**：venv 建在 session 的 scratchpad，不要建在 iCloud 資料夾。
  ```bash
  python3 -m venv "$SCRATCH/venv" && "$SCRATCH/venv/bin/pip" install -q -r requirements-dev.txt
  PYTHONDONTWRITEBYTECODE=1 "$SCRATCH/venv/bin/python" -m pytest -q -p no:cacheprovider
  node --test tests/frontend.test.cjs
  "$SCRATCH/venv/bin/python" scripts/check_exports.py
  ```
- **改了匯出欄位或 config 的窗口／晚數以後**：要用正式 state 重新匯出 `docs/data`，和程式放在同一個 commit；否則掃描前的合約檢查會失敗。memory: `lowfly-export-field-reexport`
  ```bash
  git pull --rebase --autostash && "$SCRATCH/venv/bin/python" -c "import sys;sys.path.insert(0,'.');from datetime import datetime;from zoneinfo import ZoneInfo;from lowfly.config import load_config;from lowfly.export import export_all;from lowfly.state import load_state,read_history;export_all(load_config(),load_state(),datetime.now(ZoneInfo('Asia/Taipei')).replace(microsecond=0),read_history())"
  ```
- **改了前端以後**：`docs/sw.js` 的 `VERSION` 一定要往上加。手機的 PWA 要開關兩次才會換到新版；主畫面圖示要刪掉捷徑重新加入才會換。
- **上線流程**：
  1. `git push`
  2. `gh workflow run scan.yml`
  3. `gh run watch <id> --exit-status`
  4. 看 `gh run list --workflow pages-build-deployment --limit 3` 最新一筆是 success。`pages/builds/latest` 在連續 push 時會把被取消的舊 build 標成 errored，不代表失敗。memory: `lowfly-pages-build-status`
  5. curl 線上檔案確認
- **測試隔離**：`tests/conftest.py` 的 `cfg` 把既有測試固定在舊前提：託運 0kg、沒有好價線、30 天窗口、沒有促銷月、`market.months_ahead=0`、`one_way=False`。新功能各自在 `test_baggage.py`、`test_deal_notices.py`、`test_scan_window.py`、`test_market.py`、`test_one_way.py` 打開。
- **所有數字都在 `config.yaml`**：好價線、須知、行李費表、均價天數、窗口、晚數、促銷月、行情月數，程式裡不寫死。改促銷月要同步改 `scan.yml` 第二條 cron 的月份欄（`test_workflow_contract` 會擋）。
- **本機金鑰**（`~/.cx468/`，權限 600）：`lowfly_tp.key`（Travelpayouts，可本機直接實測 API）、`lowfly_telegram.key`（11/4 新 bot token）。收新金鑰一律用 mac-dialog 彈窗，不貼在對話裡。
- **單程實測方法**：`prices_for_dates` 帶 `one_way=true`，回程把 origin／destination 對調。11/4 實測數字見 memory: `lowfly-tp-cache-sparse`。
- **不要提交**：`LowFly 競品分析 2026-11-02.md`、`LowFly 社群訂票心得 2026-11-02.md`、`.playwright-mcp/` 都已列在 `.git/info/exclude`。memory: `playwright-tmp-in-repo`
- **查社群與官網**：PTT 可以直接 curl；Facebook 要 Sir 在 Chrome 登入；航空公司官網多數要 Playwright，香港航空對 headless 跳滑動驗證。memory: `community-research-channels`

## 3. 未竟任務

**可選、不急（建議順序）**
1. **盯廉航官方促銷**（原四步計畫的第 4 步，還沒開始）：虎航、香港快運、酷航、樂桃的限時促銷先在官網開賣，快取抓不到。先查各家促銷頁或新聞有沒有穩定可抓的來源，再決定做法。
2. **其他平台挑票方式**（11/4 調查，依效益排序）：路線新低提醒（任何日期創 30 天新低就推播，約 2h）、預算模式（約 1.5h）、推播加「改一天省多少」（約 2h）、首頁三條航線並排（約 2h）、星期幾出發均價（約 2h）。之後再考慮：價格走勢折線（約 4h）、紅眼／早班標籤（要先確認快取有沒有起飛時間）。
3. **單程拼接的已知限制**：兩段的報價時間不同，可能一段已經漲價；拼接取 `a.airline_code`（去程）當須知與圖示，回程航空的須知不會列出。
4. 香港航空 HX 行李費仍用 1,500 估算（最低票種含不含託運未證實）；樂桃 930、虎航 950 來自比價站，ZIPAIR 1,200 來自官網。

**觀察中（不用寫程式）**
- 行情分頁的「過去」目前只有 3 天紀錄，2027-02 才滿 3 個月、2027-05 才滿 6 個月。
- 拼接讓基準樣本多了約 5 倍，基準價跟著變動：上線前後香港 7,791 → 8,035、澳門 6,803 → 6,782、東京 11,985 → 11,318。觀察幾天，看半價線是否變得太難或太容易觸發；好價線不受影響。

## 4. 等 Sir 本人處理

- **SerpApi 手機驗證**：屬於帳號真人驗證，Claude 不能代做。完成後由 Claude 用 mac-dialog 收 key → `gh secret set SERPAPI_API_KEY` → 跑一輪掃描驗證。選用，不處理也能運作。
- **另外兩個外流的 bot**（hc_pm_radar、heycheng_office）待輪替：Sir 點頭後 Claude 可以經 Chrome 的 Telegram Web 代換，但要更新那兩個專案各自的設定。memory: `lowfly-token-rotation`
- 手機上把 PWA 開關兩次，換成 v1.11.0。
