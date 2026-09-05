import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const OUT = path.resolve('out_huayan_bocom_research');
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(OUT, { recursive: true });

const root = 'https://research.bocomgroup.com/';
const ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36';

async function saveFetch(url, name) {
  try {
    const r = await fetch(url, { headers: { 'User-Agent': ua, 'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8' }, redirect: 'follow' });
    const b = Buffer.from(await r.arrayBuffer());
    fs.writeFileSync(path.join(OUT, name), b);
    console.log('FETCH', r.status, r.headers.get('content-type'), b.length, r.url);
    return { status: r.status, ct: r.headers.get('content-type') || '', bytes: b.length, url: r.url, text: b.toString('utf8') };
  } catch (e) {
    console.log('FETCH_ERR', url, String(e));
    return null;
  }
}

const rootFetch = await saveFetch(root, 'root.html');
const scriptUrls = new Set();
if (rootFetch) {
  for (const m of rootFetch.text.matchAll(/<script[^>]+src=["']([^"']+)["']/gi)) {
    scriptUrls.add(new URL(m[1], rootFetch.url).href);
  }
  console.log('ROOT_SCRIPTS', JSON.stringify([...scriptUrls]));
}

const jsResults = [];
let jsIndex = 0;
for (const url of [...scriptUrls]) {
  const item = await saveFetch(url, `script_${jsIndex++}.js`);
  if (!item) continue;
  const contexts = [];
  for (const pat of [/api/gi, /report/gi, /download/gi, /\.pdf/gi, /search/gi, /login/gi, /document/gi, /attachment/gi]) {
    let count = 0;
    for (const m of item.text.matchAll(pat)) {
      contexts.push(item.text.slice(Math.max(0, m.index - 350), Math.min(item.text.length, m.index + 900)));
      if (++count >= 30) break;
    }
  }
  const urls = [...new Set(item.text.match(/https?:\/\/[^"'`\\\s<>]+/g) || [])];
  const paths = [...new Set([...item.text.matchAll(/["'](\/[^"']*(?:api|report|download|pdf|search|file|attachment)[^"']*)["']/gi)].map(m => m[1]))];
  jsResults.push({ url, status: item.status, bytes: item.bytes, contexts, urls, paths });
  console.log('JS', url, item.bytes, 'paths', JSON.stringify(paths.slice(0,200)), 'urls', JSON.stringify(urls.filter(x => /api|report|download|pdf|file/i.test(x)).slice(0,100)));
}
fs.writeFileSync(path.join(OUT, 'js_results.json'), JSON.stringify(jsResults, null, 2));

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ userAgent: ua, locale: 'zh-CN', acceptDownloads: true });
const page = await context.newPage();
const events = [];
const downloads = [];

page.on('response', async response => {
  const url = response.url();
  let headers = {};
  try { headers = await response.allHeaders(); } catch {}
  const ct = headers['content-type'] || '';
  if (/api|report|search|pdf|download|attachment|file|document|login/i.test(`${url} ${ct}`)) {
    const row = { status: response.status(), url, ct, len: headers['content-length'] || '' };
    if (/json|text|javascript/i.test(ct)) {
      try { row.preview = (await response.text()).slice(0, 12000); } catch {}
    }
    events.push(row);
    console.log('RESPONSE', JSON.stringify(row).slice(0,16000));
  }
});
page.on('requestfailed', request => {
  const row = { failed: true, url: request.url(), error: request.failure()?.errorText || '' };
  events.push(row); console.log('FAILED', JSON.stringify(row));
});
page.on('download', async download => {
  const suggested = download.suggestedFilename();
  const dest = path.join(OUT, `download_${Date.now()}_${suggested}`);
  try { await download.saveAs(dest); } catch {}
  downloads.push({ suggested, dest, failure: await download.failure().catch(() => null) });
  console.log('DOWNLOAD', suggested, dest);
});

try {
  await page.goto(root, { waitUntil: 'domcontentloaded', timeout: 90000 });
} catch (e) { console.log('GOTO_ERR', String(e)); }
await page.waitForTimeout(8000);
console.log('PAGE', page.url(), await page.title().catch(() => ''));

async function snapshot(label) {
  const text = await page.locator('body').innerText().catch(() => '');
  const html = await page.content().catch(() => '');
  fs.writeFileSync(path.join(OUT, `${label}.txt`), text);
  fs.writeFileSync(path.join(OUT, `${label}.html`), html);
  await page.screenshot({ path: path.join(OUT, `${label}.png`), fullPage: true }).catch(() => {});
  const anchors = await page.locator('a').evaluateAll(nodes => nodes.map(a => ({text:(a.textContent||'').trim(), href:a.href, target:a.target}))).catch(() => []);
  const inputs = await page.locator('input,textarea').evaluateAll(nodes => nodes.map((n,i)=>({i, type:n.type, name:n.name, placeholder:n.placeholder, value:n.value, outer:n.outerHTML.slice(0,1000)}))).catch(() => []);
  const buttons = await page.locator('button,[role="button"]').evaluateAll(nodes => nodes.map((n,i)=>({i,text:(n.textContent||'').trim(),outer:n.outerHTML.slice(0,1000)}))).catch(() => []);
  fs.writeFileSync(path.join(OUT, `${label}_controls.json`), JSON.stringify({anchors,inputs,buttons}, null, 2));
  console.log('SNAPSHOT', label, 'text', text.slice(0,5000).replace(/\n/g,' | '), 'inputs', JSON.stringify(inputs), 'buttons', JSON.stringify(buttons.slice(0,50)));
}
await snapshot('initial');

// Only interact with public search controls. Do not attempt authentication.
const inputs = page.locator('input');
const count = await inputs.count().catch(() => 0);
for (let i = 0; i < count; i++) {
  const el = inputs.nth(i);
  const type = await el.getAttribute('type').catch(() => '');
  const placeholder = await el.getAttribute('placeholder').catch(() => '');
  const name = await el.getAttribute('name').catch(() => '');
  if (/text|search|^$/i.test(type || '') && /search|搜索|keyword|query|股票|报告|title/i.test(`${placeholder} ${name}`)) {
    try {
      await el.fill('华沿机器人');
      await el.press('Enter');
      await page.waitForTimeout(7000);
      console.log('SEARCHED_WITH_INPUT', i, page.url());
      await snapshot(`search_input_${i}`);
    } catch (e) { console.log('SEARCH_INPUT_ERR', i, String(e)); }
  }
}

// Click visibly public search buttons once when available.
for (const pattern of [/搜索/i, /Search/i, /查询/i]) {
  const loc = page.getByText(pattern).first();
  if (await loc.count().catch(() => 0)) {
    try {
      await loc.click({ timeout: 5000 });
      await page.waitForTimeout(7000);
      console.log('CLICK_SEARCH', pattern.toString(), page.url());
      await snapshot('after_search_click');
      break;
    } catch (e) { console.log('CLICK_SEARCH_ERR', String(e)); }
  }
}

// Try direct, human-readable search URL patterns only (no protected API bypass).
const directUrls = [
  `${root}search?keyword=${encodeURIComponent('华沿机器人')}`,
  `${root}search?query=${encodeURIComponent('华沿机器人')}`,
  `${root}?keyword=${encodeURIComponent('华沿机器人')}`,
  `${root}?search=${encodeURIComponent('1021')}`,
];
for (let i=0;i<directUrls.length;i++) {
  try {
    const p = await context.newPage();
    await p.goto(directUrls[i], { waitUntil:'domcontentloaded', timeout:45000 });
    await p.waitForTimeout(4000);
    const text = await p.locator('body').innerText().catch(()=> '');
    const html = await p.content().catch(()=> '');
    fs.writeFileSync(path.join(OUT, `direct_${i}.txt`), text);
    fs.writeFileSync(path.join(OUT, `direct_${i}.html`), html);
    console.log('DIRECT', i, p.url(), await p.title().catch(()=>''), text.slice(0,2500).replace(/\n/g,' | '));
    await p.close();
  } catch(e) { console.log('DIRECT_ERR', i, String(e)); }
}

const resources = await page.evaluate(() => performance.getEntriesByType('resource').map(r => r.name)).catch(() => []);
let storage = {};
try { storage = await page.evaluate(() => ({local:{...localStorage}, session:{...sessionStorage}, cookies:document.cookie})); } catch {}
fs.writeFileSync(path.join(OUT, 'network.json'), JSON.stringify({events, resources, downloads, storage}, null, 2));

await context.close();
await browser.close();
console.log('READY', OUT);
