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
  const bundle = {summary:{generated_at:"a",routes:[]},pairs:{generated_at:"a",pairs:[]},history:{generated_at:"a",series:{}},alerts:{generated_at:"a",alerts:[]}};
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

async function appHarness(overrides = {}, offline = false, extra = {}) {
  const html = fs.readFileSync(path.join(__dirname, '../docs/index.html'), 'utf8');
  const makeElement = () => ({innerHTML:'', textContent:'', hidden:false, checked:false, dataset:{}, attributes:{},
    classList:{add(){},remove(){},toggle(){}}, setAttribute(k,v){this.attributes[k]=v;}, removeAttribute(k){delete this.attributes[k];},
    addEventListener(){}, querySelectorAll(){return [];}, showModal(){}, close(){}});
  const nodes = Object.fromEntries([...html.matchAll(/id="([^"]+)"/g)].map(m=>[m[1],makeElement()]));
  const payload = Object.fromEntries(['summary','pairs','history','alerts'].map(name=>[name,JSON.parse(fs.readFileSync(path.join(__dirname,`fixtures/empty_data/${name}.json`)))]));
  Object.assign(payload.summary, overrides);
  Object.assign(payload, extra);
  if (extra.alerts) payload.alerts.generated_at = payload.summary.generated_at;
  const document = {getElementById(id){assert.ok(nodes[id],`缺少頁面元素 ${id}`);return nodes[id];},
    querySelectorAll(selector){return selector === '.view' ? ['home','calendar','records','settings'].map(id=>Object.assign(nodes[id],{id})) : [];}};
  const context = {document,window:{LowFly:U,LOWFLY_CONFIG:{owner:'',repo:'',branch:'main'},addEventListener(){}},
    location:{hash:'',hostname:'example.test',pathname:'/lowfly/',href:'https://example.test/lowfly/'},navigator:{onLine:!offline},
    localStorage:{setItem(){},getItem(){return null;}},setInterval(){},AbortSignal,URL,console,
    fetch:async url=>{if(offline)throw Error('offline');return {ok:true,headers:{get(){return null;}},json:async()=>payload[url.match(/(\w+)\.json/)[1]]};}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../docs/app.js'),'utf8'),context);
  await new Promise(resolve=>setImmediate(resolve));
  return nodes;
}

const patchRoutes = (routes, patch) => routes.map(r => ({...r, ...(patch[r.id] || {})}));
const baseRoutes = () => JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/empty_data/summary.json'))).routes;

const ticketItem = (extra = {}) => ({pair_key:'HKG:2026-11-27_2026-12-01',outbound:'2026-11-27',inbound:'2026-12-01',nights:4,price:9709,total:9709,fare:7829,bag_fee:1880,bag_estimated:false,ratio:.82,verified:true,airline:'酷航',airline_code:'TR',flight_no:'TR 866',depart_time:'14:25',arrive_time:'18:30',return_depart_time:'22:25',origin_airport:'TPE',destination_airport:'NRT',duration_to:185,duration_back:250,google_flights_url:'https://www.google.com/travel/flights',...extra});
const withItem = (item, baseline) => appHarness({routes:patchRoutes(baseRoutes(),{HKG:{cheapest_verified:item,...(baseline?{baseline:{...baseRoutes()[0].baseline,...baseline}}:{})}})});

test('首頁依優先序疊出每條航線一張票根，色條用設定的航線色', async () => {
  const nodes=await appHarness();
  const html=nodes['route-cards'].innerHTML;
  assert.equal((html.match(/<article class="ticket/g)||[]).length,3);
  const order=['桃園 ⇄ 香港','桃園 ⇄ 東京','桃園 ⇄ 澳門'].map(label=>html.indexOf(label));
  assert.ok(order.every(i=>i>=0)&&order[0]<order[1]&&order[1]<order[2]);
  const codes=[...html.matchAll(/<div class="code">([A-Z]{3})<\/div>/g)].map(m=>m[1]);
  assert.deepEqual(codes,['TPE','HKG','TPE','TYO','TPE','MFM']);
  assert.deepEqual([...html.matchAll(/--route:(#[0-9A-F]{6})/g)].map(m=>m[1]),['#B0124F','#23468F','#007A4D']);
  assert.equal((html.match(/等待第一筆票價/g)||[]).length,3);
  assert.match(html,/基準累積中 0\/15/);
  assert.match(nodes['home-title'].textContent,/還在等第一筆票價/);
});

test('有班次資料時畫時間軸、航空公司與價格條碼；沒有半價時開頭寫真實狀態', async () => {
  const nodes=await withItem(ticketItem());
  const html=nodes['route-cards'].innerHTML;
  assert.match(html,/酷航 TR 866/);
  assert.match(html,/pics\.avs\.io\/48\/48\/TR\.png/);
  assert.match(html,/<div class="code">NRT<\/div>/);
  assert.match(html,/3h05m/);
  assert.match(html,/桃園 <b>14:25<\/b>/);
  assert.match(html,/東京成田 <b>18:30<\/b>/);
  assert.match(html,/去 11\/27 週五/);
  assert.match(html,/回 12\/1 週二 22:25 起飛/);
  assert.match(html,/4 晚/);
  assert.match(html,/去訂票/);
  assert.doesNotMatch(html,/去訂票[^<]*[→↗]|看其他日期[^<]*[→↗]/);
  assert.doesNotMatch(html,/undefined|null|\(\)|（）/);
  assert.doesNotMatch(html,/class="stamp"/);
  assert.match(nodes['home-title'].textContent,/三條航線都還沒有好價票/);
});

test('舊資料缺航班欄位時不畫時間軸，也不出現 undefined', async () => {
  const old=ticketItem({airline:'UO',airline_code:null,flight_no:null,depart_time:null,arrive_time:null,return_depart_time:null,origin_airport:null,destination_airport:null,duration_to:null,duration_back:null});
  const html=(await withItem(old))['route-cards'].innerHTML;
  assert.match(html,/<div class="code">TPE<\/div>/);
  assert.match(html,/去 11\/27 週五/);
  assert.doesNotMatch(html,/<b>\d\d:\d\d<\/b>|起飛|3h05m|undefined|null/);
});

test('比例 ≤ 0.5 蓋「半價」印章並成為開頭；沒有基準時寫累積進度而非比例', async () => {
  let nodes=await withItem(ticketItem({price:3980,total:3980,fare:3980,bag_fee:0,ratio:.46}),{value:8652,source:'google'});
  assert.match(nodes['route-cards'].innerHTML,/class="stamp"[^>]*>半價</);
  assert.match(nodes['route-cards'].innerHTML,/比基準低 54%/);
  assert.match(nodes["home-title"].textContent,/^香港有半價票：11\/27 NT\$ 3,980$/);
  nodes=await withItem(ticketItem({ratio:null}),{value:null,source:null,samples:10,min_samples:15});
  assert.match(nodes['route-cards'].innerHTML,/基準累積中 10\/15/);
  assert.doesNotMatch(nodes['route-cards'].innerHTML,/比基準/);
});

test('價格條碼：每個出發日一條，本張票的日期用航線色，沒資料的日子留空', async () => {
  const pairs=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/empty_data/pairs.json')));
  const hkg=pairs.pairs.filter(p=>p.route_id==='HKG');
  hkg[0].price=5000; hkg[3].price=9000; hkg[3].outbound=hkg[3].outbound;   // 不同出發日各一筆
  const days=[...new Set(hkg.map(p=>p.outbound))];
  const nodes=await appHarness({routes:patchRoutes(baseRoutes(),{HKG:{cheapest_verified:ticketItem({outbound:hkg[0].outbound})}})},false,{pairs});
  const bars=nodes['route-cards'].innerHTML.match(/<div class="barcode"[\s\S]*?<\/div>/)[0];
  assert.equal((bars.match(/<i class="bar/g)||[]).length,days.length);
  assert.equal((bars.match(/bar on/g)||[]).length,1);
  assert.ok((bars.match(/bar gap/g)||[]).length>=days.length-2);
});

test('沒有已驗證價時，首頁票根顯示該航線 TP 最低快取價與未驗證說明，不冒充已驗證', async () => {
  const cache=(price,i)=>({pair_key:`HKG:2026-11-0${i}_2026-11-0${i+3}`,outbound:`2026-11-0${i}`,inbound:`2026-11-0${i+3}`,nights:3,price,ratio:price/8000,verified:false,airline:'測試航空',google_flights_url:'https://www.google.com/travel/flights'});
  const routes=patchRoutes(baseRoutes(),{HKG:{cheapest_verified:null,deals:[cache(5200,3),cache(999,2)],baseline:{value:8000,google_low:null,google_high:null,n_ranges:0,lookback_days:45,source:'travelpayouts',samples:20,min_samples:15}}});
  const nodes=await appHarness({routes});
  const html=nodes['route-cards'].innerHTML;
  assert.match(html,/999/);
  assert.match(html,/Travelpayouts 快取價，未經 Google 驗證/);
  assert.match(html,/基準 Travelpayouts 中位數/);
  assert.match(html,/比基準低 88%/);
  assert.doesNotMatch(html,/Google 已驗證/);
  assert.equal((html.match(/等待第一筆票價/g)||[]).length,2);
  assert.match(nodes.deals.innerHTML,/快取價，未經驗證/);
  assert.doesNotMatch(nodes.deals.innerHTML,/999/);
  assert.equal(nodes['deal-section'].hidden,false);
});

test('各航線最低價不重複，其他好價合併分批展開且三條航線日曆各自完整', async () => {
  const fare=(r,i)=>({pair_key:`${r}:2026-11-${10+i}_2026-11-${13+i}`,outbound:`2026-11-${10+i}`,inbound:`2026-11-${13+i}`,nights:3,price:3980+i,ratio:.46,verified:true,airline:'測試航空',google_flights_url:'https://www.google.com/travel/flights'});
  const routes=patchRoutes(baseRoutes(),{MFM:{cheapest_verified:fare('MFM',0),deals:[0,1,2,3,4].map(i=>fare('MFM',i))}});
  const nodes=await appHarness({routes});
  assert.match(nodes['route-cards'].innerHTML,/3,980/);
  assert.equal((nodes.deals.innerHTML.match(/<article/g)||[]).length,2);
  assert.equal((nodes['remaining-deals'].innerHTML.match(/<article/g)||[]).length,2);
  assert.doesNotMatch(nodes.deals.innerHTML,/3,980/);
  assert.equal(nodes['more-deals'].hidden,false);
  assert.equal((nodes.heatmap.innerHTML.match(/data-pair=/g)||[]).length,87*3);
  assert.equal((nodes.heatmap.innerHTML.match(/<section class="route-block">/g)||[]).length,3);
  const h=nodes.heatmap.innerHTML;
  assert.ok(h.indexOf('桃園 ⇄ 香港')<h.indexOf('桃園 ⇄ 東京')&&h.indexOf('桃園 ⇄ 東京')<h.indexOf('桃園 ⇄ 澳門'));
  assert.match(h,/<th scope="col">出發日<\/th><th scope="col">3 晚/);
  assert.match(h,/<th scope="col">出發日<\/th><th scope="col">4 晚<\/th><th scope="col">5 晚<\/th><th scope="col">6 晚/);
});

test('通知頁寫成「桃園→香港 日期 降到 價格（基準）」，設定頁列出所有航線與停留晚數', async () => {
  const alert={pair_key:'MFM:2026-11-14_2026-11-17',route_id:'MFM',route_label:'桃園 ⇄ 澳門',alerted_at:'2026-11-02T09:30:00+08:00',price_at_alert:3980,baseline_at_alert:7500,ratio_at_alert:.53,airline:'長榮航空',latest_price:3980,min_price_after:3980,outbound:'2026-11-14',inbound:'2026-11-17',verdict:'持平'};
  const nodes=await appHarness({},false,{alerts:{alerts:[alert]}});
  assert.match(nodes['alert-list'].innerHTML,/桃園 → 澳門 11\/14–11\/17 降到 NT\$ 3,980（基準 NT\$ 7,500）/);
  const s=nodes['settings-overview'].innerHTML;
  assert.match(s,/桃園 ⇄ 香港[\s\S]*3／4／5 晚[\s\S]*桃園 ⇄ 東京[\s\S]*4／5／6 晚[\s\S]*桃園 ⇄ 澳門[\s\S]*3／4／5 晚/);
  assert.match(s,/每天自動掃描 4 次<\/p>/);
  const promo=await appHarness({schedule:{runs_per_day:4,promo_months:[5,6,11,12],promo_runs_per_day:8}});
  assert.match(promo['settings-overview'].innerHTML,/每天自動掃描 4 次，促銷月（5、6、11、12 月）8 次/);
  assert.match(promo['settings-values'].innerHTML,/03:17；促銷月加跑 00:17／06:17／12:17／18:17/);
});

test('首次離線無資料時在主要票價卡顯示可恢復的錯誤', async () => {
  const nodes=await appHarness({},true);
  assert.match(nodes['route-cards'].innerHTML,/暫時無法讀取票價/);
  assert.match(nodes['route-cards'].innerHTML,/重新整理/);
  assert.equal(nodes.refresh.disabled,false);
});

test('票根兩欄並列不含行李／含行李；含託運單欄；舊資料或不帶託運只顯示一個價格', async () => {
  const fare=(bag,est,fareValue=3000)=>ticketItem({price:3000+bag,total:3000+bag,fare:fareValue,bag_fee:fareValue==null?null:bag,bag_estimated:est,ratio:.9});
  const run=(item,kg)=>appHarness({baggage:{checked_kg:kg,pieces_each_way:1},routes:patchRoutes(baseRoutes(),{HKG:{cheapest_verified:item}})});
  let html=(await run(fare(2000,false),20))['route-cards'].innerHTML;   // UO：票價 3,000＋行李 2,000
  assert.match(html,/不含行李<\/small><div class="fare-price"><small>NT\$<\/small>3,000/);
  assert.match(html,/含行李<\/small><div class="fare-price"><small>NT\$<\/small>5,000/);
  assert.match(html,/20kg 來回</);
  assert.match(html,/半價與好價都以含行李價判斷/);
  assert.doesNotMatch(html,/行李費估算/);
  html=(await run(fare(3000,true),20))['route-cards'].innerHTML;
  assert.match(html,/20kg 來回，行李費估算/);
  html=(await run(fare(0,false),20))['route-cards'].innerHTML;   // 傳統航空含託運：單欄
  assert.match(html,/<small>NT\$<\/small>3,000/);
  assert.match(html,/已含 20kg 託運/);
  assert.doesNotMatch(html,/不含行李|含行李</);
  html=(await run(fare(0,false,null),20))['route-cards'].innerHTML;   // 舊資料 fare 為 null
  assert.match(html,/<small>NT\$<\/small>3,000/);
  assert.doesNotMatch(html,/行李|託運/);
  html=(await run(fare(0,false),0))['route-cards'].innerHTML;   // 不帶託運
  assert.doesNotMatch(html,/行李|託運/);
});

test('票根顯示近 30 天含行李均價與筆數；舊資料沒有均價時不顯示', async () => {
  let nodes=await appHarness({routes:patchRoutes(baseRoutes(),{HKG:{cheapest_verified:ticketItem(),average:{value:7100,samples:5,days:30}}})});
  assert.match(nodes['route-cards'].innerHTML,/近 30 天含行李均價 <b>NT\$ 7,100<\/b>，5 筆/);
  nodes=await withItem(ticketItem());
  assert.doesNotMatch(nodes['route-cards'].innerHTML,/均價/);
});

test('含行李總價 ≤ 好價線蓋「好價」章並成為開頭；優惠須知列在價格下方', async () => {
  const item=ticketItem({price:4200,total:4200,fare:4200,bag_fee:0,ratio:null,notes:['手提＋隨身物品合計 7kg，腰包也算一件','23:25 深夜抵達']});
  const nodes=await appHarness({routes:patchRoutes(baseRoutes(),{HKG:{cheapest_verified:item,good_price:4500}})});
  const html=nodes['route-cards'].innerHTML;
  assert.match(html,/class="stamp"[^>]*>好價</);
  assert.match(nodes['home-title'].textContent,/^香港有好價票：11\/27 NT\$ 4,200$/);
  assert.match(html,/<div class="t-notes"><strong>須知<\/strong><ul><li>手提＋隨身物品合計 7kg，腰包也算一件<\/li><li>23:25 深夜抵達<\/li><\/ul><\/div>/);
  assert.ok(html.indexOf('t-notes')<html.indexOf('去訂票'));
  const plain=(await appHarness({routes:patchRoutes(baseRoutes(),{HKG:{cheapest_verified:{...item,price:4600,total:4600,fare:4600,notes:[]},good_price:4500}})}))['route-cards'].innerHTML;
  assert.doesNotMatch(plain,/class="stamp"|t-notes/);
});
