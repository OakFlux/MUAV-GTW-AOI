import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const OUT = path.resolve('out_sinofert_fxbaogao_full_view');
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(OUT, { recursive: true });

const reports = [
  { id: '4439431', label: 'anxin_20240812' },
  { id: '4912455', label: 'xyzq_20250620' },
  { id: '5026697', label: 'sxzq_20250828' },
  { id: '5056484', label: 'xyzq_20250911' },
  { id: '5327100', label: 'essencehk_20260330' },
];

const browser = await chromium.launch({ headless: true });
for (const report of reports) {
  const context = await browser.newContext({
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36',
    locale: 'zh-CN',
    acceptDownloads: true,
  });
  const page = await context.newPage();
  const events = [];
  const downloads = [];

  page.on('response', async (response) => {
    const url = response.url();
    const headers = await response.allHeaders().catch(() => ({}));
    const ct = headers['content-type'] || '';
    if (/pdf|octet|json|report|download|file|oss|image/i.test(`${url} ${ct}`)) {
      const entry = {
        type: 'response',
        status: response.status(),
        url,
        contentType: ct,
        contentLength: headers['content-length'] || '',
      };
      if (/json/i.test(ct)) {
        entry.preview = (await response.text().catch(() => '')).slice(0, 4000);
      }
      events.push(entry);
    }
  });
  page.on('requestfailed', request => {
    events.push({ type: 'requestfailed', url: request.url(), failure: request.failure()?.errorText || '' });
  });
  page.on('download', async download => {
    const suggested = download.suggestedFilename();
    const dest = path.join(OUT, `${report.label}_${suggested}`);
    await download.saveAs(dest).catch(() => {});
    downloads.push({ suggested, dest, failure: await download.failure().catch(() => null) });
  });

  for (const route of [`https://www.fxbaogao.com/detail/${report.id}`, `https://www.fxbaogao.com/view?id=${report.id}`]) {
    console.log('OPEN', route);
    await page.goto(route, { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(err => console.log('GOTOERR', String(err)));
    await page.waitForTimeout(8000);
    console.log('CURRENT', page.url(), 'TITLE', await page.title().catch(() => ''));

    const text = await page.locator('body').innerText().catch(() => '');
    const html = await page.content().catch(() => '');
    fs.writeFileSync(path.join(OUT, `${report.label}_${route.includes('/view') ? 'view' : 'detail'}.txt`), text);
    fs.writeFileSync(path.join(OUT, `${report.label}_${route.includes('/view') ? 'view' : 'detail'}.html`), html);
    await page.screenshot({ path: path.join(OUT, `${report.label}_${route.includes('/view') ? 'view' : 'detail'}.png`), fullPage: true }).catch(() => {});

    const anchors = await page.locator('a').evaluateAll(nodes => nodes.map(a => ({ text: (a.textContent || '').trim(), href: a.href, download: a.download || '' })).filter(x => x.text || x.href)).catch(() => []);
    const buttons = await page.locator('button,[role="button"],.download').evaluateAll(nodes => nodes.map((b, i) => ({ i, text: (b.textContent || '').trim(), cls: b.className || '' })).filter(x => x.text)).catch(() => []);
    fs.writeFileSync(path.join(OUT, `${report.label}_${route.includes('/view') ? 'view' : 'detail'}_controls.json`), JSON.stringify({ anchors, buttons }, null, 2));

    // Click only public/free-view controls. Do not log in or attempt protected downloads.
    for (const pattern of [/免费查看完整报告/i, /点击免费查看完整报告/i, /点击查看原文/i, /阅读全文/i]) {
      const loc = page.getByText(pattern).first();
      if (await loc.count().catch(() => 0)) {
        console.log('CLICK', pattern.toString());
        await loc.click({ timeout: 5000, force: true }).catch(err => console.log('CLICKERR', String(err)));
        await page.waitForTimeout(5000);
        console.log('AFTER CLICK', page.url());
      }
    }
  }

  const resources = await page.evaluate(() => performance.getEntriesByType('resource').map(r => r.name)).catch(() => []);
  fs.writeFileSync(path.join(OUT, `${report.label}_network.json`), JSON.stringify({ events, resources, downloads }, null, 2));
  console.log('REPORT', report.id, 'events', events.length, 'resources', resources.length, 'downloads', downloads.length);
  for (const ev of events.filter(e => /pdf|octet|json|download|report-image/i.test(`${e.url} ${e.contentType}`)).slice(-80)) {
    console.log('EVENT', JSON.stringify(ev).slice(0, 1400));
  }
  await context.close();
}

// Fetch and inspect public JS bundles for endpoint strings.
const jsUrls = [
  'https://static.fxbaogao.com/detail_source/js/app-v1.js',
  'https://static.fxbaogao.com/detail_source/_next/static/chunks/polyfills-0d1b80a048d4787e.js',
];
for (const url of jsUrls) {
  const response = await fetch(url);
  const text = await response.text();
  const name = url.split('/').pop();
  fs.writeFileSync(path.join(OUT, name), text);
  console.log('JS', url, response.status, text.length);
  for (const re of [/https?:\/\/[^"'`\\ ]+/g, /\/[A-Za-z0-9_?=&.{}:\/-]*(?:api|download|report|file|pdf)[A-Za-z0-9_?=&.{}:\/-]*/gi]) {
    const matches = [...new Set(text.match(re) || [])].filter(x => x.length < 500);
    console.log('JS_MATCHES', name, JSON.stringify(matches.slice(0, 150)));
  }
}

await browser.close();
console.log('READY', OUT);
