import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import crypto from 'crypto';

const OUT = path.resolve('out_xinyi_solar_hangyan_known_all');
const PDFDIR = path.join(OUT, 'pdfs');
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(PDFDIR, { recursive: true });

const targets = [
  ['2024_bocom', 'https://www.hangyan.co/reports/3402974878104552641'],
  ['2025_guoyuan', 'https://www.hangyan.co/reports/3541189723936523517'],
  ['2025_guosheng', 'https://www.hangyan.co/reports/3693579618444379624'],
  ['2026_guojin', 'https://www.hangyan.co/reports/3843608737805763979'],
];

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131 Safari/537.36',
  locale: 'zh-CN',
  viewport: { width: 1440, height: 1100 },
});

const manifest = [];
const seenSha = new Set();
for (const [label, reportUrl] of targets) {
  const page = await context.newPage();
  const pdfUrls = new Set();
  page.on('response', async response => {
    const u = response.url();
    const headers = await response.allHeaders().catch(() => ({}));
    const ct = headers['content-type'] || '';
    if (/\.pdf(?:\?|$)/i.test(u) || /application\/pdf/i.test(ct) || /cdn\.hangyan\.co\/documents\//i.test(u)) {
      pdfUrls.add(u);
      console.log('PDF_RESPONSE', label, response.status(), ct, u);
    }
  });
  console.log('OPEN', label, reportUrl);
  try {
    const nav = await page.goto(reportUrl, { waitUntil: 'domcontentloaded', timeout: 90000 });
    await page.waitForTimeout(7000);
    const html = await page.content();
    const text = await page.locator('body').innerText().catch(() => '');
    const title = await page.title().catch(() => '');
    const metas = await page.locator('meta').evaluateAll(ms => Object.fromEntries(ms.map(m => [m.getAttribute('property') || m.getAttribute('name') || '', m.getAttribute('content') || '']).filter(x => x[0]))).catch(() => ({}));
    for (const m of html.matchAll(/https?:\/\/[^"'<>\s]+\.pdf(?:\?[^"'<>\s]*)?/gi)) {
      pdfUrls.add(m[0].replace(/&amp;/g, '&'));
    }
    const anchors = await page.locator('a').evaluateAll(as => as.map(a => ({ text:(a.textContent||'').trim(), href:a.href }))).catch(() => []);
    for (const a of anchors) if (/\.pdf(?:\?|$)/i.test(a.href)) pdfUrls.add(a.href);
    fs.writeFileSync(path.join(OUT, `${label}.html`), html);
    fs.writeFileSync(path.join(OUT, `${label}.txt`), text);
    fs.writeFileSync(path.join(OUT, `${label}_meta.json`), JSON.stringify({ title, metas, pdfUrls:[...pdfUrls], navStatus:nav?.status() || null }, null, 2));
    await page.screenshot({ path: path.join(OUT, `${label}.png`), fullPage: true }).catch(() => {});
    console.log('META', label, nav?.status(), title, JSON.stringify(metas).slice(0,3000), 'PDFS', JSON.stringify([...pdfUrls]));

    for (const pdfUrl of pdfUrls) {
      try {
        const resp = await context.request.get(pdfUrl, { timeout: 90000, headers: { Referer: reportUrl, 'User-Agent':'Mozilla/5.0' } });
        const body = await resp.body();
        const ct = resp.headers()['content-type'] || '';
        console.log('FETCH', label, resp.status(), ct, body.length, pdfUrl);
        if (resp.status() !== 200 || body.length < 50000 || body.slice(0,5).toString() !== '%PDF-') continue;
        const sha = crypto.createHash('sha256').update(body).digest('hex');
        if (seenSha.has(sha)) continue;
        seenSha.add(sha);
        const fileName = `${label}_${sha.slice(0,12)}.pdf`;
        fs.writeFileSync(path.join(PDFDIR, fileName), body);
        manifest.push({ label, reportUrl, pageTitle:title, meta:metas, pdfUrl, fileName, bytes:body.length, sha256:sha, textPreview:text.slice(0,5000) });
      } catch (e) {
        console.log('FETCH_ERROR', label, pdfUrl, String(e));
      }
    }
  } catch (e) {
    console.log('PAGE_ERROR', label, String(e));
  }
  await page.close();
}

fs.writeFileSync(path.join(OUT, 'manifest.json'), JSON.stringify(manifest, null, 2));
console.log('DONE', manifest.length);
await browser.close();
