import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const out = 'out_huayan_report_viewers';
fs.rmSync(out, { recursive: true, force: true });
fs.mkdirSync(out, { recursive: true });

const targets = [
  ['fx_5435007', 'https://www.fxbaogao.com/view?id=5435007'],
  ['fx_5497229', 'https://www.fxbaogao.com/view?id=5497229'],
  ['fx_5587624', 'https://www.fxbaogao.com/view?id=5587624'],
  ['sg_1272177', 'https://www.sgpjbg.com/bgdown/1272177.html'],
];
const interesting = /(pdf|download|report|document|attachment|file|oss|image|viewer|api|docx|1272177|5435007|5497229|5587624)/i;
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131 Safari/537.36',
  viewport: { width: 1440, height: 1200 },
  locale: 'zh-CN',
});

for (const [name, url] of targets) {
  const page = await context.newPage();
  const events = [];
  page.on('request', req => {
    const u = req.url();
    if (interesting.test(u)) events.push({ t: 'request', method: req.method(), url: u, resourceType: req.resourceType(), postData: req.postData() });
  });
  page.on('response', async resp => {
    const u = resp.url();
    if (!interesting.test(u)) return;
    const h = await resp.allHeaders().catch(() => ({}));
    const item = { t: 'response', status: resp.status(), url: u, contentType: h['content-type'] || '', contentLength: h['content-length'] || '', headers: h };
    if ((item.contentType.includes('json') || item.contentType.includes('text') || item.contentType.includes('javascript')) && Number(item.contentLength || 0) < 1000000) {
      item.preview = (await resp.text().catch(() => '')).slice(0, 50000);
    }
    events.push(item);
  });
  console.log('VISIT', name, url);
  try {
    const r = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 90000 });
    console.log('NAV', name, r?.status(), page.url());
    await page.waitForTimeout(15000);
    for (const txt of ['点击免费查看完整报告','继续阅读','免费查看','预览','下载PDF','查看全文']) {
      const loc = page.getByText(txt, { exact: false }).first();
      if (await loc.count().catch(() => 0)) {
        try { await loc.click({ timeout: 3000 }); console.log('CLICK', name, txt); await page.waitForTimeout(8000); } catch {}
      }
    }
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await page.waitForTimeout(5000);
    fs.writeFileSync(path.join(out, `${name}.html`), await page.content());
    fs.writeFileSync(path.join(out, `${name}.txt`), await page.locator('body').innerText().catch(() => ''));
    await page.screenshot({ path: path.join(out, `${name}.png`), fullPage: true }).catch(() => {});
    const dom = await page.evaluate(() => ({
      url: location.href,
      title: document.title,
      anchors: [...document.querySelectorAll('a')].map((a,i) => ({i, text:(a.innerText||'').trim(), href:a.href, outer:a.outerHTML.slice(0,2000)})),
      images: [...document.images].map((im,i) => ({i, src:im.src, currentSrc:im.currentSrc, alt:im.alt, w:im.naturalWidth, h:im.naturalHeight, outer:im.outerHTML.slice(0,2000)})),
      embeds: [...document.querySelectorAll('iframe,embed,object')].map((e,i) => ({i, src:e.src||e.data||'', outer:e.outerHTML.slice(0,3000)})),
      scripts: [...document.scripts].map((s,i) => ({i,src:s.src,text:(s.textContent||'').slice(0,10000)})),
      storage: {local:{...localStorage}, session:{...sessionStorage}},
    }));
    fs.writeFileSync(path.join(out, `${name}_dom.json`), JSON.stringify(dom, null, 2));
  } catch (e) {
    console.log('ERR', name, String(e));
  }
  fs.writeFileSync(path.join(out, `${name}_network.json`), JSON.stringify(events, null, 2));
  console.log('EVENTS', name, events.length);
  await page.close();
}

// Fetch public JS assets referenced by known pages to reveal API routes.
const assets = [
  ['fx_app_v1.js','https://static.fxbaogao.com/detail_source/js/app-v1.js'],
  ['sg_page','https://www.sgpjbg.com/bgdown/1272177.html'],
];
for (const [name,url] of assets) {
  try {
    const r = await context.request.get(url, { timeout: 60000 });
    const b = await r.body();
    fs.writeFileSync(path.join(out,name),b);
    console.log('ASSET',name,r.status(),b.length,r.headers()['content-type']);
  } catch(e) { console.log('ASSET_ERR',name,String(e)); }
}
await browser.close();
