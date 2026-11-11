(function () {
  "use strict";
  const {fmtDate, fmtMoney, fmtPct, ratioClass, escapeHTML: e, safeURL, coherent} = window.LowFly;
  const $ = id => document.getElementById(id);
  const storageKey = "lowfly-bundle-v1";
  const dataNames = ["summary", "pairs", "history", "alerts"];
  let bundle = null, cached = false, busy = false;
  let previousFocus = null;
  const plainData = value => typeof value === "string" ? !/[<>"]/.test(value) :
    Array.isArray(value) ? value.every(plainData) : value && typeof value === "object" ? Object.values(value).every(plainData) : true;

  function externalLink(url, label, cls = "flight-link") {
    const safe = safeURL(url);
    return safe ? `<a class="${cls}" href="${e(safe)}" target="_blank" rel="noopener noreferrer">${e(label)}</a>` : "<span class=\"muted small\">連結暫無</span>";
  }
  function localTime(value) {
    return value ? new Date(value).toLocaleString("zh-TW", {timeZone: bundle?.summary.timezone || "Asia/Taipei", hour12: false}) : "尚未查詢";
  }
  function clock(value) {
    return new Date(value).toLocaleTimeString("zh-TW", {timeZone: bundle?.summary.timezone || "Asia/Taipei", hour12: false, hour: "2-digit", minute: "2-digit"});
  }
  function status() {
    if (!bundle) return;
    const at = bundle.summary.generated_at;
    const stale = Date.now() - Date.parse(at) > 8 * 3600000;
    $("updated").hidden = !bundle.summary.stats.runs && !bundle.summary.demo;
    $("updated").textContent = `${clock(at)} 更新${stale ? "，資料可能過期" : ""}`;
    $("updated").classList.toggle("stale", stale);
    const offline = !navigator.onLine || cached;
    $("connection").className = "connection" + (bundle.summary.demo ? " demo" : offline ? " offline" : "");
    $("connection").textContent = bundle.summary.demo ? "模擬資料，僅供預覽，非真實機票報價" :
      offline ? `離線，顯示 ${localTime(at)} 的資料` :
      bundle.summary.stats.runs ? "" : "等待首次掃描";
    $("connection").hidden = !$("connection").textContent;
    $("scan-time").textContent = `資料時間：${localTime(at)}`;
  }

  // price 是含行李的總價（半價以此判斷）；fare 是不含行李的票價。checked_kg=0 或 fare 為空（舊資料）時只顯示一個價格。
  function bagInfo(item) {
    const kg = bundle?.summary.baggage?.checked_kg;
    if (!kg || item.fare == null || item.bag_fee == null) return null;
    return {kg, included: !item.bag_fee, estimated: Boolean(item.bag_estimated)};
  }
  function bagLine(item) {
    const info = bagInfo(item);
    if (!info) return "";
    if (info.included) return `${fmtMoney(item.fare)}（已含 ${e(info.kg)}kg 託運）`;
    return `不含行李 ${fmtMoney(item.fare)}｜含行李 ${fmtMoney(item.price)}（${e(info.kg)}kg 來回${info.estimated ? "，行李費估算" : ""}）`;
  }
  const priceBig = value => `<div class="fare-price"><small>NT$</small>${e(Math.round(value).toLocaleString("en-US"))}</div>`;
  function fareBlock(item) {
    const info = bagInfo(item);
    if (!info) return `<div class="fare-pair single">${priceBig(item.price)}</div>`;
    if (info.included) return `<div class="fare-pair single">${priceBig(item.price)}<small class="fare-note">已含 ${e(info.kg)}kg 託運</small></div>`;
    return `<div class="fare-pair"><div><small class="fare-note">不含行李</small>${priceBig(item.fare)}</div><div><small class="fare-note">含行李</small>${priceBig(item.price)}<small class="fare-note">${e(info.kg)}kg 來回${info.estimated ? "，行李費估算" : ""}</small></div></div><p class="fare-helper">半價與好價都以含行李價判斷</p>`;
  }
  const modeText = r => r.direct_only === false ? "來回" : "直飛來回";
  const AIRPORT_ZH = {TPE: "桃園", TSA: "松山", HKG: "香港", MFM: "澳門", TYO: "東京", NRT: "東京成田", HND: "東京羽田"};
  const WEEK = "日一二三四五六";
  const routeColor = r => /^#[0-9A-Fa-f]{6}$/.test(r?.color || "") ? r.color : "#5B6673";
  const md = date => `${Number(date.slice(5, 7))}/${Number(date.slice(8, 10))}`;
  const dayLabel = date => `${md(date)} 週${WEEK[new Date(date + "T12:00:00+08:00").getUTCDay()]}`;
  const duration = minutes => Number.isFinite(minutes) && minutes > 0 ? `${Math.floor(minutes / 60)}h${String(minutes % 60).padStart(2, "0")}m` : "";
  const plane = '<svg viewBox="0 0 120 24" aria-hidden="true"><path class="rail" d="M2 12h44m28 0h44"/><path class="jet" d="m72 12-22-8 6 8-6 8 22-8Z"/></svg>';
  function logo(code) {
    const safe = /^[A-Z0-9]{2}$/.test(code || "") ? code : "";
    return safe ? `<img class="logo" src="https://pics.avs.io/48/48/${safe}.png" width="24" height="24" alt="" loading="lazy" data-code="${safe}" referrerpolicy="no-referrer">` : "";
  }
  function ratioText(r, item) {
    const b = r.baseline;
    if (b.value == null) return `基準累積中 ${e(b.samples ?? 0)}/${e(b.min_samples ?? 15)}`;
    if (item.ratio == null) return "";
    const pct = fmtPct(item.ratio).replace(/^[-+]/, "");
    return item.ratio < 1 ? `比基準低 ${pct}` : item.ratio > 1 ? `比基準高 ${pct}` : "與基準相同";
  }
  // 半價（比例 ≤ 即時門檻）優先；否則含行李總價 ≤ 航線好價線算「好價」。
  function dealKind(r, item) {
    if (!item || item.price == null) return "";
    if (item.ratio != null && item.ratio <= (bundle.summary.thresholds?.instant ?? 0.5)) return "半價";
    return r.good_price != null && item.price <= r.good_price ? "好價" : "";
  }
  const notesBlock = item => item.notes?.length ? `<div class="t-notes"><strong>須知</strong><ul>${item.notes.map(note => `<li>${e(note)}</li>`).join("")}</ul></div>` : "";
  // 近 N 天均價：舊資料沒有 average 欄位或還沒有樣本時不顯示。
  const avgLine = r => r.average?.value != null ? `<p class="t-avg">近 ${e(r.average.days)} 天含行李均價 <b>${e(fmtMoney(r.average.value))}</b>，${e(r.average.samples)} 筆</p>` : "";
  const baselineSource = r => r.baseline?.value == null ? "" : r.baseline.source === "travelpayouts" ? "基準 Travelpayouts 中位數" : "基準 Google 典型價格";
  // 價格條碼：未來每個出發日的最低含行李價（高＝貴），本張票的日期用航線色，沒資料的日子留空。
  function barcode(r, activeDate) {
    const mine = bundle.pairs.pairs.filter(p => p.route_id === r.id);
    const best = new Map();
    for (const p of mine) if (p.price != null && (!best.has(p.outbound) || p.price < best.get(p.outbound))) best.set(p.outbound, p.price);
    if (!best.size) return "";
    const values = [...best.values()], low = Math.min(...values), high = Math.max(...values);
    const bars = [...new Set(mine.map(p => p.outbound))].sort().map(date => {
      if (!best.has(date)) return '<i class="bar gap"></i>';
      const height = high === low ? 55 : 20 + (best.get(date) - low) / (high - low) * 80;
      return `<i class="bar${date === activeDate ? " on" : ""}" style="height:${height.toFixed(0)}%"></i>`;
    }).join("");
    return `<div class="barcode" role="img" aria-label="未來每個出發日的最低含行李價，高度越高越貴">${bars}</div>`;
  }
  function ticket(r, item, verified) {
    const origin = item?.origin_airport || r.origin, dest = item?.destination_airport || r.destination;
    const adults = r.adults || 1;
    const label = `${r.label}，${modeText(r)}，${adults} 位成人`;
    const codes = `<div class="t-route"><div class="code">${e(origin)}</div><div class="t-mid">${item && duration(item.duration_to) ? `<span>${e(duration(item.duration_to))}</span>` : ""}${plane}</div><div class="code">${e(dest)}</div></div>`;
    if (!item) {
      const b = r.baseline;
      return `<article class="ticket" style="--route:${routeColor(r)}" aria-label="${e(label)}"><div class="t-body"><div class="t-head"><span class="t-name">${e(r.label)}</span><span class="t-tag">${modeText(r)}</span></div>${codes}<p class="t-empty">等待第一筆票價</p><p class="t-sub">${b.value == null ? `基準累積中 ${e(b.samples ?? 0)}/${e(b.min_samples ?? 15)}` : e(baselineSource(r))}</p></div><div class="t-actions"><a class="t-link" href="#calendar">查看出發日期</a></div></article>`;
    }
    const kind = dealKind(r, item);
    const airline = [item.airline, item.flight_no].filter(Boolean).join(" ");
    const hasTimes = item.depart_time && item.arrive_time;
    const names = `<div class="t-places"><span>${e(AIRPORT_ZH[origin] || origin)}${hasTimes ? ` <b>${e(item.depart_time)}</b>` : ""}</span><span>${e(AIRPORT_ZH[dest] || dest)}${hasTimes ? ` <b>${e(item.arrive_time)}</b>` : ""}</span></div>`;
    const back = item.return_depart_time ? ` ${e(item.return_depart_time)} 起飛` : "";
    const dates = `<p class="t-dates"><span>去 ${e(dayLabel(item.outbound))}</span><span>回 ${e(dayLabel(item.inbound))}${r.return_origin ? "・" + e(AIRPORT_ZH[r.return_origin] || r.return_origin) : ""}${back}</span><span>${e(item.nights)} 晚</span></p>`;
    const ratio = ratioText(r, item), source = baselineSource(r);
    return `<article class="ticket${kind ? " is-half" : ""}" style="--route:${routeColor(r)}" aria-label="${e(label)}"><div class="t-body"><div class="t-head"><span class="airline">${logo(item.airline_code)}<span>${e(airline || r.label)}</span></span><span class="t-tag">${item.split ? "兩張單程" : modeText(r)}</span></div>${codes}${names}${dates}</div><div class="tear" aria-hidden="true"></div><div class="t-price">${kind ? `<div class="stamp" role="img" aria-label="${kind}">${kind}</div>` : ""}${fareBlock(item)}${notesBlock(item)}<p class="t-state">${verified ? "Google 已驗證" : "Travelpayouts 快取價，未經 Google 驗證"}</p>${barcode(r, item.outbound)}<p class="t-ratio"><strong>${e(ratio)}</strong>${source ? `<span>${e(source)}</span>` : ""}</p>${avgLine(r)}<div class="t-actions">${externalLink(item.google_flights_url, "去訂票", "btn")}<a class="t-link" href="#calendar">看其他日期</a></div></div></article>`;
  }
  function routeCard(r) {
    const cheapest = r.cheapest_verified;
    const verified = cheapest?.verified && Number.isFinite(cheapest.price) && cheapest.price > 0 ? cheapest : null;
    // 沒有已驗證價時，退回該航線 Travelpayouts 最便宜的快取價（匯出的 cheapest_cached，或好價清單中最低者）。
    const cachedPool = [r.cheapest_cached, ...r.deals.filter(item => !item.verified)].filter(item => item && Number.isFinite(item.price) && item.price > 0);
    const cached = verified ? null : cachedPool.sort((a, b) => a.price - b.price)[0] || null;
    const featured = verified || cached;
    return {featured, verified: Boolean(verified), html: ticket(r, featured, Boolean(verified))};
  }
  function leadText(routes, cards) {
    const hits = routes.map((r, i) => ({r, item: cards[i].featured, kind: dealKind(r, cards[i].featured)})).filter(hit => hit.kind);
    const city = r => AIRPORT_ZH[r.destination] || r.label;
    if (hits.length === 1) return `${city(hits[0].r)}有${hits[0].kind}票：${md(hits[0].item.outbound)} ${fmtMoney(hits[0].item.price)}`;
    if (hits.length) return `${hits.map(({r}) => city(r)).join("、")}有${hits.every(hit => hit.kind === "半價") ? "半價" : "好價"}票`;
    if (!cards.some(card => card.featured)) return "還在等第一筆票價";
    return `${["零", "一", "兩", "三", "四", "五", "六"][routes.length] || routes.length}條航線都還沒有好價票`;
  }

  function renderHome() {
    const s = bundle.summary;
    const cards = s.routes.map(routeCard);
    $("home-title").textContent = leadText(s.routes, cards);
    $("route-cards").innerHTML = cards.map(card => card.html).join("");
    const deals = s.routes.flatMap((r, i) => r.deals
      .filter(item => !cards[i].featured || item.pair_key !== cards[i].featured.pair_key)
      .map(item => ({...item, route_label: r.label, color: routeColor(r)}))).sort((a, b) => a.ratio - b.ratio);
    const dealCard = item => `<article class="deal-row" style="--route:${e(item.color)}"><div class="deal-line"><strong>${e(item.route_label)}</strong><span>${e(md(item.outbound))}–${e(md(item.inbound))}　${e(item.nights)} 晚</span></div><div class="deal-price"><span class="amount">${e(fmtMoney(item.price))}</span><span class="discount">${e(fmtPct(item.ratio))}</span></div>${bagLine(item) ? `<p class="muted small">${e(bagLine(item))}</p>` : ""}${item.notes?.length ? `<p class="deal-notes">須知：${e(item.notes.join("；"))}</p>` : ""}<div class="deal-bottom"><span class="muted small">${e(item.airline || "航空公司未提供")}　${item.verified ? "Google 已驗證" : "快取價，未經驗證"}${item.split ? "　兩張單程" : ""}</span>${externalLink(item.google_flights_url, "去訂票")}</div></article>`;
    $("deal-section").hidden = !deals.length;
    $("deals-title").textContent = cards.some(card => card.verified) ? "其他好價" : "待確認的好價";
    $("deal-count").textContent = `${deals.length} 組日期`;
    $("deals").innerHTML = deals.slice(0, 2).map(dealCard).join("");
    $("remaining-deals").innerHTML = deals.slice(2).map(dealCard).join("");
    $("more-deals").hidden = deals.length <= 2;
    $("more-deals-label").textContent = `再看 ${Math.max(0, deals.length - 2)} 組日期`;
    $("baseline-card").innerHTML = s.routes.map(r => { const b = r.baseline; return `<div class="base-row"><span>${e(r.label)}　${b.source === "travelpayouts" ? "Travelpayouts 中位數" : b.value == null ? "尚無基準" : "Google 典型價格"}</span><strong>${b.value == null ? `累積中 ${e(b.samples ?? 0)}/${e(b.min_samples ?? 15)}` : e(fmtMoney(b.value))}</strong><p>${b.source === "travelpayouts" ? "以近期 Travelpayouts 快取價的中位數估算；取得 Google 典型區間後自動改用 Google。" : b.google_low == null ? "取得 Google 典型區間後建立參考。" : `典型區間 ${e(fmtMoney(b.google_low))}～${e(Math.round(b.google_high).toLocaleString("en-US"))}`}　近 ${e(b.lookback_days)} 天，${e(b.n_ranges)} 筆觀測</p></div>`; }).join("");
    const q = s.budget;
    $("budget").innerHTML = `<div><span>SerpAPI 本月用量</span><strong>${e(q.serpapi_used_month)}<small> / ${e(q.serpapi_quota)}</small></strong><progress max="${e(q.serpapi_quota)}" value="${e(q.serpapi_used_month)}" aria-label="本月 SerpAPI 用量"></progress></div><div class="budget-bottom"><span>今日 <b>${e(q.serpapi_used_day)} / ${e(q.serpapi_daily_budget)}</b></span><span>快取資料 <b>${e(q.tp_pairs)} 組</b></span></div>`;
  }

  // 預算模式：所有航線、所有出發日裡，含行李總價不超過預算的組合，由便宜到貴；預算只存在這支手機。
  const spendKey = "lowfly-spend-v1";
  function renderSpend() {
    const value = Number($("spend-input").value);
    const budget = Number.isFinite(value) && value > 0 ? value : null;
    const routes = new Map(bundle.summary.routes.map(r => [r.id, r]));
    const priced = bundle.pairs.pairs.filter(p => p.price != null && routes.has(p.route_id));
    const hits = budget == null ? [] : priced.filter(p => p.price <= budget).sort((a, b) => a.price - b.price || a.outbound.localeCompare(b.outbound));
    const city = id => AIRPORT_ZH[routes.get(id).destination] || routes.get(id).label;
    const row = p => `<article class="deal-row" style="--route:${e(routeColor(routes.get(p.route_id)))}"><div class="deal-line"><strong>${e(routes.get(p.route_id).label)}</strong><span>${e(dayLabel(p.outbound))}–${e(md(p.inbound))}　${e(p.nights)} 晚</span></div><div class="deal-price"><span class="amount">${e(fmtMoney(p.price))}</span><span class="discount">剩 ${e(fmtMoney(budget - p.price))}</span></div><div class="deal-bottom"><span class="muted small">${e(p.airline || "航空公司未提供")}　${p.verified ? "Google 已驗證" : "快取價，未經驗證"}${p.split ? "　兩張單程" : ""}</span>${externalLink(p.google_flights_url, "去訂票")}</div></article>`;
    const counts = [...routes.keys()].map(id => [id, hits.filter(p => p.route_id === id).length]).filter(([, n]) => n);
    $("spend-count").textContent = budget == null ? "輸入預算，看哪些日期去得成" : `${hits.length} 組日期${counts.length ? `（${counts.map(([id, n]) => `${city(id)} ${n}`).join("、")}）` : ""}`;
    const cheapest = priced.reduce((low, p) => !low || p.price < low.price ? p : low, null);
    $("spend-list").innerHTML = budget == null ? "" : hits.length ? hits.slice(0, 3).map(row).join("") :
      `<p class="muted small">預算內沒有組合${cheapest ? `；目前最便宜是${e(city(cheapest.route_id))} ${e(md(cheapest.outbound))} 出發 ${e(fmtMoney(cheapest.price))}` : ""}。</p>`;
    $("spend-rest").innerHTML = hits.slice(3).map(row).join("");
    $("spend-more").hidden = hits.length <= 3;
    $("spend-more-label").textContent = `再看 ${Math.max(0, hits.length - 3)} 組日期`;
  }

  function routeHeatmap(r, only) {
    const pairs = bundle.pairs.pairs.filter(p => p.route_id === r.id);
    const dates = [...new Set(pairs.map(p => p.outbound))];
    const nights = r.stay_nights;
    const visibleDates = only ? dates.filter(date => pairs.some(p => p.outbound === date && p.price != null && p.ratio != null && p.ratio <= bundle.summary.thresholds.digest)) : dates;
    const heading = `<h2 class="route-title" id="cal-${e(r.id)}" tabindex="-1" style="--route:${routeColor(r)}">${e(r.label)}</h2>`;
    if (!visibleDates.length) return `<section class="route-block">${heading}<div class="empty"><h3>目前沒有符合的好價</h3><p>取消篩選，可查看全部出發日。</p></div></section>`;
    return `<section class="route-block">${heading}<table class="heatmap"><caption class="sr-only">${e(r.label)}，依出發日與住宿晚數排列的來回票價，單位新台幣</caption><thead><tr><th scope="col">出發日</th>${nights.map(n => `<th scope="col">${n} 晚</th>`).join("")}</tr></thead><tbody>${visibleDates.map(date => `<tr><th scope="row" class="${[0, 6].includes(new Date(date + "T12:00:00+08:00").getUTCDay()) ? "weekend" : ""}">${e(fmtDate(date))}</th>${nights.map(n => {
      const p = pairs.find(pair => pair.outbound === date && pair.nights === n);
      if (!p) return "<td>—</td>";
      const filtered = only && (p.ratio == null || p.ratio > bundle.summary.thresholds.digest);
      if (filtered) return '<td class="muted" aria-label="此組日期未達好價門檻" style="text-align:center">—</td>';
      // 不只靠底色：半價標 ★、≤70% 標 ▼（色盲也分得出好價）；讀屏名稱以格內可見文字開頭（WCAG 2.5.3）。
      const cls = ratioClass(p.ratio, p.price), mark = cls === "r50" ? "★" : cls === "r70" ? "▼" : "";
      const shown = p.price == null ? "—" : Math.round(p.price).toLocaleString("en-US"), tag = p.verified ? "✓" : p.price == null ? "" : "快取";
      const label = `${mark}${shown}${tag}，${r.label}，${fmtDate(date)}，${n} 晚，${p.verified ? "已驗證" : "待驗證"}${p.ratio != null ? `，基準的 ${Math.round(p.ratio * 100)}%` : ""}`;
      return `<td><button data-pair="${e(p.pair_key)}" class="heat-cell ${cls} ${filtered ? "filtered" : ""}" aria-label="${e(label)}">${mark}${e(shown)}<small>${tag}</small></button></td>`;
    }).join("")}</tr>`).join("")}</tbody></table></section>`;
  }

  function renderCalendar() {
    const only = $("deals-only").checked;
    // 日曆很長（每條航線數十列）：頂端加跳轉按鈕，鍵盤不必 Tab 過整張表（WCAG 2.4.1）。分頁用 hash 路由，所以不用錨點。
    const jump = bundle.summary.routes.length > 1 ? `<nav class="jump" aria-label="跳到航線">${bundle.summary.routes.map(r => `<button type="button" class="secondary-button" data-jump="cal-${e(r.id)}">${e(r.return_origin ? r.label : AIRPORT_ZH[r.destination] || r.label)}</button>`).join("")}</nav>` : "";
    $("heatmap").innerHTML = jump + bundle.summary.routes.map(r => routeHeatmap(r, only)).join("");
    $("heatmap").querySelectorAll("[data-jump]").forEach(button => button.addEventListener("click", () => {
      const heading = $(button.dataset.jump);
      heading.scrollIntoView({block: "start"});
      heading.focus({preventScroll: true});
    }));
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
    const route = bundle.summary.routes.find(r => r.id === p.route_id);
    const series = (bundle.history.series[p.route_id] || {})[key] || [];
    const flight = [p.airline, p.flight_no].filter(Boolean).join(" ") + (p.depart_time && p.arrive_time ? `　${p.depart_time}–${p.arrive_time}` : "");
    $("pair-detail").innerHTML = `<div class="pair-wrap" style="--route:${routeColor(route)}"><h2 id="pair-title">${e(route?.label || p.route_id)}　${e(md(p.outbound))}–${e(md(p.inbound))}</h2><p class="muted small">${e(p.nights)} 晚　${route ? modeText(route) : "直飛來回"}${flight ? `　${e(flight)}` : ""}</p>${p.price == null ? '<p class="t-empty">尚無報價</p>' : `${fareBlock(p)}<p class="t-state">${p.verified ? "Google 已驗證" : "Travelpayouts 快取價，未經 Google 驗證"}</p>${route ? `<p class="t-ratio"><strong>${e(ratioText(route, p))}</strong></p>` : ""}`}${externalLink(p.google_flights_url, "去訂票", "btn")}<details class="disclosure record-detail"><summary>價格紀錄與來源</summary><dl class="details"><div><dt>來源</dt><dd>${p.verified ? "Google Flights（SerpAPI）" : p.price != null ? "Aviasales 快取，尚未驗證" : "尚無報價"}</dd></div><div><dt>查詢時間</dt><dd>${e(localTime(p.checked_at))}</dd></div><div><dt>Google 價位</dt><dd>${e(p.price_level || "—")}</dd></div></dl>${chart(series)}<p class="muted small">實心點為 Google，空心點為快取。</p></details></div>`;
    $("pair-dialog").showModal();
  }

  function renderRecords() {
    const records = bundle.alerts.alerts;
    const hits = records.filter(item => item.verdict === "低點").length;
    const colors = Object.fromEntries(bundle.summary.routes.map(r => [r.id, routeColor(r)]));
    $("record-stats").hidden = !records.length;
    $("record-help").hidden = !records.length;
    $("record-stats").innerHTML = `已提醒 <strong>${e(bundle.summary.stats.alerts_sent)}</strong> 次　低點比例 <strong>${records.length ? Math.round(hits / records.length * 100) + "%" : "—"}</strong>`;
    $("alert-list").innerHTML = records.length ? records.map(item => `<article class="deal-row" style="--route:${e(colors[item.route_id] || "#5B6673")}"><div class="deal-line"><strong>${e(String(item.route_label || "").replace("⇄", "→"))} ${e(md(item.outbound))}–${e(md(item.inbound))} 降到 ${e(fmtMoney(item.price_at_alert))}${item.baseline_at_alert != null ? `（基準 ${e(fmtMoney(item.baseline_at_alert))}）` : ""}</strong></div><div class="deal-bottom"><span class="verdict">${e(item.verdict)}</span><span class="muted small">${e(item.airline)}　通知於 ${e(localTime(item.alerted_at))}</span></div><details class="disclosure record-detail"><summary>提醒後的價格</summary><p>現在 ${e(fmtMoney(item.latest_price))}　提醒後最低 ${e(fmtMoney(item.min_price_after))}</p></details></article>`).join("") : '<div class="empty"><h3>目前還沒有提醒紀錄</h3><p>票價降到基準的一半以下時，會用 Telegram 通知並記在這裡。</p></div>';
  }

  function renderMarket() {
    const routes = bundle.summary.routes, num = v => v == null ? "—" : Math.round(v).toLocaleString("en-US");
    const name = r => AIRPORT_ZH[r.destination] || r.label;
    const cell = (v, note) => `<td>${e(num(v))}${note ? `<small>${e(note)}</small>` : ""}</td>`;
    const updated = routes.map(r => r.market?.updated_at).find(Boolean);
    $("market-table").innerHTML = `<table class="market-table"><caption class="sr-only">各航線來回均價，單位新台幣</caption><thead><tr><th scope="col">航線</th><th scope="col">過去 3 個月</th><th scope="col">過去 6 個月</th><th scope="col">未來 3 個月</th><th scope="col">未來 6 個月</th></tr></thead><tbody>${routes.map(r => {
      const m = r.market || {}, days = x => x?.days ? `${x.days} 天紀錄` : "", count = x => x?.n ? `${e(x.n)} 組` : "";
      return `<tr><th scope="row">${e(name(r))}</th>${cell(m.past_3m?.total, days(m.past_3m))}${cell(m.past_6m?.total, days(m.past_6m))}${cell(m.next_3m?.total, count(m.next_3m))}${cell(m.next_6m?.total, count(m.next_6m))}</tr>`;
    }).join("")}</tbody></table><p class="muted small">${updated ? `未來均價更新於 ${e(md(updated.slice(0, 10)))} ${e(updated.slice(11, 16))}，含行李。` : "未來均價會在每天第一次掃描後產生。"}過去均價是 LowFly 每天記錄的含行李價，自 11/2 起累積，滿 3／6 個月前天數較少。</p>`;
    $("market-detail").innerHTML = routes.map(r => {
      const m = r.market || {};
      const months = (m.months || []).map(x => `<tr><th scope="row">${Number(x.month.slice(5))} 月</th>${cell(x.total)}${cell(x.fare)}${cell(x.min)}<td>${e(x.n)}</td></tr>`).join("");
      const refs = (m.reference || []).map(x => `<li>${externalLink(x.url, x.source)}：${e(x.text)}</li>`).join("");
      return `<details class="disclosure market-route"><summary>${e(r.label)} 各月份</summary>${months ? `<table class="market-table"><caption class="sr-only">${e(r.label)} 未來各出發月份均價</caption><thead><tr><th scope="col">出發月份</th><th scope="col">含行李均價</th><th scope="col">不含行李</th><th scope="col">最低</th><th scope="col">組數</th></tr></thead><tbody>${months}</tbody></table>` : '<p class="muted">尚無未來月份資料。</p>'}${refs ? `<ul class="muted small">${refs}</ul>` : ""}</details>`;
    }).join("");
  }

  // AI 團隊：四位助手的分工與即時狀態，只用公開資料（提示詞與設定不在網站上）。舊快取沒有 team 欄位時不顯示。
  function renderTeam() {
    const s = bundle.summary, t = s.team;
    if (!t) { $("team-cards").innerHTML = ""; return; }
    const hours = (Date.now() - Date.parse(s.generated_at)) / 3600000;
    const light = hours > 18 ? "red" : hours > 8 ? "amber" : "green";
    const label = {green: "正常", amber: "資料延遲", red: "需要處理"};
    const watched = s.airline_sales?.enabled ? s.airline_sales.airlines.length : 0;
    const members = [
      ["🗼", "塔台", "總監", "收你的口述，複述確認後派工並驗收", t.report_date ? `最近團隊週報 ${md(t.report_date)}` : "團隊週報：每週一 09:00 後送出", "green"],
      ["🧭", "領航員", "票價分析", "追蹤各航線含行李價、基準與推播", `近 7 天推播 ${t.alerts_7d} 則，有價組合 ${s.budget.tp_pairs} 組`, light],
      ["🔭", "瞭望員", "促銷情報", `監看 ${watched} 家廉航的促銷消息與規則`, `近 7 天推出促銷消息 ${t.sales_7d} 則`, watched ? "green" : "amber"],
      ["🛠️", "地勤", "維運", "排程掃描、失敗告警、看門狗與資安", hours > 8 ? `資料已 ${Math.floor(hours)} 小時沒更新，看門狗會自動補跑` : `已完成 ${t.runs} 輪掃描，最近 ${clock(s.generated_at)}`, light]];
    $("team-cards").innerHTML = members.map(([icon, name, role, duty, now, state]) => `<article class="member"><div class="avatar" aria-hidden="true">${icon}</div><div class="member-body"><p class="member-head"><strong>${e(name)}</strong><span>${e(role)}</span><span class="light ${state}">${label[state]}</span></p><p class="muted small">${e(duty)}</p><p class="member-now">${e(now)}</p></div></article>`).join("");
  }
  function renderSettings() {
    const s = bundle.summary, q = s.budget;
    $("settings-overview").innerHTML = s.routes.map(r => `<p><strong>${e(r.label)}</strong>　${modeText(r)}　${r.adults || 1} 位成人　${r.stay_nights.join("／")} 晚</p>`).join("") + `<p class="muted small">每天自動掃描 ${e(s.schedule.runs_per_day)} 次${s.schedule.promo_months?.length ? `，促銷月（${e(s.schedule.promo_months.join("、"))} 月）${e(s.schedule.promo_runs_per_day)} 次` : ""}</p>`;
    const routeFields = s.routes.map(r => [r.label, `${r.return_origin ? `${r.origin} → ${r.destination}／${r.return_origin} → ${r.origin}` : `${r.origin} ⇄ ${r.destination}`}　${modeText(r)}　${r.adults || 1} 位成人　${r.stay_nights.join("／")} 晚`]);
    const fields = [...routeFields, ["幣別", s.currency], ["行李", s.baggage?.checked_kg > 0 ? `來回各 ${s.baggage.pieces_each_way} 件 ${s.baggage.checked_kg}kg。顯示「不含行李｜含行李」，半價以含行李價判斷` : "只帶手提，總價＝票價"], ["掃描窗口", `後天起至未來 ${s.window.days_ahead} 天（最早 ${s.window.min_lead_days} 天）`], ["立即推播", `≤ 基準 ${s.thresholds.instant * 100}%，或含行李總價 ≤ 好價線（${s.routes.filter(r => r.good_price != null).map(r => `${AIRPORT_ZH[r.destination] || r.label} ${fmtMoney(r.good_price)}`).join("、") || "未設定"}）${s.new_low?.days ? `，或比近 ${s.new_low.days} 天航線最低價再低 ${s.dedupe.min_drop_ratio * 100}%（紀錄滿 ${s.new_low.min_days} 天才開始）` : ""}，Google 驗證（SerpApi 未啟用時為 Travelpayouts 快取價），單次最多 ${s.thresholds.max_instant_per_run ?? 5} 則`], ...(s.airline_sales?.enabled ? [["促銷消息", `${s.airline_sales.airlines.join("、")}：新聞與 PTT 標題有促銷字眼、${s.airline_sales.max_age_hours} 小時內的新消息，每輪合成一則推播`]] : []), ["每日摘要", `≤ 基準 ${s.thresholds.digest * 100}%，${s.digest.hour_local}:00 後首次掃描`], ["基準回看", `${s.routes[0].baseline.lookback_days} 天`], ["SerpAPI 額度", `每日 ${e(q.serpapi_daily_budget)}／每月 ${e(q.serpapi_quota)}，安全額 ${q.monthly_safety}`], ["候選保留", `每次最多 ${q.reserve_for_candidates} 組；${q.reverify_hours} 小時內未降價不重驗`], ["重發條件", `再降 ≥${s.dedupe.min_drop_ratio * 100}% 或超過 ${s.dedupe.cooldown_hours} 小時`], ["排程", `台北 09:17／15:17／21:17／03:17${s.schedule.promo_months?.length ? `；促銷月加跑 00:17／06:17／12:17／18:17` : ""}`]];
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

  function render() { renderHome(); renderSpend(); renderCalendar(); renderRecords(); renderMarket(); renderTeam(); renderSettings(); status(); }
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
        // 離線快取來自 localStorage：同一個 github.io 網域的其他網站也寫得到，含 < > " 的字串一律不採用（我們的資料不會有）。
        try { const saved = JSON.parse(localStorage.getItem(storageKey)); if (coherent(saved) && plainData(saved)) bundle = saved; } catch { /* 尚無快取。 */ }
      }
      if (bundle) { cached = true; render(); }
      else {
        $("connection").textContent = "目前無法讀取資料";
        $("connection").classList.add("offline");
        $("route-cards").innerHTML = '<article class="fare-card"><div class="fare-body"><h2 class="fare-empty-title">暫時無法讀取票價</h2><p class="fare-helper">連線後，點右上角重新整理。</p></div></article>';
      }
    } finally { busy = false; $("refresh").disabled = false; }
  }

  function navigate(event) {
    const requested = location.hash.slice(1) || "home";
    const tab = ["home", "calendar", "records", "market", "settings"].includes(requested) ? requested : "home";
    document.querySelectorAll(".view").forEach(view => { view.hidden = view.id !== tab; });
    document.querySelectorAll("[data-tab]").forEach(link => {
      if (link.dataset.tab === tab) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    document.title = `${({home:"票根", calendar:"出發日曆", records:"好價提醒", market:"票價行情", settings:"設定"})[tab]}｜低飛 LowFly`;
    // 切換分頁（不是第一次載入）時回到頂端並把焦點移到該頁標題，讀屏與鍵盤使用者才知道換頁了（WCAG 2.4.3）。
    if (event) {
      window.scrollTo(0, 0);
      $(`${tab}-title`).setAttribute("tabindex", "-1");
      $(`${tab}-title`).focus({preventScroll: true});
    }
  }
  $("refresh").addEventListener("click", load);
  // 航空 logo 載入失敗改顯示代碼（不用 inline onerror，方便套 CSP）。
  document.addEventListener("error", event => {
    const img = event.target;
    if (img.tagName === "IMG" && img.classList.contains("logo")) {
      const fallback = document.createElement("span");
      fallback.className = "logo-fb";
      fallback.textContent = img.dataset.code;
      img.replaceWith(fallback);
    }
  }, true);
  $("skip-link").addEventListener("click", event => { event.preventDefault(); $("main").focus(); });
  $("deals-only").addEventListener("change", () => bundle && renderCalendar());
  try { $("spend-input").value = localStorage.getItem(spendKey) || ""; } catch { /* 無法讀取本機儲存時預算留空。 */ }
  $("spend-input").addEventListener("input", () => {
    try { localStorage.setItem(spendKey, $("spend-input").value); } catch { /* 無法儲存時只在本次顯示。 */ }
    if (bundle) renderSpend();
  });
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
