"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const U = require("../docs/utils.js");

test("日期、金額、折扣與 Telegram 一致", () => {
  assert.equal(U.fmtDate("2026-11-14"), "11/14（六）");
  assert.equal(U.fmtMoney(3980), "NT$ 3,980");
  assert.equal(U.fmtPct(.46), "-54%");
  assert.equal(U.fmtPct(.665), "-34%");
  assert.equal(U.fmtMoney(null), "尚無報價");
});
test("完整六種熱力圖分級與無資料", () => {
  assert.deepEqual([.5,.7,.85,1,1.01].map(r => U.ratioClass(r, 4000)), ["r50","r70","r85","r100","rhigh"]);
  assert.equal(U.ratioClass(null, null), "rnone");
});
test("外部來源 HTML 與連結安全處理", () => {
  assert.equal(U.safeURL("javascript:alert(1)"), "");
  assert.equal(U.safeURL("https://www.google.com/travel/flights"), "https://www.google.com/travel/flights");
  assert.equal(U.escapeHTML('<script>"&'), "&lt;script&gt;&quot;&amp;");
});
test("時間顯示", () => {
  const now = Date.parse("2026-11-02T09:30:00+08:00");
  assert.equal(U.relativeTime("2026-11-02T09:18:00+08:00", now), "12 分鐘前");
  assert.equal(U.relativeTime("2026-11-02T00:18:00+08:00", now), "9 小時前");
});
test("混合批次 JSON 不得覆寫一致快取", () => {
  const bundle = {summary:{generated_at:"a",deals:[]},pairs:{generated_at:"a",pairs:[]},history:{generated_at:"a",series:{}},alerts:{generated_at:"a",alerts:[]}};
  assert.equal(U.coherent(bundle), true);
  bundle.alerts.generated_at = "b";
  assert.equal(U.coherent(bundle), false);
});
test("PWA 路徑與圖示均相對，可部署於 repo 子路徑", () => {
  const root = path.join(__dirname,"../docs");
  const manifest = JSON.parse(fs.readFileSync(path.join(root,"manifest.webmanifest")));
  assert.equal(manifest.start_url, "./");
  assert.equal(manifest.display, "standalone");
  for (const icon of manifest.icons) assert.ok(fs.existsSync(path.join(root,icon.src)));
  const html = fs.readFileSync(path.join(root,"index.html"),"utf8");
  assert.ok(!/(?:href|src)="\//.test(html));
  assert.match(html,/apple-mobile-web-app-capable/);
  assert.match(html,/apple-touch-icon/);
});

function workerHarness() {
  const handlers = {}, stores = new Map();
  const normalize = request => typeof request === "string" ? new URL(request,"https://example.test/repo/").href : request.url;
  const caches = {
    async keys() { return [...stores.keys()]; },
    async delete(key) { return stores.delete(key); },
    async open(key) {
      if (!stores.has(key)) stores.set(key,new Map());
      const store = stores.get(key);
      return {
        async match(request) { return store.get(normalize(request))?.clone(); },
        async put(request,response) { store.set(normalize(request),response.clone()); },
        async addAll(items) { for (const item of items) store.set(normalize(item),new Response("shell")); }
      };
    }
  };
  let fail = false, fetches = 0;
  const scope = "https://example.test/repo/";
  const context = {URL,Response,Headers,AbortSignal,console,caches,
    fetch:async () => { fetches++; if(fail) throw new Error("offline"); return new Response('{"generated_at":"2026-11-02T09:30:00+08:00"}',{headers:{"Content-Type":"application/json"}}); },
    self:{registration:{scope},location:{origin:"https://example.test"},clients:{claim:async()=>{}},skipWaiting:async()=>{},addEventListener:(name,fn)=>handlers[name]=fn}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,"../docs/sw.js"),"utf8"),context);
  return {handlers,caches,setOffline(){fail=true;},get fetches(){return fetches;},async lifecycle(name){let p;handlers[name]({waitUntil:v=>p=v});await p;},async request(url,mode="cors"){let p;handlers.fetch({request:{url,method:"GET",mode},respondWith:v=>p=v});return await p;}};
}
test("Service Worker JSON network-first，斷線回退快取並標示", async () => {
  const h = workerHarness(), url = "https://example.test/repo/data/summary.json";
  let response = await h.request(url);
  assert.equal(response.status,200);
  h.setOffline();
  response = await h.request(url);
  assert.equal(response.headers.get("X-LowFly-Cache"),"offline");
  assert.match(await response.text(),/generated_at/);
  assert.equal(h.fetches,2);
});
test("Service Worker shell cache-first，可離線啟動", async () => {
  const h = workerHarness();
  await h.lifecycle("install");
  h.setOffline();
  const response = await h.request("https://example.test/repo/index.html","navigate");
  assert.equal(await response.text(),"shell");
  assert.equal(h.fetches,0);
});
test("Service Worker 更新只清理此 repo 舊版快取", async () => {
  const h = workerHarness();
  await h.caches.open("lowfly:/repo/:shell-old");
  await h.caches.open("lowfly:/other/:shell-old");
  await h.lifecycle("install");
  await h.lifecycle("activate");
  const keys = await h.caches.keys();
  assert.ok(!keys.includes("lowfly:/repo/:shell-old"));
  assert.ok(keys.includes("lowfly:/other/:shell-old"));
});
test("Service Worker 首次離線沒有資料時回 503", async () => {
  const h = workerHarness();h.setOffline();
  assert.equal((await h.request("https://example.test/repo/data/pairs.json")).status,503);
});
