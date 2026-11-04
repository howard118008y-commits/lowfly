(function (root) {
  "use strict";
  const weekdays = "日一二三四五六";
  function fmtDate(value) {
    const date = new Date(value.slice(0, 10) + "T12:00:00+08:00");
    return `${date.getUTCMonth() + 1}/${date.getUTCDate()}（${weekdays[date.getUTCDay()]}）`;
  }
  function roundHalfAway(value) { return Math.sign(value) * Math.floor(Math.abs(value) + 0.5 + 1e-9); }
  function fmtMoney(value) { return value == null ? "尚無報價" : `NT$ ${roundHalfAway(Number(value)).toLocaleString("en-US")}`; }
  function fmtPct(ratio) {
    if (ratio == null) return "尚無基準";
    const percent = roundHalfAway((ratio - 1) * 100);
    return `${percent >= 0 ? "+" : ""}${percent}%`;
  }
  function ratioClass(ratio, price) {
    if (price == null || ratio == null) return "rnone";
    if (ratio <= .5) return "r50";
    if (ratio <= .7) return "r70";
    if (ratio <= .85) return "r85";
    if (ratio <= 1) return "r100";
    return "rhigh";
  }
  function escapeHTML(value) {
    return String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"}[c]));
  }
  function safeURL(value) {
    try { const url = new URL(value); return url.protocol === "https:" ? url.href : ""; }
    catch { return ""; }
  }
  function relativeTime(value, now = Date.now()) {
    const minutes = Math.max(0, Math.floor((now - Date.parse(value)) / 60000));
    if (minutes < 1) return "剛剛更新";
    if (minutes < 60) return `${minutes} 分鐘前`;
    if (minutes < 1440) return `${Math.floor(minutes / 60)} 小時前`;
    return `${Math.floor(minutes / 1440)} 天前`;
  }
  const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
  const records = value => Array.isArray(value) && value.every(object);
  function validDataDocument(name, data) {
    if (!object(data) || typeof data.generated_at !== "string" || !data.generated_at) return false;
    switch (name) {
      case "summary": return records(data.routes);
      case "pairs": return records(data.pairs);
      case "history": return object(data.series);
      case "alerts": return records(data.alerts);
      default: return false;
    }
  }
  function coherent(bundle) {
    if (!object(bundle) || !["summary", "pairs", "history", "alerts"].every(k => validDataDocument(k, bundle[k]))) return false;
    return new Set(Object.values(bundle).map(d => d.generated_at)).size === 1;
  }
  const api = {fmtDate, fmtMoney, fmtPct, ratioClass, escapeHTML, safeURL, relativeTime, validDataDocument, coherent};
  root.LowFly = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
