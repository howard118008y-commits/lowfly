# LowFly 交接信

> 改寫：2026-11-04 10:30（台北），原因：資安、可靠度、無障礙三項稽核後全面強化（v1.13.1）。這是現況快照，不是 changelog，歷史請看 `git log`。
> 放在 repo 根目錄而不是 `docs/`：`docs/` 是 GitHub Pages 網站根目錄，放進去會被當成公開網頁。本 repo 是 **PUBLIC**，這份信只寫技術資訊；私密細節用 `memory: <name>` 引用（位置是本機 `~/.claude/projects/...LowFly/memory/`）。

## 1. 當前狀態快照

| 項目 | 現況 | 重驗指令 |
|---|---|---|
| 程式 | 最新：`01ae4e1` security（權限拆分、SHA 釘選、CSP）、`17e6f09` 失敗告警＋無障礙、`0a5e876` 四項新功能 | `git log --oneline -8` |
| 測試 | pytest 158 passed、node 30 pass、四份 JSON 合約檢查通過；pip-audit 無已知漏洞 | 見第 2 節「跑測試」 |
| 線上 PWA | v1.14.0（設定頁有 AI 團隊面板）；index 含 CSP meta、`skip-link`、`spend-input`；Lighthouse（v1.12 時）效能 96／無障礙 100／最佳實務 100／SEO 100 | `curl -s https://howard118008y-commits.github.io/lowfly/sw.js \| grep -o 'v1\.[0-9.]*'` |
| 排程掃描 | `17 1,7,13,19 * * *`（台北 09:17／15:17／21:17／03:17）＋促銷月（5、6、11、12 月）`17 4,10,16,22 * 5,6,11,12 *`，11 月起每 3 小時一次 | `gh run list --workflow=scan.yml --limit 3` |
| 監看 | `scan.yml` 任一 job 失敗→`alert` job 推 Telegram；`watchdog.yml` 每 2 小時看線上 summary.json，超過 7 小時沒更新自動補跑，滿 18 小時每天告警一次 | `gh run list --workflow=watchdog.yml --limit 3` |
| 資安設定 | 掃描 job 唯讀、只有 `publish` job 可寫且不裝套件；actions 全釘 SHA、只允許 GitHub 官方 action；main 禁止 force push／刪除；Dependabot、CodeQL、secret scanning＋push protection、私下回報漏洞都已開 | `gh api repos/howard118008y-commits/lowfly/rulesets` |
| GitHub secrets | `TELEGRAM_BOT_TOKEN`（11/4 輪替）、`TELEGRAM_CHAT_ID`、`TRAVELPAYOUTS_TOKEN`；沒有 `SERPAPI_API_KEY`，所以以 Travelpayouts 快取模式運作 | `gh secret list` |
| 線上資料（11/4 08:45） | 窗口 60 天；住宿 香港／澳門 1～5 晚、東京 1／2／4／5／6 晚；TP 有價組合 191（其中 159 為單程拼接）。三條航線基準都已成立：香港 8,035／澳門 6,782／東京 11,318；好價線 4,500／5,000／9,000；最低含行李價 7,038／5,916／8,684；已推播 1 則（東京 8,684，星宇去＋虎航回） | `curl -s https://howard118008y-commits.github.io/lowfly/data/summary.json \| python3 -c "import json,sys;d=json.load(sys.stdin);print(d['generated_at'],d['budget']['tp_pairs']);[print(r['id'],r['baseline']['value'],r['good_price'],(r['cheapest_cached'] or {}).get('price')) for r in d['routes']]"` |

**目前功能**（細節看各 commit message）：
- 登機證票根、不含／含行李並列、近 30 天均價、社群好價線、優惠須知（航空公司規則、深夜抵達）。
- 60 天掃描窗口，住宿 1～5 晚（含 2天1夜、3天2夜）；每日摘要圖超過 31 天時分成兩段。
- 推播附「同價位（≤本票 +5%）還有 N 個出發日」；總價 ≤ 基準 20% 時置頂「疑似錯價」須知。
- 促銷月每天掃 8 次；SerpApi 每輪上限跟著改用 `runs_per_day()`。
- **單程拼接**（`sources.travelpayouts.one_way`）：去程、回程各取每天最低價拼成來回，比來回快取便宜或來回沒資料時採用，標 `split: true`；行李費依各段航空公司計算。
- **航線新低**（`config.yaml new_low`）：本輪價格比近 30 天（不含今天）該航線最低價再低 3%（`dedupe.min_drop_ratio`）就推「新低」，不論基準與好價線；推過的記在 `state.new_low_sent`。紀錄滿 7 天（`min_days`）才開始推，tp_samples 自 11/2 起算，約 11/9 生效。
- **改一天**：每則推播列出去／回前後挪一天裡最便宜的組合，比本票省或多多少（`_shift_one_day`，只看本次窗口內有價的組合）。
- **預算模式**（首頁）：輸入含行李預算，列出所有航線、日期 ≤ 預算的組合，由便宜到貴；預算只存在手機 localStorage（`lowfly-spend-v1`）。
- **廉航促銷消息**（`config.yaml airline_sales`，`lowfly/sources/airline_sales.py`）：每輪抓 Google 新聞 RSS（6 家）、PTT Japan_Travel 搜「虎航」、香港快運首頁促銷頁 slug；標題要有促銷字眼、不含排除字、提到該航空，48 小時內、沒推過的合成一則推播，每家最多 3 條，超過 4096 字自動少列。已推 id 存 `state.sales_seen` 30 天。11/4 首推：虎航 ITF 999 元起等 13 條。
- **AI 團隊**：總監「塔台」＋領航員（票價）、瞭望員（促銷）、地勤（維運）。設定頁有「AI 團隊」面板（`summary.team`）；每週一 09:00 後推「團隊週報」（`lowfly/team_report.py`，`config.yaml team_report`）。提示詞、技能包與 Telegram 塔台的位置見 memory: `lowfly-ai-team`（不進公開 repo）。開新 session 說「接手 LowFly」即可，不用再貼交接範本。
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
- **iCloud 資料夾的 git**：`git commit` 後馬上 `git pull --rebase` 常因 iCloud 同步誤判「本機有變更」而中斷（rebase 卡在 pick）。先 `git status` 確認乾淨，再 `GIT_EDITOR=true git rebase --continue`，比對 `git diff --stat <原 commit> HEAD` 為空再 push。不要 `reset --hard`。
- **main 結束碼**：0 正常；1 不寫入（state 讀不到、Travelpayouts 0 筆）；3 已寫入但 Telegram 送失敗（publish 存檔後標紅）。
- **改了前端以後**：`docs/sw.js` 的 `VERSION` 一定要往上加。手機的 PWA 要開關兩次才會換到新版；主畫面圖示要刪掉捷徑重新加入才會換。
- **上線流程**：
  1. `git push`
  2. `gh workflow run scan.yml`
  3. `gh run watch <id> --exit-status`
  4. 看 `gh run list --workflow pages-build-deployment --limit 3` 最新一筆是 success。`pages/builds/latest` 在連續 push 時會把被取消的舊 build 標成 errored，不代表失敗。memory: `lowfly-pages-build-status`
  5. curl 線上檔案確認
- **測試隔離**：`tests/conftest.py` 的 `cfg` 把既有測試固定在舊前提：託運 0kg、沒有好價線、30 天窗口、沒有促銷月、`market.months_ahead=0`、`one_way=False`、`new_low.days=0`、`airline_sales.enabled=False`（要連網）。新功能各自在 `test_baggage.py`、`test_deal_notices.py`、`test_scan_window.py`、`test_market.py`、`test_one_way.py`、`test_new_low.py`、`test_shift_day.py`、`test_airline_sales.py` 打開。
- **所有數字都在 `config.yaml`**：好價線、須知、行李費表、均價天數、窗口、晚數、促銷月、行情月數，程式裡不寫死。改促銷月要同步改 `scan.yml` 第二條 cron 的月份欄（`test_workflow_contract` 會擋）。
- **本機金鑰**：位置與檔名見 memory: `lowfly-token-rotation`（公開 repo 不寫路徑）。收新金鑰一律用 mac-dialog 彈窗，不貼在對話裡。
- **單程實測方法**：`prices_for_dates` 帶 `one_way=true`，回程把 origin／destination 對調。11/4 實測數字見 memory: `lowfly-tp-cache-sparse`。
- **不要提交**：`LowFly 競品分析 2026-11-02.md`、`LowFly 社群訂票心得 2026-11-02.md`、`.playwright-mcp/` 都已列在 `.git/info/exclude`。memory: `playwright-tmp-in-repo`
- **查社群與官網**：PTT 可以直接 curl；Facebook 要 Sir 在 Chrome 登入；航空公司官網多數要 Playwright，香港航空對 headless 跳滑動驗證。memory: `community-research-channels`

## 3. 未竟任務

**可選、不急（建議順序）**
1. **稽核剩下的 Low 項**（不急）：字級改 rem（目前 px，系統字級放大不跟著變）、sw.js `VERSION` 自動化、commit 簽章、每週健康摘要推播。
2. **其他平台挑票方式**（11/4 調查，剩下的）：首頁三條航線並排（約 2h）、星期幾出發均價（約 2h）。之後再考慮：價格走勢折線（約 4h）、紅眼／早班標籤（要先確認快取有沒有起飛時間）。
3. **廉航促銷的限制**：酷航、樂桃、捷星、ZIPAIR 官網擋爬蟲或要 JS，只能靠新聞，會晚數小時，快閃促銷可能漏；預期約 3 成誤報（旅展懶人包、轉載），改 `keywords`／`exclude` 調整。PTT 沒有 AirTicket 板。
4. **航線新低用 TP 快取樣本當前低**：之後若啟用 SerpApi，Google 驗證價會拿來和 TP 前低比，兩者有價差，可能誤報或漏報。
5. **單程拼接的已知限制**：兩段的報價時間不同，可能一段已經漲價；拼接取 `a.airline_code`（去程）當須知與圖示，回程航空的須知不會列出。
6. 香港航空 HX 行李費仍用 1,500 估算（最低票種含不含託運未證實）；樂桃 930、虎航 950 來自比價站，ZIPAIR 1,200 來自官網。

**觀察中（不用寫程式）**
- 行情分頁的「過去」目前只有 3 天紀錄，2027-02 才滿 3 個月、2027-05 才滿 6 個月。
- 拼接讓基準樣本多了約 5 倍，基準價跟著變動：上線前後香港 7,791 → 8,035、澳門 6,803 → 6,782、東京 11,985 → 11,318。觀察幾天，看半價線是否變得太難或太容易觸發；好價線不受影響。

## 4. 等 Sir 本人處理

- **啟用 Telegram 塔台**：終端機執行 `tmux attach -t lowfly-tower`，選「Yes, I trust this folder」，再按 Ctrl-b d 離開。之後在 Telegram 對 LowFly bot 說話就會由塔台回覆（auto mode 不准 Claude 代按這個確認）。

- **GitHub 帳號設定**：Settings → Emails 勾「Block command line pushes that expose my email」。本 repo 之後的 commit 已改用 noreply 信箱，但 28 個舊 commit 的作者欄仍是 Gmail（改寫歷史要 force push，未做）。
- **要不要換自訂網域**：LowFly 與同帳號其他 github.io 網站共用網域（localStorage 共用）。已加防護（離線快取含 HTML 字元就不採用），換網域才是根治，需購買網域。
- `docs/data/alerts.json` 公開了推播過的出發日期（是好價日期，不是訂票紀錄）。介意的話可改成不匯出日期。

- **SerpApi 手機驗證**：屬於帳號真人驗證，Claude 不能代做。完成後由 Claude 用 mac-dialog 收 key → `gh secret set SERPAPI_API_KEY` → 跑一輪掃描驗證。選用，不處理也能運作。
- **bot token 輪替**：11/2 外流的三個 token 已於 11/4 全部輪替，舊 token 皆失效。各 bot 的設定位置見 memory: `lowfly-token-rotation`（公開 repo 不寫名稱）。
- 手機上把 PWA 開關兩次，換成 v1.12.0。
