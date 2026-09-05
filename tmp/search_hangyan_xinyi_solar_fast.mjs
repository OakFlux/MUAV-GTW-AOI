import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import crypto from 'crypto';

const OUT = path.resolve('out_xinyi_solar_hangyan_fast');
const PDFDIR = path.join(OUT, 'pdfs');
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(PDFDIR, { recursive: true });

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131 Safari/537.36',
  locale: 'zh-CN',
  viewport: { width: 1440, height: 1200 },
});

const relevantRe = /信义光能|信義光能|Xinyi Solar|00968|0968\.HK|0968HK/i;
const reportUrls = new Set(['https://www.hangyan.co/reports/3843608737805763979']);
const searchEvents = [];

async function collectLinks(page, label) {
  const links = await page.locator('a').evaluateAll(nodes => nodes.map(a => ({
    text: (a.textContent || '').trim().replace(/\s+/g, ' '),
    href: a.href || '',
  })).filter(x => x.href));
  for (const link of links) {
    if (/hangyan\.co\/reports\/\d+/.test(link.href) && relevantRe.test(`${link.text} ${link.href}`)) {
      reportUrls.add(link.href.split('?')[0]);
      console.log('REPORT_LINK', label, JSON.stringify(link));
    }
  }
  fs.writeFileSync(path.join(OUT, `${label}_links.json`), JSON.stringify(links, null, 2));
}

const page = await context.newPage();
page.on('response', async response => {
  const u = response.url();
  if (/algolia|search|autocomplete|reports|api/i.test(u)) {
    const h = await response.allHeaders().catch(() => ({}));
    const row = { url: u, status: response.status(), contentType: h['content-type'] || '', contentLength: h['content-length'] || '' };
    if (/json|text/i.test(row.contentType) && Number(row.contentLength || 0) < 3000000) {
      row.preview = (await response.text().catch(() => '')).slice(0, 500000);
    }
    searchEvents.push(row);
  }
});

for (const [idx, u] of [
  'https://www.hangyan.co/reports',
  'https://www.hangyan.co/reports?q=%E4%BF%A1%E4%B9%89%E5%85%89%E8%83%BD',
  'https://www.hangyan.co/search?q=%E4%BF%A1%E4%B9%89%E5%85%89%E8%83%BD',
  'https://www.hangyan.co/?q=%E4%BF%A1%E4%B9%89%E5%85%89%E8%83%BD',
].entries()) {
  console.log('OPEN_SEARCH', u);
  await page.goto(u, { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(e => console.log('GOTO_ERROR', String(e)));
  await page.waitForTimeout(3500);
  await collectLinks(page, `url_${idx}`);
  fs.writeFileSync(path.join(OUT, `url_${idx}.html`), await page.content().catch(() => ''));
  fs.writeFileSync(path.join(OUT, `url_${idx}.txt`), await page.locator('body').innerText().catch(() => ''));
}

await page.goto('https://www.hangyan.co/reports', { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => {});
await page.waitForTimeout(3000);
const inputs = page.locator('input[type="search"], .aa-Input');
const n = await inputs.count();
console.log('INPUTS', n);
for (let i = 0; i < n; i++) {
  const input = inputs.nth(i);
  if (!(await input.isVisible().catch(() => false))) continue;
  for (const query of ['信义光能', '00968', '0968.HK', 'Xinyi Solar']) {
    try {
      await input.fill('');
      await input.fill(query);
      await page.waitForTimeout(5000);
      await collectLinks(page, `autocomplete_${i}_${Buffer.from(query).toString('hex')}`);
      fs.writeFileSync(path.join(OUT, `autocomplete_${i}_${Buffer.from(query).toString('hex')}.html`), await page.content());
      await page.screenshot({ path: path.join(OUT, `autocomplete_${i}_${Buffer.from(query).toString('hex')}.png`), fullPage: true }).catch(() => {});
      await input.press('Enter').catch(() => {});
      await page.waitForTimeout(3500);
      await collectLinks(page, `entered_${i}_${Buffer.from(query).toString('hex')}`);
      await page.goto('https://www.hangyan.co/reports', { waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => {});
      await page.waitForTimeout(1500);
    } catch (e) {
      console.log('INPUT_ERROR', i, query, String(e));
    }
  }
}

const eventText = JSON.stringify(searchEvents);
for (const m of eventText.matchAll(/https?:\\?\/\\?\/www\.hangyan\.co\\?\/reports\\?\/(\d+)/g)) {
  const contextText = eventText.slice(Math.max(0, m.index - 1500), Math.min(eventText.length, m.index + 2500));
  if (relevantRe.test(contextText)) reportUrls.add(`https://www.hangyan.co/reports/${m[1]}`);
}
for (const m of eventText.matchAll(/(?:report[s]?[_-]?id|objectID)[^0-9]{0,20}(\d{12,})/gi)) {
  const contextText = eventText.slice(Math.max(0, m.index - 1500), Math.min(eventText.length, m.index + 2500));
  if (relevantRe.test(contextText)) reportUrls.add(`https://www.hangyan.co/reports/${m[1]}`);
}
fs.writeFileSync(path.join(OUT, 'search_network.json'), JSON.stringify(searchEvents, null, 2));
console.log('REPORT_URLS', JSON.stringify([...reportUrls]));

const manifest = [];
const seenPdf = new Set();
for (const reportUrl of [...reportUrls]) {
  const report = await context.newPage();
  const pdfUrls = new Set();
  report.on('response', async response => {
    const u = response.url();
    const h = await response.allHeaders().catch(() => ({}));
    if (/\.pdf(?:\?|$)/i.test(u) || /application\/pdf/i.test(h['content-type'] || '')) pdfUrls.add(u);
  });
  console.log('OPEN_REPORT', reportUrl);
  try {
    const nav = await report.goto(reportUrl, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await report.waitForTimeout(4500);
    const html = await report.content();
    const text = await report.locator('body').innerText().catch(() => '');
    const title = await report.title().catch(() => '');
    const metas = await report.locator('meta').evaluateAll(ms => Object.fromEntries(ms.map(m => [m.getAttribute('property') || m.getAttribute('name') || '', m.getAttribute('content') || '']).filter(x => x[0]))).catch(() => ({}));
    for (const m of html.matchAll(/https?:\/\/[^"'<>\s]+\.pdf(?:\?[^"'<>\s]*)?/gi)) pdfUrls.add(m[0].replace(/&amp;/g, '&'));
    const anchors = await report.locator('a').evaluateAll(as => as.map(a => ({ text:(a.textContent||'').trim(), href:a.href }))).catch(() => []);
    for (const a of anchors) if (/\.pdf(?:\?|$)/i.test(a.href)) pdfUrls.add(a.href);
    fs.writeFileSync(path.join(OUT, `report_${reportUrl.split('/').pop()}.html`), html);
    fs.writeFileSync(path.join(OUT, `report_${reportUrl.split('/').pop()}.txt`), text);
    console.log('REPORT_META', reportUrl, nav?.status(), title, JSON.stringify(metas).slice(0,3500), 'PDFS', JSON.stringify([...pdfUrls]));
    if (!relevantRe.test(`${title}\n${text}\n${JSON.stringify(metas)}`)) {
      console.log('SKIP_NOT_RELEVANT', reportUrl);
      await report.close();
      continue;
    }
    for (const pdfUrl of pdfUrls) {
      if (seenPdf.has(pdfUrl)) continue;
      seenPdf.add(pdfUrl);
      try {
        const resp = await context.request.get(pdfUrl, { timeout: 90000, headers: { Referer: reportUrl, 'User-Agent': 'Mozilla/5.0' } });
        const body = await resp.body();
        const ct = resp.headers()['content-type'] || '';
        console.log('PDF_FETCH', resp.status(), ct, body.length, pdfUrl);
        if (resp.status() !== 200 || body.length < 50000 || body.slice(0,5).toString() !== '%PDF-') continue;
        const sha = crypto.createHash('sha256').update(body).digest('hex');
        const rid = reportUrl.split('/').pop();
        const fileName = `${rid}_${sha.slice(0,12)}.pdf`;
        fs.writeFileSync(path.join(PDFDIR, fileName), body);
        manifest.push({ reportUrl, reportId: rid, pageTitle: title, meta: metas, pdfUrl, fileName, bytes: body.length, sha256: sha, bodyTextPreview: text.slice(0,5000) });
      } catch (e) {
        console.log('PDF_FETCH_ERROR', pdfUrl, String(e));
      }
    }
  } catch (e) {
    console.log('REPORT_ERROR', reportUrl, String(e));
  }
  await report.close();
}

fs.writeFileSync(path.join(OUT, 'report_urls.json'), JSON.stringify([...reportUrls], null, 2));
fs.writeFileSync(path.join(OUT, 'manifest.json'), JSON.stringify(manifest, null, 2));
console.log('DONE', 'reports', reportUrls.size, 'pdfs', manifest.length);
await browser.close();
