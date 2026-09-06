import { chromium } from 'playwright';
import crypto from 'crypto';
import fs from 'fs';
import path from 'path';

const OUT = path.resolve('out_ascletis_resolved');
const PDFDIR = path.join(OUT, 'pdfs');
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(PDFDIR, { recursive: true });

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36';
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ userAgent: UA, locale: 'zh-CN', viewport: { width: 1440, height: 1200 } });
const results = [];
const savedHashes = new Set();

async function savePdf(buf, meta) {
  if (!buf || buf.length < 50000 || buf.subarray(0,5).toString() !== '%PDF-') return;
  const sha = crypto.createHash('sha256').update(buf).digest('hex');
  if (savedHashes.has(sha)) return;
  savedHashes.add(sha);
  const file = path.join(PDFDIR, `${String(results.length+1).padStart(2,'0')}_${sha.slice(0,12)}.pdf`);
  fs.writeFileSync(file, buf);
  const row = { ...meta, file, bytes: buf.length, sha256: sha };
  results.push(row);
  console.log('SAVED', JSON.stringify(row));
}

async function visitAndSaveReport(page, sourceLabel) {
  await page.waitForTimeout(9000);
  const reportUrl = page.url();
  const pageTitle = await page.title().catch(() => '');
  const filenameHint = await page.locator('[data-native-pdf-filename-value]').first().getAttribute('data-native-pdf-filename-value').catch(() => '') || '';
  const sources = await page.locator('iframe,embed').evaluateAll(nodes => nodes.map(n => n.src || n.getAttribute('src') || '').filter(Boolean)).catch(() => []);
  const html = await page.content().catch(() => '');
  for (const m of html.matchAll(/https?:[^"'<>\s]+\.pdf(?:\?[^"'<>\s]*)?/gi)) sources.push(m[0].replace(/&amp;/g,'&'));
  for (const u of [...new Set(sources)].filter(u => /^https?:/i.test(u))) {
    try {
      const r = await context.request.get(u, { timeout: 60000, headers: { Referer: reportUrl, Accept: 'application/pdf,*/*' } });
      const buf = Buffer.from(await r.body());
      await savePdf(buf, { sourceLabel, reportUrl, pageTitle, filenameHint, pdfUrl: u });
    } catch (e) { console.log('PDFERR', u, String(e)); }
  }
  fs.writeFileSync(path.join(OUT, `${sourceLabel}_report.html`), html);
  fs.writeFileSync(path.join(OUT, `${sourceLabel}_report.txt`), await page.locator('body').innerText().catch(() => ''));
}

async function clickProtected(sourceUrl, targetPattern, label) {
  const page = await context.newPage();
  const events = [];
  page.on('request', req => {
    if (/protected|link|report/i.test(req.url())) events.push({ type:'request', method:req.method(), url:req.url(), postData:req.postData() });
  });
  page.on('response', async resp => {
    if (/protected|link|report/i.test(resp.url())) {
      const h = await resp.allHeaders().catch(() => ({}));
      const ev = { type:'response', status:resp.status(), url:resp.url(), ct:h['content-type']||'' };
      if ((ev.ct.includes('json') || ev.ct.includes('text')) && Number(h['content-length']||0) < 100000) ev.preview = (await resp.text().catch(() => '')).slice(0,5000);
      events.push(ev);
    }
  });
  console.log('OPEN_SOURCE', label, sourceUrl);
  await page.goto(sourceUrl, { waitUntil:'domcontentloaded', timeout:90000 });
  await page.waitForTimeout(7000);
  const anchors = await page.locator('a[data-controller="protected-link"]').evaluateAll(nodes => nodes.map((a,i) => ({ i, text:(a.innerText||a.textContent||'').replace(/\s+/g,' ').trim(), token:a.getAttribute('data-protected-link-token-value')||'', outer:a.outerHTML }))).catch(() => []);
  fs.writeFileSync(path.join(OUT, `${label}_protected.json`), JSON.stringify(anchors,null,2));
  console.log('PROTECTED', label, JSON.stringify(anchors));
  let loc = page.locator('a[data-controller="protected-link"]').filter({ hasText: targetPattern }).first();
  if (!(await loc.count())) loc = page.locator('a[data-controller="protected-link"]').first();
  if (!(await loc.count())) {
    console.log('NO_TARGET', label);
    await page.close();
    return;
  }
  const before = page.url();
  console.log('CLICK_TARGET', label, await loc.innerText().catch(()=>''), await loc.getAttribute('data-protected-link-token-value'));
  const popupPromise = context.waitForEvent('page', { timeout:5000 }).catch(() => null);
  await loc.click({ force:true, timeout:10000 }).catch(e => console.log('CLICKERR', label, String(e)));
  const popup = await popupPromise;
  const active = popup || page;
  await active.waitForTimeout(8000);
  console.log('AFTER_CLICK', label, 'before', before, 'after', active.url(), 'title', await active.title().catch(() => ''));
  fs.writeFileSync(path.join(OUT, `${label}_events.json`), JSON.stringify(events,null,2));
  if (/\/reports\/\d+/.test(active.url())) await visitAndSaveReport(active, label);
  else {
    const body = await active.locator('body').innerText().catch(() => '');
    fs.writeFileSync(path.join(OUT, `${label}_after.txt`), body);
    fs.writeFileSync(path.join(OUT, `${label}_after.html`), await active.content().catch(() => ''));
  }
  if (popup) await popup.close();
  await page.close();
}

await clickProtected(
  'https://www.hangyan.co/charts/3601111842144912396',
  '全新GLP-1减重不减肌',
  'dongwu_20250401'
);

// Search endpoint generated by the site itself.
const searchPage = await context.newPage();
const searchUrl = 'https://www.hangyan.co/reports?q=%E6%AD%8C%E7%A4%BC%E5%88%B6%E8%8D%AF';
await searchPage.goto(searchUrl, { waitUntil:'domcontentloaded', timeout:90000 });
await searchPage.waitForTimeout(9000);
const searchAnchors = await searchPage.locator('a[data-controller="protected-link"]').evaluateAll(nodes => nodes.map((a,i) => ({ i, text:(a.innerText||a.textContent||'').replace(/\s+/g,' ').trim(), token:a.getAttribute('data-protected-link-token-value')||'', outer:a.outerHTML }))).catch(() => []);
fs.writeFileSync(path.join(OUT,'search_protected.json'),JSON.stringify(searchAnchors,null,2));
fs.writeFileSync(path.join(OUT,'search.html'),await searchPage.content());
fs.writeFileSync(path.join(OUT,'search.txt'),await searchPage.locator('body').innerText().catch(()=>''));
console.log('SEARCH_PROTECTED', JSON.stringify(searchAnchors));
await searchPage.close();

const desired = [
  ['东方证券_20251228', '口服小分子率先破局'],
  ['东吴证券_20250909', '临床数据显示超长半衰期'],
  ['国元国际_20240902', '创新药研发推进顺利'],
];
for (const [label, text] of desired) {
  await clickProtected(searchUrl, text, label);
}

fs.writeFileSync(path.join(OUT,'saved.json'),JSON.stringify(results,null,2));
await browser.close();
console.log('DONE', results.length);
