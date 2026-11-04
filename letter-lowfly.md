# LowFly 交接信

> 改寫：2026-11-04 14:45（台北），原因：11/4 一天內加了四項功能、資安／可靠度／無障礙強化、AI 團隊，舊快照多處過期，整份重寫。這是現況快照，不是 changelog，歷史請看 `git log`。
> 放在 repo 根目錄而不是 `docs/`：`docs/` 是 GitHub Pages 網站根目錄，放進去會被當成公開網頁。本 repo 是 **PUBLIC**，這份信只寫技術資訊；私密細節用 `memory: <name>` 引用（位置是本機 `~/.claude/projects/...LowFly/memory/`）。
> 開新 session 不用貼交接範本：在 LowFly 資料夾說「接手 LowFly」，技能包 `lowfly-塔台` 會自己查現況。

## 1. 當前狀態快照（2026-11-04 14:45 重驗）

| 項目 | 現況 | 重驗指令 |
|---|---|---|
| 程式 | HEAD `f056bf1`（文件）；最新功能 `fc741b4` AI 團隊面板＋團隊週報；之前 `01ae4e1` 權限拆分／SHA 釘選／CSP、`17e6f09` 失敗告警＋無障礙、`0a5e876` 新低／改一天／預算／促銷 | `git log --oneline -8` |
| 測試 | pytest 158 passed、node 29 pass、四份 JSON 合約檢查通過、pip-audit 無已知漏洞；test.yml 最新 push success；CodeQL 開著的 alert 0 | 見第 2 節「跑測試」；`gh api "repos/howard118008y-commits/lowfly/code-scanning/alerts?state=open" --jq length` |
| 線上 PWA | v1.14.0；index 含 CSP meta 與 `team-cards`；設定頁有「AI 團隊」面板；Lighthouse（v1.12 時）效能 96／無障礙 100／最佳實務 100／SEO 100 | `curl -s https://howard118008y-commits.github.io/lowfly/sw.js \| grep -o 'v1\.[0-9.]*'` |
| 線上資料（14:33） | 有價組合 206；基準 香港 8,030／澳門 6,802／東京 11,305；好價線 4,500／5,000／9,000；最低含行李價 7,038／6,231／8,684；`team`：近 7 天推播 1、促銷 1、樣本 3 天、掃描 23 輪 | `curl -s https://howard118008y-commits.github.io/lowfly/data/summary.json \| python3 -c "import json,sys;d=json.load(sys.stdin);print(d['generated_at'],d['budget']['tp_pairs'],d['team']);[print(r['id'],r['baseline']['value'],r['good_price'],(r['cheapest_cached'] or {}).get('price')) for r in d['routes']]"` |
| 排程 | scan.yml：`17 1,7,13,19 * * *`＋促銷月 `17 4,10,16,22 * 5,6,11,12 *`（11 月每 3 小時）。GitHub 排程約漏一半，11/4 起 Sir 的 Mac 每小時 :50 補觸發：最近一輪過 30 分鐘沒 run 就 `workflow_dispatch`（設定在 repo 外，見塔台記憶）；改 cron 要同步改補觸發器 | `gh run list --workflow=scan.yml --limit 5` |
| 監看 | scan.yml 任一 job 失敗→`alert` job 推 Telegram；watchdog.yml 每 2 小時（`43 */2 * * *`），GitHub 排程沒觸發過，改由 Mac 補觸發器 2 小時 15 分沒 run 就補 | `gh run list --workflow=watchdog.yml --limit 5` |
| 資安設定 | workflow 預設權限 `{}`；scan job 唯讀、不留 token；只有 publish job 可寫且不裝套件；actions 全釘 SHA、只允許 GitHub 官方 action；main 禁止 force push／刪除（ruleset `protect-main`）；Dependabot alerts＋security updates、CodeQL、secret scanning＋push protection、私下回報漏洞都開；外部 PR 一律要核准 | `gh api repos/howard118008y-commits/lowfly/rulesets --jq '.[].name'` |
| GitHub secrets | `TELEGRAM_BOT_TOKEN`（11/4 輪替）、`TELEGRAM_CHAT_ID`、`TRAVELPAYOUTS_TOKEN`；沒有 `SERPAPI_API_KEY`，以 Travelpayouts 快取模式運作 | `gh secret list` |
| Telegram 塔台 | tmux session `lowfly-tower` 已建立，**停在「信任資料夾」確認畫面，等 Sir 按** | `tmux ls` |

**目前功能**（細節看各 commit message）：
- 票根：不含／含行李並列、近 30 天均價、好價線、優惠須知、疑似錯價置頂；60 天窗口、住宿 1～5 晚（東京 1／2／4／5／6）。
- 推播：神票（≤ 基準 50%）、好價（≤ 好價線）、**航線新低**（比近 30 天最低再低 3%，紀錄滿 7 天才啟動，約 11/9）；附「同價位還有 N 個出發日」與「改一天省／多多少」。
- **單程拼接**：去回各取每天最低價拼成來回（`split: true`）。
- **預算模式**（首頁）：輸入含行李預算，列出所有航線 ≤ 預算的日期，預算只存在手機。
- **廉航促銷消息**：Google 新聞 RSS（6 家）、PTT Japan_Travel、香港快運首頁 slug；48 小時內、像促銷、沒推過的合成一則；已推 id 存 `state.sales_seen`，推出則數存 `state.sales_log`。
- **團隊週報**：每週一 09:00 後第一輪推一則（`lowfly/team_report.py`），首份 2026-11-09。
- **行情分頁**、**AI 團隊面板**（設定頁，`summary.team`）。
- **AI 團隊**：塔台（總監）、領航員（票價）、瞭望員（促銷）、地勤（維運）。提示詞、技能包、Telegram 塔台與私人組織圖頁的位置見 memory: `lowfly-ai-team`。

## 2. 可複用資產與程序

- **跑測試**：venv 建在 session 的 scratchpad，不要建在 iCloud 資料夾（scratchpad 換 session 會清空，要重建）。
  ```bash
  python3 -m venv "$SCRATCH/venv" && "$SCRATCH/venv/bin/pip" install -q -r requirements-dev.txt
  PYTHONDONTWRITEBYTECODE=1 "$SCRATCH/venv/bin/python" -m pytest -q -p no:cacheprovider
  node --test tests/frontend.test.cjs
  "$SCRATCH/venv/bin/python" scripts/check_exports.py
  ```
- **改了匯出欄位或窗口／晚數**：用正式 state 重匯 `docs/data`，和程式放在同一個 commit。memory: `lowfly-export-field-reexport`
  ```bash
  git pull --rebase --autostash && "$SCRATCH/venv/bin/python" -c "import sys;sys.path.insert(0,'.');from datetime import datetime;from zoneinfo import ZoneInfo;from lowfly.config import load_config;from lowfly.export import export_all;from lowfly.state import load_state,read_history;export_all(load_config(),load_state(),datetime.now(ZoneInfo('Asia/Taipei')).replace(microsecond=0),read_history())"
  ```
- **改了前端**：`docs/sw.js` 的 `VERSION` 往上加。手機 PWA 要開兩次才換新版；換版前那一次可能是「新 index＋舊快取 app.js」，會出現 CSP 擋 inline 事件的錯誤，第二次開就正常。
- **上線流程**：`git push` → `gh workflow run scan.yml` → `gh run watch <id> --exit-status`（preflight／scan／publish success、alert skipped）→ `until curl -s .../sw.js | grep -q '<新版>'; do sleep 5; done` → curl 驗欄位。連續 push 時 `pages/builds/latest` 顯示 errored 不代表失敗。memory: `lowfly-pages-build-status`
- **iCloud 資料夾的 git**：commit 後馬上 `pull --rebase` 常卡在 pick，或 `index.lock` 寫入逾時。`git status` 乾淨就 `GIT_EDITOR=true git rebase --continue`，`git diff --stat <原 commit> HEAD` 為空再 push；不要 `reset --hard`。memory: `icloud-git-rebase-race`
- **workflow 架構與結束碼**：preflight → scan（唯讀、打包 artifact）→ publish（唯一可寫、只收 data/ 與 docs/data/、push 重試三次）→ alert。main 結束碼 0 正常／1 不寫入（state 讀不到、TP 0 筆）／3 已寫入但 Telegram 失敗。`tests/test_reliability.py` 守著權限邊界與 SHA 釘選。
- **Dependabot**：查各 action 最新 tag 的 SHA，在一個 commit 裡全部升級＋跑測試＋跑一輪掃描，PR 會自動關。
- **測試隔離**：`tests/conftest.py` 的 `cfg` 固定舊前提（託運 0kg、無好價線、30 天、無促銷月、無行情、無拼接、`new_low.days=0`、`airline_sales.enabled=False`、`team_report.enabled=False`）；新功能在各自的測試檔打開。
- **所有數字都在 `config.yaml`**；改促銷月要同步改 scan.yml 第二條 cron 的月份欄（`test_workflow_contract` 會擋）。
- **AI 團隊用法**：「接手 LowFly」→ 技能包 `lowfly-塔台`；`claude --agent lowfly-tower` 整個 session 由塔台主持；派工用 Agent 工具 `lowfly-navigator`／`lowfly-lookout`／`lowfly-ground`。
- **Playwright**：截圖只能存在 repo 的 `.playwright-mcp/`（已 gitignore），不能開 `file://`；用完刪自己產生的檔。memory: `playwright-tmp-in-repo`
- **auto mode 會擋**：大範圍掃描金鑰檔（只能查已知檔案、用 bot id 比對）、替 Sir 按同意／信任類確認。
- **本機金鑰與 bot 設定**：見 memory: `lowfly-token-rotation`（公開 repo 不寫路徑與其他專案名稱）。收新金鑰一律用 mac-dialog。
- **不要提交**：`LowFly 競品分析 2026-11-02.md`、`LowFly 社群訂票心得 2026-11-02.md`（`.git/info/exclude`）；`.claude/`、`.playwright-mcp/`（`.gitignore`）。
- **查社群與官網**：PTT 可 curl（無 AirTicket 板）；Google 新聞 RSS 的 q 要 urlencode；Facebook 要 Sir 在 Chrome 登入。memory: `community-research-channels`

## 3. 未竟任務

**硬期限相關**
1. **GitHub 排程漏跑（11/4 已上 Mac 補觸發器）**：11/5 跑 `gh run list --workflow=scan.yml --limit 10`，確認有 `workflow_dispatch` 補跑、相鄰兩輪間隔不超過 3.5 小時。Mac 關機時只剩 GitHub 排程；要不靠 Mac，備案是 Cloudflare Worker Cron＋只有 `actions:write` 的 PAT（約 1 小時）。
2. **2026-11-09（週一）驗收兩件事**：首份團隊週報有送到 Telegram（09:00 後第一輪）；航線新低滿 7 天紀錄開始生效（設定頁 AI 團隊面板的「樣本」天數 ≥ 7）。

**可選、不急**
3. **Service Worker 換版不一致**：shell 是 cache-first，換版那一次可能新 index 配舊 app.js。可改成 index 與 app.js 同一個版本號載入，或 navigation 一律 network-first。約 1 小時。
4. 稽核剩下的 Low 項：字級改 rem、sw.js `VERSION` 自動化、commit 簽章。
5. 挑票方式（11/4 調查剩下的）：首頁三條航線並排（約 2h）、星期幾出發均價（約 2h）、價格走勢折線（約 4h）。
6. 香港航空 HX 行李費仍用 1,500 估算；樂桃 930、虎航 950 來自比價站。交給瞭望員查證。
7. 已知限制：航線新低用 TP 樣本當前低（啟用 SerpApi 後 Google 價與 TP 前低有價差）；單程拼接兩段報價時間不同、回程航空須知不列。

**日常常態**
- 塔台每週一做團隊檢查（技能包 `lowfly-塔台` 流程二），並看團隊週報。
- 促銷消息約 3 成誤報（旅展懶人包、轉載）：瞭望員依實際推播調 `keywords`／`exclude`。
- 行情「過去」2027-02 才滿 3 個月、2027-05 滿 6 個月。

## 4. 等 Sir 本人處理

- **啟用 Telegram 塔台**：終端機執行 `tmux attach -t lowfly-tower`，選「Yes, I trust this folder」，再按 Ctrl-b d 離開；之後在 Telegram 對 LowFly bot 說話就由塔台回覆。開機自動啟動（選用）的指令見 memory: `lowfly-ai-team`。
- **手機 PWA 開關兩次**，換成 v1.14.0。
- **GitHub 帳號設定**：Settings → Emails 勾「Block command line pushes that expose my email」。之後的 commit 已用 noreply 信箱；28 個舊 commit 作者欄仍是 Gmail（改寫歷史要 force push，未做）。
- **要不要換自訂網域**：LowFly 與同帳號其他 github.io 網站共用網域（localStorage 共用）；已加防護，換網域才是根治。
- `docs/data/alerts.json` 公開了推播過的出發日期（好價日期，不是訂票紀錄）；介意可改成不匯出日期。
- **SerpApi 手機驗證**（選用）：完成後 Claude 用 mac-dialog 收 key → `gh secret set SERPAPI_API_KEY` → 跑一輪掃描驗證。
