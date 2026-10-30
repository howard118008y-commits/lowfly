(function () {
  "use strict";
  const {fmtDate, fmtMoney, fmtPct, ratioClass, escapeHTML: e, safeURL, relativeTime, coherent} = window.LowFly;
  const $ = id => document.getElementById(id);
  const storageKey = "lowfly-bundle-v1";
  const dataNames = ["summary", "pairs", "history", "alerts"];
  let bundle = null, cached = false, busy = false;
  let previousFocus = null;

  function externalLink(url, label = "Google Flights ↗") {
    const safe = safeURL(url);
    return safe ? `<a class="flight-link" href="${e(safe)}" target="_blank" rel="noopener noreferrer">${e(label)}</a>` : "<span class=\"muted small\">連結暫無</span>";
  }
  function localTime(value) {
    return value ? new Date(value).toLocaleString("zh-TW", {timeZone: bundle?.summary.timezone || "Asia/Taipei", hour12: false}) : "尚未查詢";
  }
  function status() {
    if (!bundle) return;
    const at = bundle.summary.generated_at;
    const stale = Date.now() - Date.parse(at) > 8 * 3600000;
    $("updated").textContent = `更新 ${relativeTime(at)} · ${localTime(at)}${stale ? " · 資料可能過期" : ""}`;
    $("updated").classList.toggle("stale", stale);
    const offline = !navigator.onLine || cached;
    $("connection").className = "connection" + (offline ? " offline" : "");
    $("connection").textContent = bundle.summary.demo ? "模擬資料 · 僅供預覽，非真實機票報價" :
      offline ? `離線／快取資料 · 上次更新 ${localTime(at)}` :
      bundle.summary.stats.runs ? "自動掃描中 · 桃園 ⇄ 澳門" : "尚未開始掃描 · 等待 Actions 首次匯出資料";
  }

  function renderHome() {
    const s = bundle.summary, b = s.baseline;
    $("route-label").textContent = `${s.route.label} · ${s.route.origin} ⇄ ${s.route.destination} · 直飛來回 · ${s.route.adults} 位成人`;
    $("baseline-card").classList.remove("skeleton");
    $("baseline-card").innerHTML = `<div class="hero-top"><span>GOOGLE 典型價格基準</span><span class="hero-tag">${b.n_ranges} 筆觀測</span></div>
      <div class="baseline-price">${b.value == null ? "<span class=\"waiting\">尚未取得基準</span>" : e(fmtMoney(b.value))}</div>
      <p>${b.google_low == null ? "首次精查後，自動建立價格參考。" : `典型區間 ${e(fmtMoney(b.google_low))}～${e(Math.round(b.google_high).toLocaleString("en-US"))}`}</p>
      <div class="hero-bottom"><span>近 ${b.lookback_days} 天的區間中位數</span><span aria-hidden="true">↘</span></div>`;
    $("deal-count").textContent = `${s.deals.length} 組 ≤${Math.round(s.thresholds.digest * 100)}%`;
    $("deal-explainer").textContent = `≤${s.thresholds.instant * 100}% 立即通知 · ≤${s.thresholds.digest * 100}% 每日摘要`;
    $("deals").innerHTML = s.deals.length ? s.deals.map(item => `<article class="deal-card">
      <div class="deal-top"><span class="tag ${item.verified ? "verified" : "pending"}">${item.verified ? "✓ 已驗證" : "⌛ 待驗證 · Aviasales 快取"}</span><span class="nights">${item.nights} 晚</span></div>
      <h3>${e(fmtDate(item.outbound))} → ${e(fmtDate(item.inbound))}</h3>
      <div class="price-row"><strong>${e(fmtMoney(item.price))}</strong><span class="discount">${e(fmtPct(item.ratio))}</span></div>
      <div class="deal-bottom"><span class="muted">${e(item.airline || "航空公司未提供")}</span>${externalLink(item.google_flights_url)}</div>
      <p class="observation">觀測 ${e(localTime(item.at))}</p></article>`).join("") :
      `<div class="empty"><span class="empty-symbol" aria-hidden="true">↘</span><h3>${b.value == null ? "雷達準備中" : "好價格，值得等一等。"}</h3><p>${b.value == null ? "尚未取得 Google 典型區間，暫不判斷折扣。" : `目前沒有低於基準 ${s.thresholds.digest * 100}% 的票。`}</p></div>`;
    const cheapest = s.cheapest_verified;
    $("cheapest").innerHTML = cheapest ? `<div class="cheapest"><span class="eyebrow">目前已驗證最低</span><strong>${e(fmtMoney(cheapest.price))}</strong><p>${e(fmtDate(cheapest.outbound))} → ${e(fmtDate(cheapest.inbound))} · ${e(cheapest.airline)}</p>${externalLink(cheapest.google_flights_url)}</div>` : "";
    const q = s.budget;
    $("budget").innerHTML = `<div><span>SerpAPI 本月</span><strong>${q.serpapi_used_month}<small> / ${q.serpapi_quota}</small></strong><progress max="${q.serpapi_quota}" value="${q.serpapi_used_month}" aria-label="本月 SerpAPI 用量"></progress></div>
      <div class="budget-bottom"><span>今日 <b>${q.serpapi_used_day} / ${q.serpapi_daily_budget}</b></span><span>Travelpayouts <b>${q.tp_pairs} 組</b></span></div>`;
  }

  function renderCalendar() {
    const pairs = bundle.pairs.pairs;
    const dates = [...new Set(pairs.map(p => p.outbound))];
    const nights = bundle.summary.window.stay_nights;
    const only = $("deals-only").checked;
    $("heatmap").innerHTML = `<table class="heatmap"><caption class="sr-only">出發日期與住宿晚數的來回價格</caption><thead><tr><th scope="col">晚數</th>${dates.map(date => `<th scope="col" class="${[0, 6].includes(new Date(date + "T12:00:00+08:00").getUTCDay()) ? "weekend" : ""}">${e(fmtDate(date))}</th>`).join("")}</tr></thead>
      <tbody>${nights.map(n => `<tr><th scope="row">${n}晚</th>${dates.map(date => {
        const p = pairs.find(p => p.outbound === date && p.nights === n);
        if (!p) return "<td>—</td>";
        const filtered = only && (p.ratio == null || p.ratio > bundle.summary.thresholds.digest);
        const label = `${fmtDate(date)}，${n} 晚，${fmtMoney(p.price)}，${p.verified ? "已驗證" : "待驗證"}`;
        return `<td><button data-pair="${e(p.pair_key)}" class="heat-cell ${ratioClass(p.ratio, p.price)} ${filtered ? "filtered" : ""}" aria-label="${e(label)}">${p.price == null ? "—" : e((p.price / 1000).toFixed(1) + "k")}<small>${p.verified ? "✓" : p.price == null ? "無資料" : "快取"}</small></button></td>`;
      }).join("")}</tr>`).join("")}</tbody></table>`;
    $("heatmap").querySelectorAll("[data-pair]").forEach(button => button.addEventListener("click", () => showPair(button.dataset.pair)));
  }

  function chart(series) {
    if (!series.length) return '<div class="empty chart-empty">這組日期尚無歷史觀測。</div>';
    // 一次搜尋可有多家航空；曲線採同時段最低價，Google 優先。
    const grouped = new Map();
    for (const point of series.filter(point => Number.isFinite(point[1]))) {
      const old = grouped.get(point[0]);
      if (!old || (point[2] === old[2] && point[1] < old[1]) ||
          (point[2] === "serpapi" && old[2] !== "serpapi")) grouped.set(point[0], point);
    }
    const points = [...grouped.values()].sort((a, b) => Date.parse(a[0]) - Date.parse(b[0]));
    if (!points.length) return '<p class="muted">尚無有效觀測。</p>';
    const values = points.map(point => point[1]);
    const low = Math.min(...values), high = Math.max(...values);
    const times = points.map(point => Date.parse(point[0]));
    const t0 = Math.min(...times), t1 = Math.max(...times);
    const coords = points.map((p, i) => `${42 + (t1 === t0 ? .5 : (times[i] - t0) / (t1 - t0)) * 302},${164 - (high === low ? .5 : (p[1] - low) / (high - low)) * 112}`);
    const dots = coords.map((coordinate, i) => `<circle cx="${coordinate.split(",")[0]}" cy="${coordinate.split(",")[1]}" r="3" class="${points[i][2] === "serpapi" ? "verified-dot" : "cache-dot"}"><title>${e(localTime(points[i][0]))} ${e(fmtMoney(points[i][1]))} ${points[i][2] === "serpapi" ? "Google" : "快取"}</title></circle>`).join("");
    return `<svg class="history-chart" viewBox="0 0 370 218" role="img" aria-label="歷史價格，最低 ${e(fmtMoney(low))}，最高 ${e(fmtMoney(high))}"><line x1="40" y1="178" x2="350" y2="178"/><polyline points="${coords.join(" ")}"/>${dots}<text x="4" y="36">${e(Math.round(high).toLocaleString("en-US"))}</text><text x="4" y="174">${e(Math.round(low).toLocaleString("en-US"))}</text><text x="42" y="205">${e(fmtDate(points[0][0]))}</text><text x="260" y="205">${e(fmtDate(points[points.length - 1][0]))}</text></svg>`;
  }

  function showPair(key) {
    const p = bundle.pairs.pairs.find(pair => pair.pair_key === key);
    if (!p) return;
    previousFocus = document.activeElement;
    const series = bundle.history.series[key] || [];
    $("pair-detail").innerHTML = `<p class="eyebrow">${p.nights} 晚 · 單組日期詳情</p><h2 id="pair-title">${e(fmtDate(p.outbound))} → ${e(fmtDate(p.inbound))}</h2>
      <div class="price-row"><strong>${e(fmtMoney(p.price))}</strong><span class="discount">${e(fmtPct(p.ratio))}</span></div>
      <dl class="details"><div><dt>來源</dt><dd>${p.verified ? "✓ Google Flights（SerpAPI）" : p.price != null ? "待驗證 · Aviasales 快取" : "尚無報價"}</dd></div><div><dt>航空</dt><dd>${e(p.airline || "—")}</dd></div><div><dt>${p.verified ? "驗證" : "快取觀測"}時間</dt><dd>${e(localTime(p.checked_at))}</dd></div><div><dt>Google 價位</dt><dd>${e(p.price_level || "—")}</dd></div></dl>
      <h3>最近 ${series.length} 筆觀測</h3>${chart(series)}<p class="muted small">同時段以 Google 最低價優先繪圖；實心點為 Google，空心點為快取。</p>${externalLink(p.google_flights_url, "前往 Google Flights 查看／訂票 ↗")}`;
    $("pair-dialog").showModal();
  }

  function renderRecords() {
    const records = bundle.alerts.alerts;
    const hits = records.filter(item => item.verdict === "低點").length;
    $("record-stats").innerHTML = `<div><span>累計推播</span><strong>${bundle.summary.stats.alerts_sent}</strong></div><div><span>保留 ${records.length} 筆 · 低點比例</span><strong>${records.length ? Math.round(hits / records.length * 100) + "%" : "—"}</strong></div>`;
    $("alert-list").innerHTML = records.length ? records.map(item => `<article class="deal-card"><div class="deal-top"><span class="tag ${item.verdict === "低點" ? "verified" : "pending"}">${e(item.verdict)}</span><span class="muted small">${e(localTime(item.alerted_at))}</span></div><h3>${e(fmtDate(item.outbound))} → ${e(fmtDate(item.inbound))}</h3><div class="price-row"><strong>${e(fmtMoney(item.price_at_alert))}</strong><span class="discount">${e(fmtPct(item.ratio_at_alert))}</span></div><p class="muted">現在 ${e(fmtMoney(item.latest_price))} · 推播後最低 ${e(fmtMoney(item.min_price_after))}</p><p class="muted small">${e(item.airline)}</p></article>`).join("") : '<div class="empty"><h3>好價出現時，這裡就有紀錄。</h3><p>尚無推播，最多保留至出發後 90 天。</p></div>';
  }

  function renderSettings() {
    const s = bundle.summary, q = s.budget;
    const fields = [["航線", `${s.route.label}（${s.route.origin} ⇄ ${s.route.destination}）`], ["形式", `直飛來回 · ${s.route.adults} 位成人 · TWD`], ["掃描窗口", `後天起至未來 ${s.window.days_ahead} 天（最早 ${s.window.min_lead_days} 天）`], ["住宿", s.window.stay_nights.join("／") + " 晚"], ["立即推播", `≤ 基準 ${s.thresholds.instant * 100}% · Google 驗證`], ["每日摘要", `≤ 基準 ${s.thresholds.digest * 100}% · ${s.digest.hour_local}:00 後首次掃描`], ["基準回看", `${s.baseline.lookback_days} 天`], ["SerpAPI 額度", `每日 ${q.serpapi_daily_budget}／每月 ${q.serpapi_quota}，安全額 ${q.monthly_safety}`], ["候選保留", `每次最多 ${q.reserve_for_candidates} 組；${q.reverify_hours} 小時內未降價不重驗`], ["重發條件", `再降 ≥${s.dedupe.min_drop_ratio * 100}% 或超過 ${s.dedupe.cooldown_hours} 小時`], ["排程", `台北 09:17／15:17／21:17／03:17`]];
    $("settings-values").innerHTML = `<dl class="details">${fields.map(([name, value]) => `<div><dt>${e(name)}</dt><dd>${e(value)}</dd></div>`).join("")}</dl>`;
    const config = window.LOWFLY_CONFIG;
    const owner = config.owner || (location.hostname.endsWith(".github.io") ? location.hostname.split(".")[0] : "");
    const repo = config.repo || (location.hostname.endsWith(".github.io") ? location.pathname.split("/").filter(Boolean)[0] || `${owner}.github.io` : "");
    if (owner && repo) {
      $("edit-config").href = `https://github.com/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/edit/${encodeURIComponent(config.branch)}/config.yaml`;
      $("edit-config").removeAttribute("aria-disabled");
      $("config-note").textContent = "儲存 config.yaml 後，於下次 Actions 掃描生效。";
    } else {
      $("edit-config").setAttribute("aria-disabled", "true");
      $("config-note").textContent = "本機預覽：先在 docs/config.js 填入 GitHub owner 與 repo，即可開啟編輯連結。";
    }
  }

  function render() { renderHome(); renderCalendar(); renderRecords(); renderSettings(); status(); }
  async function fetchBundle() {
    for (let attempt = 0; attempt < 2; attempt++) {
      let fromCache = false;
      const results = await Promise.all(dataNames.map(async name => {
        const response = await fetch(`./data/${name}.json`, {cache: "no-store", signal: AbortSignal.timeout(12000)});
        if (!response.ok) throw new Error("資料讀取失敗");
        if (response.headers.get("X-LowFly-Cache") === "offline") fromCache = true;
        return [name, await response.json()];
      }));
      const next = Object.fromEntries(results);
      if (coherent(next)) return {next, fromCache};
    }
    throw new Error("資料版本正在更新，稍後再試");
  }

  async function load() {
    if (busy) return;
    busy = true;
    $("refresh").disabled = true;
    try {
      const {next, fromCache} = await fetchBundle();
      bundle = next; cached = fromCache;
      try { localStorage.setItem(storageKey, JSON.stringify(bundle)); } catch { /* 儲存空間不足時仍顯示即時資料。 */ }
      render();
    } catch {
      if (!bundle) {
        try { const saved = JSON.parse(localStorage.getItem(storageKey)); if (coherent(saved)) bundle = saved; } catch { /* 尚無快取。 */ }
      }
      if (bundle) { cached = true; render(); }
      else {
        $("connection").textContent = "目前無法讀取資料 · 連線後點右上方重新整理";
        $("connection").classList.add("offline");
        $("baseline-card").textContent = "尚無離線資料，請先連線載入一次。";
        $("baseline-card").classList.remove("skeleton");
      }
    } finally { busy = false; $("refresh").disabled = false; }
  }

  function navigate() {
    const requested = location.hash.slice(1) || "home";
    const tab = ["home", "calendar", "records", "settings"].includes(requested) ? requested : "home";
    document.querySelectorAll(".view").forEach(view => { view.hidden = view.id !== tab; });
    document.querySelectorAll("[data-tab]").forEach(link => {
      if (link.dataset.tab === tab) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    document.title = `${({home:"首頁", calendar:"價格日曆", records:"通知紀錄", settings:"設定"})[tab]}｜低飛 LowFly`;
  }
  $("refresh").addEventListener("click", load);
  $("deals-only").addEventListener("change", () => bundle && renderCalendar());
  $("close-dialog").addEventListener("click", () => $("pair-dialog").close());
  $("pair-dialog").addEventListener("close", () => previousFocus?.focus());
  $("pair-dialog").addEventListener("click", event => { if (event.target === $("pair-dialog")) $("pair-dialog").close(); });
  $("clear-cache").addEventListener("click", async () => {
    try {
      localStorage.removeItem(storageKey);
      const prefix = `lowfly:${new URL("./", location.href).pathname}:`;
      if ("caches" in window) await Promise.all((await caches.keys()).filter(key => key.startsWith(prefix)).map(key => caches.delete(key)));
      if ("serviceWorker" in navigator) {
        const registration = await navigator.serviceWorker.getRegistration("./");
        if (registration) await registration.unregister();
      }
      $("cache-status").textContent = "已清除此 App 的離線快取；重新開啟後會下載最新資料。";
    } catch { $("cache-status").textContent = "無法清除快取，請於瀏覽器網站設定清除。"; }
  });
  window.addEventListener("hashchange", navigate);
  window.addEventListener("offline", status);
  window.addEventListener("online", load);
  setInterval(status, 60000);
  navigate();
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("./sw.js", {scope:"./"}).catch(() => {});
  load();
})();
