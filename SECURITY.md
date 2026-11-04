# 資安政策

## 回報漏洞

請**不要**開公開 issue。到本 repo 的 [Security → Report a vulnerability](https://github.com/howard118008y-commits/lowfly/security/advisories/new) 私下回報，附上重現步驟與影響範圍。收到後 7 天內回覆。

## 範圍

- 網站：<https://howard118008y-commits.github.io/lowfly/>（`docs/`，純靜態 PWA，無登入、無後端）。
- 排程掃描：`.github/workflows/`、`lowfly/`。

## 設計上的保護

- 金鑰（Telegram、Travelpayouts、SerpApi）只存在 GitHub Actions Secrets，不進 repo；secret scanning 與 push protection 已開。
- 掃描 job 只有讀取權；寫回 main 的 publish job 不安裝任何套件。所有 actions 釘在 commit SHA，Dependabot 每週更新。
- main 禁止 force push 與刪除；外部 PR 的 workflow 一律要核准。
- 網頁有 Content-Security-Policy（只允許本站 script），外部連結只接受 https。
- `data/`、`docs/data/` 是公開的票價資料，不含個人資料。
