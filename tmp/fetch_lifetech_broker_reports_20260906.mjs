import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import crypto from 'crypto';

const OUT = path.resolve('out_lifetech_broker_reports_20260906');
const PDF_DIR = path.join(OUT, 'raw_pdfs');
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(PDF_DIR, { recursive: true });

const knownReports = [
  {
    sourcePage: 'https://www.hangyan.co/reports/3536997837541737746',
    pageId: '3536997837541737746',
    brokerHint: '国金证券',
    dateHint: '2024-12-31',
    titleHint: '心血管器械布局丰富，创新引领增长',
    priority: 100,
  },
  {
    sourcePage: 'https://www.hangyan.co/reports/3630222104332339085',
    pageId: '3630222104332339085',
    brokerHint: '西南证券',
    dateHint: '2025-04-30',
    titleHint: '心血管及外周血管微创介入器械领先者，24年海外收入高增',
    priority: 75,
  },
  {
    sourcePage: 'https://www.hangyan.co/reports/3872055960256120040',
    pageId: '3872055960256120040',
    brokerHint: '西南证券',
    dateHint: '2026-04-09',
    titleHint: '2025年年报点评：外周血管介入业务增长稳健，持续拓展海外业务',
    priority: 65,
  },
];

const discoveredPages = new Map(knownReports.map(x => [x.sourcePage, x]));
const savedHashes = new Set();
const pdfRecords = [];
const pageRecords = [];

function sanitize(value) {
  return String(value || '').replace(/[^A-Za-z0-9._-]+/g, '_').slice(0, 100);
}

async function savePdfBuffer(buffer, url, reportMeta, origin) {
  if (!buffer || buffer.length < 50000 || buffer.slice(0, 5).toString() !== '%PDF-') return null;
  const sha = crypto.createHash('sha256').update(buffer).digest('hex');
  if (savedHashes.has(sha)) return null;
  savedHashes.add(sha);
  const name = `${sanitize(reportMeta?.pageId || 'report')}_${sha.slice(0, 12)}.pdf`;
  const filePath = path.join(PDF_DIR, name);
  fs.writeFileSync(filePath, buffer);
  const item = {
    filePath,
    fileName: name,
    sha256: sha,
    bytes: buffer.length,
    pdfUrl: url,
    sourcePage: reportMeta?.sourcePage || '',
    pageId: reportMeta?.pageId || '',
    brokerHint: reportMeta?.brokerHint || '',
    dateHint: reportMeta?.dateHint || '',
    titleHint: reportMeta?.titleHint || '',
    priority: reportMeta?.priority || 0,
    origin,
  };
  pdfRecords.push(item);
  console.log('PDF_SAVED', JSON.stringify(item));
  return item;
}

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36',
  locale: 'zh-CN',
  viewport: { width: 1440, height: 1100 },
});

// Discover additional Hangyan pages through its public search UI and query routes.
const searchUrls = [
  'https://www.hangyan.co/reports?q=%E5%85%88%E5%81%A5%E7%A7%91%E6%8A%80',
  'https://www.hangyan.co/search?q=%E5%85%88%E5%81%A5%E7%A7%91%E6%8A%80',
  'https://www.hangyan.co/?q=%E5%85%88%E5%81%A5%E7%A7%91%E6%8A%80',
  'https://www.hangyan.co/reports',
];

for (const url of searchUrls) {
  const page = await context.newPage();
  try {
    console.log('SEARCH_OPEN', url);
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForTimeout(5000);
    if (url.endsWith('/reports')) {
      const inputs = page.locator('input');
      const count = await inputs.count();
      for (let i = 0; i < count; i++) {
        const input = inputs.nth(i);
        const ph = (await input.getAttribute('placeholder').catch(() => '')) || '';
        const type = (await input.getAttribute('type').catch(() => '')) || '';
        if (/搜索|search|报告|研报/i.test(ph) || /search/i.test(type)) {
          try {
            await input.fill('先健科技');
            await input.press('Enter');
            await page.waitForTimeout(7000);
            break;
          } catch {}
        }
      }
    }
    const body = await page.locator('body').innerText().catch(() => '');
    const anchors = await page.locator('a').evaluateAll(nodes => nodes.map(a => ({ text: (a.innerText || a.textContent || '').trim(), href: a.href })));
    for (const a of anchors) {
      if (!/\/reports\/\d+/.test(a.href)) continue;
      if (!/先健科技|LifeTech|01302|1302/i.test(`${a.text} ${body.slice(0, 20000)}`)) continue;
      if (!discoveredPages.has(a.href)) {
        const id = (a.href.match(/\/reports\/(\d+)/) || [,''])[1];
        discoveredPages.set(a.href, {
          sourcePage: a.href,
          pageId: id,
          brokerHint: '',
          dateHint: '',
          titleHint: a.text,
          priority: 40,
        });
      }
    }
  } catch (err) {
    console.log('SEARCH_ERR', url, String(err));
  }
  await page.close();
}

console.log('REPORT_PAGES', JSON.stringify([...discoveredPages.values()]));

for (const reportMeta of discoveredPages.values()) {
  const page = await context.newPage();
  const responseCandidates = [];
  const handledUrls = new Set();

  page.on('response', async response => {
    const url = response.url();
    if (handledUrls.has(url)) return;
    const headers = await response.allHeaders().catch(() => ({}));
    const contentType = (headers['content-type'] || '').toLowerCase();
    if (response.status() === 200 && (contentType.includes('application/pdf') || /\.pdf(?:\?|$)/i.test(url))) {
      handledUrls.add(url);
      try {
        const body = await response.body();
        responseCandidates.push({ url, body, origin: 'browser-response' });
      } catch (err) {
        console.log('RESPONSE_BODY_ERR', url, String(err));
      }
    }
  });

  try {
    console.log('REPORT_OPEN', reportMeta.sourcePage);
    const nav = await page.goto(reportMeta.sourcePage, { waitUntil: 'domcontentloaded', timeout: 70000 });
    await page.waitForTimeout(8000);
    const title = await page.title().catch(() => '');
    const meta = await page.evaluate(() => Object.fromEntries([...document.querySelectorAll('meta')].map(m => [m.getAttribute('property') || m.getAttribute('name') || '', m.getAttribute('content') || '']).filter(([k]) => k)));
    const bodyText = await page.locator('body').innerText().catch(() => '');
    const html = await page.content().catch(() => '');
    pageRecords.push({
      ...reportMeta,
      status: nav?.status() || 0,
      finalUrl: page.url(),
      pageTitle: title,
      meta,
      bodyPreview: bodyText.slice(0, 20000),
    });

    // Direct URLs can be present in HTML, scripts or performance entries even if the browser does not display the PDF.
    const directUrls = new Set();
    for (const match of html.matchAll(/https?:\\?\/\\?\/[^"'<>\\\s]+?\.pdf(?:\?[^"'<>\\\s]*)?/gi)) {
      directUrls.add(match[0].replaceAll('\\/', '/').replaceAll('&amp;', '&'));
    }
    const perf = await page.evaluate(() => performance.getEntriesByType('resource').map(x => x.name)).catch(() => []);
    for (const u of perf) if (/\.pdf(?:\?|$)/i.test(u)) directUrls.add(u);
    const anchors = await page.locator('a').evaluateAll(nodes => nodes.map(a => a.href)).catch(() => []);
    for (const u of anchors) if (/\.pdf(?:\?|$)/i.test(u)) directUrls.add(u);

    for (const candidate of responseCandidates) {
      await savePdfBuffer(candidate.body, candidate.url, reportMeta, candidate.origin);
    }
    for (const url of directUrls) {
      if (pdfRecords.some(x => x.pdfUrl === url)) continue;
      try {
        const response = await context.request.get(url, { timeout: 60000, headers: { Referer: reportMeta.sourcePage } });
        const body = await response.body();
        console.log('DIRECT_PDF', response.status(), response.headers()['content-type'] || '', body.length, url);
        if (response.status() === 200) await savePdfBuffer(body, url, reportMeta, 'direct-url');
      } catch (err) {
        console.log('DIRECT_PDF_ERR', url, String(err));
      }
    }

    // Hangyan normally exposes a CDN PDF after client-side initialization. Revisit once and click report/view controls if no PDF was captured.
    if (!pdfRecords.some(x => x.sourcePage === reportMeta.sourcePage)) {
      for (const pattern of [/查看完整报告/i, /免费查看/i, /阅读全文/i, /下载/i]) {
        const loc = page.getByText(pattern).first();
        if (await loc.count().catch(() => 0)) {
          try {
            await loc.click({ timeout: 4000, force: true });
            await page.waitForTimeout(5000);
          } catch {}
        }
      }
      for (const candidate of responseCandidates) {
        await savePdfBuffer(candidate.body, candidate.url, reportMeta, candidate.origin + '-after-click');
      }
    }
  } catch (err) {
    console.log('REPORT_ERR', reportMeta.sourcePage, String(err));
  }
  await page.close();
}

fs.writeFileSync(path.join(OUT, 'page_records.json'), JSON.stringify(pageRecords, null, 2));
fs.writeFileSync(path.join(OUT, 'pdf_records.json'), JSON.stringify(pdfRecords, null, 2));
console.log('FETCH_DONE', 'pages', pageRecords.length, 'pdfs', pdfRecords.length);
await browser.close();
