import { chromium } from 'playwright';
import crypto from 'crypto';
import fs from 'fs';
import path from 'path';

const OUT = path.resolve('out_ascletis_browser_rebuild');
const PDFDIR = path.join(OUT, 'pdfs');
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(PDFDIR, { recursive: true });

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131 Safari/537.36';
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ userAgent: UA, locale: 'zh-CN', viewport: { width: 1440, height: 1200 } });

const reportLinks = new Map();
function addReportLink(href, text, source) {
  try {
    const u = new URL(href, 'https://www.hangyan.co/').href.split('#')[0];
    if (!/https:\/\/www\.hangyan\.co\/reports\/\d+/.test(u)) return;
    const old = reportLinks.get(u) || { href: u, texts: [], sources: [] };
    if (text && !old.texts.includes(text)) old.texts.push(text);
    if (source && !old.sources.includes(source)) old.sources.push(source);
    reportLinks.set(u, old);
  } catch {}
}

async function inspectPage(url, label, clickRead = false) {
  const page = await context.newPage();
  console.log('OPEN', label, url);
  try {
    const response = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 90000 });
    console.log('NAV', label, response?.status(), page.url(), await page.title().catch(() => ''));
    await page.waitForTimeout(8000);
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight)).catch(() => {});
    await page.waitForTimeout(2500);

    const anchors = await page.locator('a').evaluateAll(nodes => nodes.map(a => ({
      text: (a.innerText || a.textContent || '').replace(/\s+/g, ' ').trim(),
      title: a.getAttribute('title') || '',
      href: a.href || a.getAttribute('href') || '',
      outer: a.outerHTML.slice(0, 1500),
    })));
    const body = await page.locator('body').innerText().catch(() => '');
    const html = await page.content().catch(() => '');
    fs.writeFileSync(path.join(OUT, `${label}.html`), html);
    fs.writeFileSync(path.join(OUT, `${label}.txt`), body);
    fs.writeFileSync(path.join(OUT, `${label}_anchors.json`), JSON.stringify(anchors, null, 2));

    for (const a of anchors) {
      const t = `${a.text} ${a.title}`.trim();
      if (/歌礼制药|歌禮製藥|Ascletis|全新GLP-1减重不减肌|口服小分子率先破局|临床数据显示超长半衰期|创新药研发推进顺利/i.test(t)) {
        addReportLink(a.href, t, label);
        console.log('MATCH_LINK', label, JSON.stringify({ text: t, href: a.href }));
      }
      if (clickRead && /阅读研究报告|閱讀研究報告/i.test(t)) {
        addReportLink(a.href, t, label);
        console.log('READ_LINK', label, JSON.stringify({ text: t, href: a.href }));
      }
    }

    // Exercise the public site search box to discover dynamically returned report links.
    if (label === 'reports_home') {
      const searchInputs = page.locator('input[type="search"]:visible');
      const count = await searchInputs.count().catch(() => 0);
      for (let i = 0; i < Math.min(count, 2); i++) {
        const input = searchInputs.nth(i);
        try {
          await input.fill('歌礼制药');
          await page.waitForTimeout(5000);
          const dynamic = await page.locator('a').evaluateAll(nodes => nodes.map(a => ({
            text: (a.innerText || a.textContent || '').replace(/\s+/g, ' ').trim(),
            href: a.href || '',
          })));
          for (const a of dynamic) {
            if (/歌礼制药|歌禮製藥|Ascletis/i.test(a.text)) {
              addReportLink(a.href, a.text, `${label}_search_${i}`);
              console.log('SEARCH_LINK', JSON.stringify(a));
            }
          }
        } catch (e) { console.log('SEARCH_ERR', i, String(e)); }
      }
    }
  } catch (e) {
    console.log('PAGE_ERR', label, String(e));
  }
  await page.close();
}

await inspectPage('https://www.hangyan.co/charts/3601111842144912396', 'chart_dongwu_20250401', true);
await inspectPage('https://www.hangyan.co/charts/3725107781510890977', 'chart_related_20250909', true);
for (let p = 88; p <= 104; p++) {
  await inspectPage(`https://www.hangyan.co/reports?page=${p}`, `reports_page_${p}`);
  if ([...reportLinks.values()].some(x => x.texts.join(' ').includes('口服小分子率先破局'))) break;
}
await inspectPage('https://www.hangyan.co/reports', 'reports_home');
addReportLink('https://www.hangyan.co/reports/3448696034581022433', '国元国际：创新药研发推进顺利，BD合作空间广阔', 'known');

console.log('DISCOVERED_REPORT_LINKS', JSON.stringify([...reportLinks.values()], null, 2));
fs.writeFileSync(path.join(OUT, 'report_links.json'), JSON.stringify([...reportLinks.values()], null, 2));

const saved = [];
const hashes = new Set();
async function savePdf(buffer, sourceUrl, reportUrl, filenameHint, title) {
  if (!buffer || buffer.length < 80000 || buffer.subarray(0,5).toString() !== '%PDF-') return null;
  const sha = crypto.createHash('sha256').update(buffer).digest('hex');
  if (hashes.has(sha)) return null;
  hashes.add(sha);
  const out = path.join(PDFDIR, `${String(saved.length + 1).padStart(2,'0')}_${sha.slice(0,12)}.pdf`);
  fs.writeFileSync(out, buffer);
  const item = { file: out, sourceUrl, reportUrl, filenameHint, title, bytes: buffer.length, sha256: sha };
  saved.push(item);
  console.log('SAVED_PDF', JSON.stringify(item));
  return out;
}

for (const entry of reportLinks.values()) {
  const page = await context.newPage();
  const pdfResponses = [];
  page.on('response', async response => {
    const url = response.url();
    const headers = await response.allHeaders().catch(() => ({}));
    const ct = String(headers['content-type'] || '').toLowerCase();
    if (ct.includes('application/pdf') || /\.pdf(?:[?#]|$)/i.test(url)) {
      try {
        const body = await response.body();
        pdfResponses.push({ url, body: Buffer.from(body) });
      } catch {}
    }
  });
  console.log('OPEN_REPORT', entry.href);
  let title = entry.texts.join(' | ');
  let filenameHint = '';
  try {
    const nav = await page.goto(entry.href, { waitUntil: 'domcontentloaded', timeout: 90000 });
    console.log('REPORT_NAV', nav?.status(), page.url(), await page.title().catch(() => ''));
    await page.waitForTimeout(10000);
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight / 2)).catch(() => {});
    await page.waitForTimeout(3000);
    title = (await page.title().catch(() => title)) || title;
    filenameHint = await page.locator('[data-native-pdf-filename-value]').first().getAttribute('data-native-pdf-filename-value').catch(() => '') || '';
    const srcs = await page.locator('iframe,embed').evaluateAll(nodes => nodes.map(n => n.src || n.getAttribute('src') || '').filter(Boolean)).catch(() => []);
    const html = await page.content().catch(() => '');
    const matches = html.match(/https?:[^"'<>\s]+\.pdf(?:\?[^"'<>\s]*)?/gi) || [];
    const candidates = [...new Set([...srcs, ...matches].map(x => x.replace(/&amp;/g,'&')))];
    for (const candidate of candidates) {
      try {
        const r = await context.request.get(candidate, { timeout: 60000, headers: { Referer: entry.href, Accept: 'application/pdf,*/*' } });
        const body = Buffer.from(await r.body());
        await savePdf(body, candidate, entry.href, filenameHint, title);
      } catch (e) { console.log('DIRECT_PDF_ERR', candidate, String(e)); }
    }
    for (const item of pdfResponses) {
      await savePdf(item.body, item.url, entry.href, filenameHint, title);
    }
  } catch (e) {
    console.log('REPORT_ERR', entry.href, String(e));
  }
  await page.close();
}

fs.writeFileSync(path.join(OUT, 'saved_pdfs.json'), JSON.stringify(saved, null, 2));
await browser.close();
console.log('DONE', saved.length);
