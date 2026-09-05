import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const OUT = path.resolve('out_xyzq_huayan_research');
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36',
  locale: 'zh-CN',
  viewport: { width: 1440, height: 1200 },
  acceptDownloads: true,
});
const page = await context.newPage();
const events = [];
page.on('response', async response => {
  const url = response.url();
  const headers = await response.allHeaders().catch(() => ({}));
  const ct = headers['content-type'] || '';
  if (/cms|research|report|search|list|pdf|file|download|api/i.test(`${url} ${ct}`)) {
    const ev = { status: response.status(), url, contentType: ct, length: headers['content-length'] || '' };
    if (/json|text|javascript|html/i.test(ct)) ev.preview = (await response.text().catch(() => '')).slice(0, 50000);
    events.push(ev);
    console.log('RESPONSE', JSON.stringify(ev).slice(0, 52000));
  }
});
page.on('request', request => {
  if (/cms|research|report|search|list|api/i.test(request.url())) console.log('REQUEST', request.method(), request.url(), request.postData() || '');
});
page.on('download', async download => {
  const name = download.suggestedFilename();
  const dest = path.join(OUT, name || 'download.bin');
  await download.saveAs(dest).catch(() => {});
  console.log('DOWNLOAD', name, dest, await download.failure().catch(() => null));
});

const url = 'https://www.xyzq.com.hk/detail/research';
await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 70000 }).catch(e => console.log('GOTO_ERR', String(e)));
await page.waitForTimeout(12000);
console.log('LOADED', page.url(), await page.title().catch(() => ''));
let body = await page.locator('body').innerText().catch(() => '');
let html = await page.content().catch(() => '');
fs.writeFileSync(path.join(OUT, 'initial.txt'), body);
fs.writeFileSync(path.join(OUT, 'initial.html'), html);
await page.screenshot({ path: path.join(OUT, 'initial.png'), fullPage: true }).catch(() => {});
console.log('BODY', body.length, body.slice(0, 12000).replace(/\n/g, ' | '));

const controls = await page.locator('input,button,a,[role="button"]').evaluateAll(nodes => nodes.map((n,i)=>({i,tag:n.tagName,text:(n.textContent||'').trim(),href:n.href||'',placeholder:n.placeholder||'',type:n.type||'',cls:n.className||''})).filter(x=>x.text||x.href||x.placeholder)).catch(()=>[]);
fs.writeFileSync(path.join(OUT, 'controls.json'), JSON.stringify(controls,null,2));
console.log('CONTROLS', JSON.stringify(controls).slice(0,40000));

// Search only through visible public search controls.
for (let i=0;i<await page.locator('input').count();i++) {
  const loc=page.locator('input').nth(i);
  const ph=(await loc.getAttribute('placeholder').catch(()=>''))||'';
  if (/搜|检索|关键|公司|股票|research|search/i.test(ph)) {
    console.log('FILL',i,ph);
    await loc.fill('华沿机器人').catch(()=>{});
    await loc.press('Enter').catch(()=>{});
    await page.waitForTimeout(7000);
  }
}
for (const pattern of [/搜索/i,/检索/i,/查询/i]) {
  const loc=page.getByText(pattern,{exact:false}).first();
  if (await loc.count().catch(()=>0) && await loc.isVisible().catch(()=>false)) {
    console.log('CLICK_SEARCH',pattern.toString());
    await loc.click({force:true,timeout:5000}).catch(()=>{});
    await page.waitForTimeout(5000);
  }
}
body = await page.locator('body').innerText().catch(() => '');
html = await page.content().catch(() => '');
fs.writeFileSync(path.join(OUT, 'after.txt'), body);
fs.writeFileSync(path.join(OUT, 'after.html'), html);
await page.screenshot({ path: path.join(OUT, 'after.png'), fullPage: true }).catch(() => {});
console.log('AFTER_BODY', body.length, body.slice(0, 18000).replace(/\n/g, ' | '));

const resources = await page.evaluate(()=>performance.getEntriesByType('resource').map(r=>r.name)).catch(()=>[]);
fs.writeFileSync(path.join(OUT,'network.json'),JSON.stringify({events,resources},null,2));

// Fetch public JSON API responses exposed by the route, and public PDF links within them.
const pdfUrls = new Set();
for (const ev of events) {
  const text = ev.preview || '';
  for (const m of text.matchAll(/https?:\\?\/\\?\/[^"'<>\\\s]+?\.pdf(?:\?[^"'<>\\\s]*)?/gi)) {
    pdfUrls.add(m[0].replace(/\\\//g,'/').replace(/\\u0026/g,'&'));
  }
  for (const m of text.matchAll(/"file_path"\s*:\s*"([^"]+\.pdf[^"]*)"/gi)) pdfUrls.add(m[1].replace(/\\\//g,'/'));
}
console.log('PDF_URLS',JSON.stringify([...pdfUrls]).slice(0,50000));
let n=0;
for (const pdfUrl of pdfUrls) {
  try {
    const r=await context.request.get(pdfUrl,{timeout:40000});
    const data=await r.body();
    console.log('PDF_FETCH',r.status(),r.headers()['content-type']||'',data.length,pdfUrl);
    if(r.status()===200 && data.length>80000 && data.subarray(0,5).toString()==='%PDF-') fs.writeFileSync(path.join(OUT,`pdf_${n++}.pdf`),data);
  } catch(e) { console.log('PDF_ERR',pdfUrl,String(e)); }
}

await context.close();
await browser.close();
console.log('READY',OUT);
