import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import crypto from 'crypto';

const OUT = path.resolve('out_qunabox_broker_reports_20260906');
const PDFDIR = path.join(OUT, 'pdfs');
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(PDFDIR, { recursive: true });

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131 Safari/537.36',
  locale: 'zh-CN',
  viewport: { width: 1440, height: 1200 },
  acceptDownloads: true,
});

const identityRe = /趣致集团|趣致集團|Qunabox|00917\.HK|00917|0917\.HK/i;
const deepRe = /首次覆盖|首次覆蓋|深度|公司研究|买入|買入|AI互动营销|AI互動營銷|物理AI|营销闭环|營銷閉環|KA客户|KA客戶|AI变现|AI變現/i;
const discoveredPages = new Set([
  'https://www.sdyanbao.com/detail/853466',
  'https://www.sgpjbg.com/baogao/464567.html',
  'https://www.sgpjbg.com/bgdown/464567.html',
  'https://www.fxbaogao.com/detail/5630239',
  'https://www.fxbaogao.com/detail/5630240',
]);
const manifest = [];
const seenPdfUrls = new Set();
const seenHashes = new Set();
const networkLog = [];

function safeName(s) {
  return s.replace(/[^a-zA-Z0-9._-]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 100) || 'file';
}

async function savePdfBuffer(buffer, sourcePage, pdfUrl, label, pageTitle = '') {
  if (!buffer || buffer.length < 50000 || buffer.slice(0,5).toString() !== '%PDF-') return null;
  const sha = crypto.createHash('sha256').update(buffer).digest('hex');
  if (seenHashes.has(sha)) return null;
  seenHashes.add(sha);
  const fileName = `${safeName(label)}_${sha.slice(0,12)}.pdf`;
  fs.writeFileSync(path.join(PDFDIR, fileName), buffer);
  const row = { sourcePage, pdfUrl, fileName, bytes: buffer.length, sha256: sha, pageTitle };
  manifest.push(row);
  console.log('SAVED_PDF', JSON.stringify(row));
  return row;
}

async function fetchPdf(pdfUrl, sourcePage, label, pageTitle = '') {
  if (!pdfUrl || seenPdfUrls.has(pdfUrl)) return;
  seenPdfUrls.add(pdfUrl);
  try {
    const resp = await context.request.get(pdfUrl, {
      timeout: 90000,
      headers: { Referer: sourcePage, 'User-Agent': 'Mozilla/5.0' },
    });
    const body = await resp.body();
    const ct = resp.headers()['content-type'] || '';
    console.log('PDF_FETCH', resp.status(), ct, body.length, pdfUrl);
    await savePdfBuffer(body, sourcePage, pdfUrl, label, pageTitle);
  } catch (e) {
    console.log('PDF_FETCH_ERR', pdfUrl, String(e));
  }
}

async function inspectPage(url, label, clickTexts = []) {
  const page = await context.newPage();
  const pdfUrls = new Set();
  const events = [];
  page.on('response', async response => {
    const u = response.url();
    const h = await response.allHeaders().catch(() => ({}));
    const ct = h['content-type'] || '';
    if (/\.pdf(?:\?|$)/i.test(u) || /application\/pdf/i.test(ct)) pdfUrls.add(u);
    if (/pdf|download|report|document|attachment|file|api|search|algolia|oss|cdn|research/i.test(`${u} ${ct}`)) {
      const row = { url: u, status: response.status(), contentType: ct, contentLength: h['content-length'] || '' };
      if (/json|text|javascript/i.test(ct) && Number(row.contentLength || 0) < 1500000) {
        row.preview = (await response.text().catch(() => '')).slice(0, 100000);
      }
      events.push(row);
      networkLog.push({ page: url, ...row });
    }
  });
  console.log('OPEN', label, url);
  let status = null;
  try {
    const response = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 75000 });
    status = response?.status() || null;
    await page.waitForTimeout(5000);
    for (const text of clickTexts) {
      const loc = page.getByText(text, { exact: false }).first();
      if (await loc.count().catch(() => 0)) {
        try {
          await loc.click({ timeout: 4000, force: true });
          console.log('CLICK', label, text, page.url());
          await page.waitForTimeout(5000);
        } catch (e) { console.log('CLICK_ERR', label, text, String(e)); }
      }
    }
    const html = await page.content();
    const bodyText = await page.locator('body').innerText().catch(() => '');
    const title = await page.title().catch(() => '');
    const metas = await page.locator('meta').evaluateAll(ms => Object.fromEntries(ms.map(m => [m.getAttribute('property') || m.getAttribute('name') || '', m.getAttribute('content') || '']).filter(x => x[0]))).catch(() => ({}));
    const anchors = await page.locator('a').evaluateAll(as => as.map(a => ({text:(a.textContent||'').trim().replace(/\s+/g,' '),href:a.href||'',download:a.download||''}))).catch(() => []);
    const embeds = await page.locator('iframe,embed,object').evaluateAll(es => es.map(e => ({src:e.src||e.data||'',outer:e.outerHTML.slice(0,3000)}))).catch(() => []);
    const scripts = await page.locator('script').evaluateAll(ss => ss.map(s => ({src:s.src||'', text:(s.textContent||'').slice(0,50000)}))).catch(() => []);
    fs.writeFileSync(path.join(OUT, `${safeName(label)}.html`), html);
    fs.writeFileSync(path.join(OUT, `${safeName(label)}.txt`), bodyText);
    fs.writeFileSync(path.join(OUT, `${safeName(label)}_dom.json`), JSON.stringify({url:page.url(),status,title,metas,anchors,embeds,scripts}, null, 2));
    fs.writeFileSync(path.join(OUT, `${safeName(label)}_network.json`), JSON.stringify(events, null, 2));
    await page.screenshot({ path: path.join(OUT, `${safeName(label)}.png`), fullPage: true }).catch(() => {});

    const combined = `${html}\n${JSON.stringify(metas)}\n${JSON.stringify(anchors)}\n${JSON.stringify(embeds)}\n${JSON.stringify(scripts)}`;
    for (const m of combined.matchAll(/https?:\\?\/\\?\/[^"'<>\s\\]+\.pdf(?:\?[^"'<>\s\\]*)?/gi)) {
      pdfUrls.add(m[0].replace(/\\\//g,'/').replace(/&amp;/g,'&'));
    }
    for (const a of anchors) if (/\.pdf(?:\?|$)/i.test(a.href)) pdfUrls.add(a.href);
    for (const e of embeds) if (/\.pdf(?:\?|$)/i.test(e.src)) pdfUrls.add(e.src);

    // Collect report pages discovered in links or response payloads.
    for (const a of anchors) {
      if (/hangyan\.co\/reports\/\d+/.test(a.href) && identityRe.test(`${a.text} ${bodyText}`)) discoveredPages.add(a.href.split('?')[0]);
      if (/fxbaogao\.com\/detail\/\d+/.test(a.href) && identityRe.test(`${a.text} ${bodyText}`)) discoveredPages.add(a.href.split('?')[0]);
      if (/sdyanbao\.com\/detail\/\d+/.test(a.href) && identityRe.test(`${a.text} ${bodyText}`)) discoveredPages.add(a.href.split('?')[0]);
    }
    const eventText = JSON.stringify(events);
    for (const m of eventText.matchAll(/https?:\\?\/\\?\/www\.hangyan\.co\\?\/reports\\?\/(\d+)/g)) discoveredPages.add(`https://www.hangyan.co/reports/${m[1]}`);
    for (const m of eventText.matchAll(/https?:\\?\/\\?\/www\.fxbaogao\.com\\?\/detail\\?\/(\d+)/g)) discoveredPages.add(`https://www.fxbaogao.com/detail/${m[1]}`);

    console.log('PAGE_META', label, status, title, 'identity', identityRe.test(`${title}\n${bodyText}\n${JSON.stringify(metas)}`), 'pdfs', [...pdfUrls]);
    for (const pdfUrl of pdfUrls) await fetchPdf(pdfUrl, url, label, title);
    return { status, title, bodyText, html, metas, anchors, events };
  } catch (e) {
    console.log('PAGE_ERR', label, url, String(e));
    return null;
  } finally {
    await page.close();
  }
}

// 1. Search Hangyan through public search UI and capture autocomplete/API responses.
const searchPage = await context.newPage();
const searchEvents = [];
searchPage.on('response', async response => {
  const u = response.url();
  if (/algolia|search|autocomplete|reports|api/i.test(u)) {
    const h = await response.allHeaders().catch(() => ({}));
    const ct = h['content-type'] || '';
    const row = { url:u, status:response.status(), contentType:ct, contentLength:h['content-length']||'' };
    if (/json|text/i.test(ct) && Number(row.contentLength || 0) < 3000000) row.preview = (await response.text().catch(() => '')).slice(0, 300000);
    searchEvents.push(row);
  }
});
for (const u of [
  'https://www.hangyan.co/reports',
  'https://www.hangyan.co/reports?q=%E8%B6%A3%E8%87%B4%E9%9B%86%E5%9B%A2',
  'https://www.hangyan.co/search?q=%E8%B6%A3%E8%87%B4%E9%9B%86%E5%9B%A2',
  'https://www.hangyan.co/?q=%E8%B6%A3%E8%87%B4%E9%9B%86%E5%9B%A2',
]) {
  console.log('SEARCH_OPEN', u);
  await searchPage.goto(u, { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(e => console.log('SEARCH_GOTO_ERR', String(e)));
  await searchPage.waitForTimeout(4000);
  const links = await searchPage.locator('a').evaluateAll(as => as.map(a => ({text:(a.textContent||'').trim().replace(/\s+/g,' '),href:a.href||''}))).catch(() => []);
  for (const a of links) if (/hangyan\.co\/reports\/\d+/.test(a.href) && identityRe.test(a.text)) discoveredPages.add(a.href.split('?')[0]);
}
await searchPage.goto('https://www.hangyan.co/reports', { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => {});
await searchPage.waitForTimeout(2500);
const inputs = searchPage.locator('input[type="search"], .aa-Input, input[placeholder*="搜索"], input[placeholder*="Search"]');
const inputCount = await inputs.count();
console.log('HANGYAN_INPUTS', inputCount);
for (let i=0;i<inputCount;i++) {
  const input = inputs.nth(i);
  if (!(await input.isVisible().catch(() => false))) continue;
  for (const query of ['趣致集团','00917','Qunabox']) {
    try {
      await input.fill(''); await input.fill(query); await searchPage.waitForTimeout(5000);
      const links = await searchPage.locator('a').evaluateAll(as => as.map(a => ({text:(a.textContent||'').trim().replace(/\s+/g,' '),href:a.href||''}))).catch(() => []);
      for (const a of links) if (/hangyan\.co\/reports\/\d+/.test(a.href) && identityRe.test(`${a.text} ${query}`)) discoveredPages.add(a.href.split('?')[0]);
      fs.writeFileSync(path.join(OUT, `hangyan_autocomplete_${i}_${Buffer.from(query).toString('hex')}.txt`), await searchPage.locator('body').innerText().catch(() => ''));
    } catch (e) { console.log('HANGYAN_INPUT_ERR', i, query, String(e)); }
  }
}
const searchBlob = JSON.stringify(searchEvents);
for (const m of searchBlob.matchAll(/https?:\\?\/\\?\/www\.hangyan\.co\\?\/reports\\?\/(\d+)/g)) discoveredPages.add(`https://www.hangyan.co/reports/${m[1]}`);
for (const m of searchBlob.matchAll(/(?:objectID|report(?:s)?[_-]?id)[^0-9]{0,30}(\d{12,})/gi)) discoveredPages.add(`https://www.hangyan.co/reports/${m[1]}`);
fs.writeFileSync(path.join(OUT, 'hangyan_search_network.json'), JSON.stringify(searchEvents, null, 2));
await searchPage.close();

// 2. Inspect West Bull official research page and capture its public API.
for (const u of ['https://www.westbullsec.com.hk/','https://www.westbullsec.com.hk/research']) {
  const result = await inspectPage(u, `westbull_${safeName(u)}`);
  if (result) {
    const blob = `${result.html}\n${JSON.stringify(result.events)}`;
    for (const m of blob.matchAll(/https?:\\?\/\\?\/[^"'<>\s\\]+\.pdf(?:\?[^"'<>\s\\]*)?/gi)) {
      const pdf = m[0].replace(/\\\//g,'/');
      if (identityRe.test(blob) || deepRe.test(blob)) await fetchPdf(pdf, u, 'westbull_official');
    }
  }
}

// 3. Inspect known pages.
const initialPages = [...discoveredPages];
for (const u of initialPages) {
  await inspectPage(u, `known_${safeName(u)}`, ['立即下载','下载PDF','点击免费查看完整报告','免费查看完整报告','查看全文']);
}

// 4. Inspect all newly discovered report pages.
for (const u of [...discoveredPages]) {
  if (initialPages.includes(u)) continue;
  await inspectPage(u, `discovered_${safeName(u)}`, ['立即下载','下载PDF','点击免费查看完整报告','免费查看完整报告','查看全文']);
}

// 5. Bing searches for exact report titles and broker names, then inspect discovered result pages.
const bingPage = await context.newPage();
for (const q of [
  '趣致集团 00917 券商 研报 PDF',
  '趣致集团 AI互动营销领导者 公司业绩高速增长 PDF',
  '趣致集团 深耕KA客户 加速出海中东 PDF',
  '趣致集团 物理AI构建营销闭环 PDF',
  'Qunabox 00917 research report PDF',
]) {
  const u = `https://www.bing.com/search?q=${encodeURIComponent(q)}`;
  console.log('BING', q);
  await bingPage.goto(u, { waitUntil:'domcontentloaded', timeout:60000 }).catch(() => {});
  await bingPage.waitForTimeout(2500);
  const links = await bingPage.locator('a').evaluateAll(as => as.map(a => ({text:(a.textContent||'').trim().replace(/\s+/g,' '),href:a.href||''}))).catch(() => []);
  for (const a of links) {
    if (!identityRe.test(`${a.text} ${a.href}`) && !deepRe.test(a.text)) continue;
    if (/hangyan\.co\/reports\/\d+|fxbaogao\.com\/detail\/\d+|sdyanbao\.com\/detail\/\d+|sgpjbg\.com\/(?:baogao|bgdown)\/\d+/.test(a.href)) discoveredPages.add(a.href.split('?')[0]);
    if (/\.pdf(?:\?|$)/i.test(a.href)) await fetchPdf(a.href, u, `bing_${safeName(q)}`);
  }
}
await bingPage.close();

for (const u of [...discoveredPages]) {
  const label = `final_${safeName(u)}`;
  const expectedHtml = path.join(OUT, `${label}.html`);
  if (!fs.existsSync(expectedHtml)) await inspectPage(u, label, ['立即下载','下载PDF','点击免费查看完整报告','免费查看完整报告','查看全文']);
}

fs.writeFileSync(path.join(OUT, 'discovered_pages.json'), JSON.stringify([...discoveredPages], null, 2));
fs.writeFileSync(path.join(OUT, 'manifest.json'), JSON.stringify(manifest, null, 2));
fs.writeFileSync(path.join(OUT, 'network_all.json'), JSON.stringify(networkLog, null, 2));
console.log('DONE', 'pages', discoveredPages.size, 'pdfs', manifest.length);
await browser.close();
