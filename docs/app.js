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
    const relative = relativeTime(at);
    $("updated").hidden = !bundle.summary.stats.runs && !bundle.summary.demo;
    $("updated").textContent = `${relative === "剛剛更新" ? relative : relative + "更新"}${stale ? " · 資料可能過期" : ""}`;
    $("updated").classList.toggle("stale", stale);
    const offline = !navigator.onLine || cached;
    $("connection").className = "connection" + (bundle.summary.demo ? " demo" : offline ? " offline" : "");
    $("connection").textContent = bundle.summary.demo ? "模擬資料 · 僅供預覽，非真實機票報價" :
      offline ? `離線／快取資料 · 上次更新 ${localTime(at)}` :
      bundle.summary.stats.runs ? "票價已更新" : "等待首次掃描";
    $("scan-time").textContent = `資料時間：${localTime(at)}`;
  }

  function renderHome() {
    const s = bundle.summary, b = s.baseline;
    const route = $("route-label");
    route.setAttribute("aria-label", `${s.route.label}，直飛來回，${s.route.adults} 位成人`);
    route.innerHTML = `<div><span>${e(s.route.label.split("⇄")[0].trim())}</span><strong>${e(s.route.origin)}</strong></div><div class="route-journey"><span>直飛來回</span><svg viewBox="0 0 120 24" aria-hidden="true"><path d="M2 12h40m36 0h40"/><path d="m48 12 23-8-7 8 7 8-23-8Z"/></svg><small>${s.route.adults} 位成人</small></div><div><span>${e(s.route.label.split("⇄")[1]?.trim() || s.route.destination)}</span><strong>${e(s.route.destination)}</strong></div>`;
    $("baseline-card").innerHTML = `<span>Google 典型價格基準</span><strong>${b.value == null ? "等待價格資料" : e(fmtMoney(b.value))}</strong><p>${b.google_low == null ? "取得 Google 典型區間後建立參考。" : `典型區間 ${e(fmtMoney(b.google_low))}～${e(Math.round(b.google_high).toLocaleString("en-US"))}`} · 近 ${b.lookback_days} 天 · ${b.n_ranges} 筆觀測</p>`;
    const cheapest = s.cheapest_verified;
    const featured = cheapest?.verified && Number.isFinite(cheapest.price) && cheapest.price > 0 ? cheapest : null;
    $("cheapest").classList.remove("skeleton");
    $("cheapest").innerHTML = featured ? `<div class="fare-kicker"><span>目前已驗證最低價</span><span class="tag verified">Google 已驗證</span></div><div class="fare-price"><small>NT$</small>${e(Math.round(featured.price).toLocaleString("en-US"))}</div>${featured.ratio != null && featured.ratio < 1 ? `<p class="fare-savings">比參考價低 ${e(fmtPct(featured.ratio).replace("-", ""))}</p>` : '<p class="fare-helper">每人來回票價</p>'}<p class="fare-date">${e(fmtDate(featured.outbound))} → ${e(fmtDate(featured.inbound))}</p><p class="fare-airline">${featured.nights} 晚 · ${e(featured.airline || "航空公司未提供")}</p>${externalLink(featured.google_flights_url, "查看航班 ↗")}<a class="fare-secondary" href="#calendar">看看其他日期 →</a>` : `<div class="fare-kicker"><span>你的下一趟旅程</span></div><h2 class="fare-empty-title">等待第一筆票價</h2><p class="fare-helper">完成掃描後，好價會自動出現。</p><a class="primary-button" href="#calendar">查看出發日期 →</a>`;
    const deals = s.deals.filter(item => !featured || item.pair_key !== featured.pair_key);
    const dealCard = item => `<article class="deal-card"><div class="deal-top"><span class="tag ${item.verified ? "verified" : "pending"}">${item.verified ? "Google 已驗證" : "快取 · 待確認"}</span><span class="nights">${item.nights} 晚</span></div><h3>${e(fmtDate(item.outbound))} → ${e(fmtDate(item.inbound))}</h3><div class="price-row"><strong>${e(fmtMoney(item.price))}</strong><span class="discount">${e(fmtPct(item.ratio))}</span></div><div class="deal-bottom"><span class="muted">${e(item.airline || "航空公司未提供")}</span>${externalLink(item.google_flights_url, "查看航班 ↗")}</div></article>`;
    $("deal-section").hidden = !deals.length;
    $("deals-title").textContent = featured ? "其他好價" : "待確認的好價";
    $("deal-count").textContent = `${deals.length} 組日期`;
    $("deals").innerHTML = deals.slice(0, 2).map(dealCard).join("");
    $("remaining-deals").innerHTML = deals.slice(2).map(dealCard).join("");
    $("more-deals").hidden = deals.length <= 2;
    $("more-deals-label").textContent = `再看 ${Math.max(0, deals.length - 2)} 組日期`;
    const q = s.budget;
    $("budget").innerHTML = `<div><span>SerpAPI 本月用量</span><strong>${q.serpapi_used_month}<small> / ${q.serpapi_quota}</small></strong><progress max="${q.serpapi_quota}" value="${q.serpapi_used_month}" aria-label="本月 SerpAPI 用量"></progress></div><div class="budget-bottom"><span>今日 <b>${q.serpapi_used_day} / ${q.serpapi_daily_budget}</b></span><span>快取資料 <b>${q.tp_pairs} 組</b></span></div>`;
  }

  function renderCalendar() {
    const pairs = bundle.pairs.pairs;
    const dates = [...new Set(pairs.map(p => p.outbound))];
    const nights = bundle.summary.window.stay_nights;
    const only = $("deals-only").checked;
    const visibleDates = only ? dates.filter(date => pairs.some(p => p.outbound === date && p.price != null && p.ratio != null && p.ratio <= bundle.summary.thresholds.digest)) : dates;
    if (!visibleDates.length) { $("heatmap").innerHTML = '<div class="empty"><h3>目前沒有符合的好價</h3><p>取消篩選，可查看全部出發日。</p></div>'; return; }
    $("heatmap").innerHTML = `<table class="heatmap"><caption class="sr-only">依出發日與住宿晚數排列的來回票價，單位新台幣</caption><thead><tr><th scope="col">出發日</th>${nights.map(n => `<th scope="col">${n} 晚</th>`).join("")}</tr></thead><tbody>${visibleDates.map(date => `<tr><th scope="row" class="${[0, 6].includes(new Date(date + "T12:00:00+08:00").getUTCDay()) ? "weekend" : ""}">${e(fmtDate(date))}</th>${nights.map(n => {
      const p = pairs.find(pair => pair.outbound === date && pair.nights === n);
      if (!p) return "<td>—</td>";
      const filtered = only && (p.ratio == null || p.ratio > bundle.summary.thresholds.digest);
      if (filtered) return '<td class="muted" aria-label="此組日期未達好價門檻" style="text-align:center">—</td>';
      const label = `${fmtDate(date)}，${n} 晚，${fmtMoney(p.price)}，${p.verified ? "已驗證" : "待驗證"}`;
      return `<td><button data-pair="${e(p.pair_key)}" class="heat-cell ${ratioClass(p.ratio, p.price)} ${filtered ? "filtered" : ""}" aria-label="${e(label)}">${p.price == null ? "—" : e(Math.round(p.price).toLocaleString("en-US"))}<small>${p.verified ? "✓" : p.price == null ? "" : "快取"}</small></button></td>`;
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
    $("pair-detail").innerHTML = `<p class="eyebrow">${p.nights} 晚 · 直飛來回</p><h2 id="pair-title">${e(fmtDate(p.outbound))} → ${e(fmtDate(p.inbound))}</h2><span class="tag ${p.verified ? "verified" : "pending"}">${p.verified ? "Google 已驗證" : p.price != null ? "快取 · 待確認" : "尚無報價"}</span><div class="price-row"><strong>${e(fmtMoney(p.price))}</strong><span class="discount">${e(fmtPct(p.ratio))}</span></div><p class="muted small">${e(p.airline || "航空公司尚未提供")}</p>${externalLink(p.google_flights_url, "查看 Google Flights 航班 ↗")}<details class="disclosure record-detail"><summary>價格紀錄與來源</summary><dl class="details"><div><dt>來源</dt><dd>${p.verified ? "Google Flights（SerpAPI）" : p.price != null ? "Aviasales 快取，尚未驗證" : "尚無報價"}</dd></div><div><dt>查詢時間</dt><dd>${e(localTime(p.checked_at))}</dd></div><div><dt>Google 價位</dt><dd>${e(p.price_level || "—")}</dd></div></dl>${chart(series)}<p class="muted small">實心點為 Google，空心點為快取。</p></details>`;
    $("pair-dialog").showModal();
  }

  function renderRecords() {
    const records = bundle.alerts.alerts;
    const hits = records.filter(item => item.verdict === "低點").length;
    $("record-stats").hidden = !records.length;
    $("record-help").hidden = !records.length;
    $("record-stats").innerHTML = `已提醒 <strong>${bundle.summary.stats.alerts_sent}</strong> 次 · 低點比例 <strong>${records.length ? Math.round(hits / records.length * 100) + "%" : "—"}</strong>`;
    $("alert-list").innerHTML = records.length ? records.map(item => `<article class="deal-card"><div class="deal-top"><span class="tag ${item.verdict === "低點" ? "verified" : "pending"}">${e(item.verdict)}</span><span class="muted small">${e(fmtDate(item.alerted_at))}</span></div><h3>${e(fmtDate(item.outbound))} → ${e(fmtDate(item.inbound))}</h3><div class="price-row"><strong>${e(fmtMoney(item.price_at_alert))}</strong><span class="discount">${e(fmtPct(item.ratio_at_alert))}</span></div><p class="muted small">${e(item.airline)}</p><details class="disclosure record-detail"><summary>提醒後的價格</summary><p>現在 ${e(fmtMoney(item.latest_price))} · 提醒後最低 ${e(fmtMoney(item.min_price_after))}</p><p>${e(localTime(item.alerted_at))}</p></details></article>`).join("") : '<div class="empty"><h3>好價出現，就會提醒你。</h3><p>目前還沒有提醒紀錄。</p></div>';
  }

  function renderSettings() {
    const s = bundle.summary, q = s.budget;
    $("settings-overview").innerHTML = `<strong>${e(s.route.label)} · 直飛來回</strong><p>${s.route.adults} 位成人 · ${s.window.stay_nights.join("／")} 晚 · 每天自動掃描 ${s.schedule.runs_per_day} 次</p>`;
    const fields = [["航線", `${s.route.label}（${s.route.origin} ⇄ ${s.route.destination}）`], ["形式", `直飛來回 · ${s.route.adults} 位成人 · TWD`], ["掃描窗口", `後天起至未來 ${s.window.days_ahead} 天（最早 ${s.window.min_lead_days} 天）`], ["住宿", s.window.stay_nights.join("／") + " 晚"], ["立即推播", `≤ 基準 ${s.thresholds.instant * 100}% · Google 驗證`], ["每日摘要", `≤ 基準 ${s.thresholds.digest * 100}% · ${s.digest.hour_local}:00 後首次掃描`], ["基準回看", `${s.baseline.lookback_days} 天`], ["SerpAPI 額度", `每日 ${q.serpapi_daily_budget}／每月 ${q.serpapi_quota}，安全額 ${q.monthly_safety}`], ["候選保留", `每次最多 ${q.reserve_for_candidates} 組；${q.reverify_hours} 小時內未降價不重驗`], ["重發條件", `再降 ≥${s.dedupe.min_drop_ratio * 100}% 或超過 ${s.dedupe.cooldown_hours} 小時`], ["排程", `台北 09:17／15:17／21:17／03:17`]];
    $("settings-values").innerHTML = `<dl class="details">${fields.map(([name, value]) => `<div><dt>${e(name)}</dt><dd>${e(value)}</dd></div>`).join("")}</dl>`;
    const config = window.LOWFLY_CONFIG;
    const owner = config.owner || (location.hostname.endsWith(".github.io") ? location.hostname.split(".")[0] : "");
    const repo = config.repo || (location.hostname.endsWith(".github.io") ? location.pathname.split("/").filter(Boolean)[0] || `${owner}.github.io` : "");
    if (owner && repo) {
      $("edit-config").href = `https://github.com/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/edit/${encodeURIComponent(config.branch)}/config.yaml`;
      $("edit-config").removeAttribute("aria-disabled");
      $("config-note").textContent = "在 GitHub 儲存後，於下次掃描生效。";
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
        $("connection").textContent = "目前無法讀取資料";
        $("connection").classList.add("offline");
        $("cheapest").innerHTML = '<h2 class="fare-empty-title">暫時無法讀取票價</h2><p class="fare-helper">連線後，點右上角重新整理。</p>';
        $("cheapest").classList.remove("skeleton");
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
