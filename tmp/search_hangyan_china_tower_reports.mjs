import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import crypto from 'crypto';

const OUT = path.resolve('out_china_tower_hangyan_search');
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

const reportUrls = new Set([
  'https://www.hangyan.co/reports/3485236846772881072',
  'https://www.hangyan.co/reports/3429851902681023749',
]);
const searchEvents = [];

async function collectLinks(page, label) {
  const links = await page.locator('a').evaluateAll(nodes => nodes.map(a => ({
    text: (a.textContent || '').trim().replace(/\s+/g, ' '),
    href: a.href || '',
  })).filter(x => x.href));
  for (const link of links) {
    if (/hangyan\.co\/reports\/\d+/.test(link.href) && /中国铁塔|China Tower|00788|0788/i.test(link.text)) {
      reportUrls.add(link.href.split('?')[0]);
      console.log('REPORT_LINK', label, JSON.stringify(link));
    }
  }
  fs.writeFileSync(path.join(OUT, `${label}_links.json`), JSON.stringify(links, null, 2));
}

// Search through the site's public autocomplete UI and common URL variants.
const searchPage = await context.newPage();
searchPage.on('response', async response => {
  const u = response.url();
  if (/algolia|search|autocomplete|reports|api/i.test(u)) {
    const h = await response.allHeaders().catch(() => ({}));
    const row = { url: u, status: response.status(), contentType: h['content-type'] || '', contentLength: h['content-length'] || '' };
    if (/json|text/i.test(row.contentType) && Number(row.contentLength || 0) < 2000000) {
      row.preview = (await response.text().catch(() => '')).slice(0, 200000);
    }
    searchEvents.push(row);
  }
});

const searchUrls = [
  'https://www.hangyan.co/reports',
  'https://www.hangyan.co/reports?q=%E4%B8%AD%E5%9B%BD%E9%93%81%E5%A1%94',
  'https://www.hangyan.co/search?q=%E4%B8%AD%E5%9B%BD%E9%93%81%E5%A1%94',
  'https://www.hangyan.co/?q=%E4%B8%AD%E5%9B%BD%E9%93%81%E5%A1%94',
];
for (let i = 0; i < searchUrls.length; i++) {
  const u = searchUrls[i];
  console.log('OPEN_SEARCH', u);
  await searchPage.goto(u, { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(e => console.log('SEARCH_GOTO_ERR', String(e)));
  await searchPage.waitForTimeout(4000);
  await collectLinks(searchPage, `search_url_${i}`);
  fs.writeFileSync(path.join(OUT, `search_url_${i}.html`), await searchPage.content().catch(() => ''));
  fs.writeFileSync(path.join(OUT, `search_url_${i}.txt`), await searchPage.locator('body').innerText().catch(() => ''));
}

// Exercise autocomplete. Use all visible inputs because mobile/desktop widgets differ.
await searchPage.goto('https://www.hangyan.co/reports', { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => {});
await searchPage.waitForTimeout(3000);
const inputs = searchPage.locator('input[type="search"], .aa-Input');
const nInputs = await inputs.count();
console.log('SEARCH_INPUTS', nInputs);
for (let i = 0; i < nInputs; i++) {
  const input = inputs.nth(i);
  if (!(await input.isVisible().catch(() => false))) continue;
  for (const query of ['中国铁塔', '00788', 'China Tower']) {
    try {
      await input.fill('');
      await input.fill(query);
      await searchPage.waitForTimeout(5000);
      await collectLinks(searchPage, `autocomplete_${i}_${query.replace(/\W/g,'_')}`);
      const body = await searchPage.locator('body').innerText().catch(() => '');
      fs.writeFileSync(path.join(OUT, `autocomplete_${i}_${Buffer.from(query).toString('hex')}.txt`), body);
      await searchPage.screenshot({ path: path.join(OUT, `autocomplete_${i}_${Buffer.from(query).toString('hex')}.png`), fullPage: true }).catch(() => {});
      await input.press('Enter').catch(() => {});
      await searchPage.waitForTimeout(5000);
      console.log('AFTER_ENTER', query, searchPage.url());
      await collectLinks(searchPage, `after_enter_${i}_${query.replace(/\W/g,'_')}`);
      await searchPage.goBack({ waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => {});
      await searchPage.waitForTimeout(2000);
    } catch (e) {
      console.log('AUTOCOMPLETE_ERR', i, query, String(e));
    }
  }
}
fs.writeFileSync(path.join(OUT, 'search_network.json'), JSON.stringify(searchEvents, null, 2));

// Extract report URLs from response payloads as a fallback.
const eventText = JSON.stringify(searchEvents);
for (const m of eventText.matchAll(/https?:\\?\/\\?\/www\.hangyan\.co\\?\/reports\\?\/(\d+)/g)) {
  reportUrls.add(`https://www.hangyan.co/reports/${m[1]}`);
}
for (const m of eventText.matchAll(/(?:report[s]?[_-]?id|objectID)[^0-9]{0,20}(\d{12,})/gi)) {
  reportUrls.add(`https://www.hangyan.co/reports/${m[1]}`);
}

const manifest = [];
const seenPdf = new Set();
for (const reportUrl of [...reportUrls]) {
  const page = await context.newPage();
  const pdfUrls = new Set();
  page.on('response', async response => {
    const u = response.url();
    const h = await response.allHeaders().catch(() => ({}));
    if (/\.pdf(?:\?|$)/i.test(u) || /application\/pdf/i.test(h['content-type'] || '')) pdfUrls.add(u);
  });
  console.log('OPEN_REPORT', reportUrl);
  let status = null;
  try {
    const response = await page.goto(reportUrl, { waitUntil: 'domcontentloaded', timeout: 60000 });
    status = response?.status() || null;
    await page.waitForTimeout(5000);
    const html = await page.content();
    const text = await page.locator('body').innerText().catch(() => '');
    const title = await page.title().catch(() => '');
    fs.writeFileSync(path.join(OUT, `report_${reportUrl.split('/').pop()}.html`), html);
    fs.writeFileSync(path.join(OUT, `report_${reportUrl.split('/').pop()}.txt`), text);
    for (const m of html.matchAll(/https?:\/\/[^"'<>\s]+\.pdf(?:\?[^"'<>\s]*)?/gi)) pdfUrls.add(m[0].replace(/&amp;/g, '&'));
    const metas = await page.locator('meta').evaluateAll(ms => Object.fromEntries(ms.map(m => [m.getAttribute('property') || m.getAttribute('name') || '', m.getAttribute('content') || '']).filter(x => x[0]))).catch(() => ({}));
    const anchors = await page.locator('a').evaluateAll(as => as.map(a => ({text:(a.textContent||'').trim(),href:a.href}))).catch(() => []);
    for (const a of anchors) if (/\.pdf(?:\?|$)/i.test(a.href)) pdfUrls.add(a.href);
    console.log('REPORT_META', reportUrl, status, title, JSON.stringify(metas).slice(0,3000), 'PDFS', [...pdfUrls]);
    const relevant = /中国铁塔|China Tower|00788|0788/i.test(`${title}\n${text}\n${JSON.stringify(metas)}`);
    if (!relevant) {
      console.log('SKIP_NOT_RELEVANT', reportUrl);
      await page.close();
      continue;
    }
    for (const pdfUrl of pdfUrls) {
      if (seenPdf.has(pdfUrl)) continue;
      seenPdf.add(pdfUrl);
      try {
        const pdfResp = await context.request.get(pdfUrl, { timeout: 90000, headers: { Referer: reportUrl, 'User-Agent': 'Mozilla/5.0' } });
        const body = await pdfResp.body();
        const ct = pdfResp.headers()['content-type'] || '';
        console.log('PDF_FETCH', pdfResp.status(), ct, body.length, pdfUrl);
        if (pdfResp.status() !== 200 || body.length < 50000 || body.slice(0,5).toString() !== '%PDF-') continue;
        const sha = crypto.createHash('sha256').update(body).digest('hex');
        const rid = reportUrl.split('/').pop();
        const fileName = `${rid}_${sha.slice(0,12)}.pdf`;
        fs.writeFileSync(path.join(PDFDIR, fileName), body);
        manifest.push({ reportUrl, reportId: rid, pageTitle: title, status, pdfUrl, fileName, bytes: body.length, sha256: sha, bodyTextPreview: text.slice(0,3000), meta: metas });
      } catch (e) {
        console.log('PDF_FETCH_ERR', pdfUrl, String(e));
      }
    }
  } catch (e) {
    console.log('REPORT_ERR', reportUrl, String(e));
  }
  await page.close();
}

fs.writeFileSync(path.join(OUT, 'report_urls.json'), JSON.stringify([...reportUrls], null, 2));
fs.writeFileSync(path.join(OUT, 'manifest.json'), JSON.stringify(manifest, null, 2));
console.log('DONE', 'report_urls', reportUrls.size, 'pdfs', manifest.length);
await browser.close();
