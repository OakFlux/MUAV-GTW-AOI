import { chromium } from 'playwright';
import crypto from 'crypto';
import fs from 'fs';
import path from 'path';

const OUT = path.resolve('out_cssc_defense_20260907');
const PDFDIR = path.join(OUT, 'raw_pdfs');
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(PDFDIR, { recursive: true });

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';
const targets = [
  {
    key: 'zheshang_20240608_deep',
    url: 'https://www.hangyan.co/reports/3386969413495293759',
    expectedTitle: '中船集团旗下“A+H”平台，受益船舶景气上行、竞争格局改善',
  },
  {
    key: 'ccbi_20250303_initiation',
    url: 'https://www.hangyan.co/reports/3584289384419034920',
    expectedTitle: '顺风启航',
  },
];

const browser = await chromium.launch({ headless: true });
const saved = [];
const hashes = new Set();

function normalizeUrl(value) {
  return String(value || '')
    .replace(/\\u0026/g, '&')
    .replace(/\\u003[dD]/g, '=')
    .replace(/\\u003[fF]/g, '?')
    .replace(/\\u002[fF]/g, '/')
    .replace(/\\\//g, '/')
    .replace(/&amp;/g, '&')
    .replace(/[\\"'<>),;]+$/g, '');
}

function isPdf(buf) {
  return buf && buf.length > 50000 && buf.subarray(0, 5).toString() === '%PDF-';
}

async function savePdf(buf, label, sourceUrl) {
  if (!isPdf(buf)) return null;
  const digest = crypto.createHash('sha256').update(buf).digest('hex');
  if (hashes.has(digest)) return null;
  hashes.add(digest);
  const safe = label.replace(/[^A-Za-z0-9_.-]+/g, '_').slice(0, 150);
  const file = path.join(PDFDIR, `${safe}_${digest.slice(0, 12)}.pdf`);
  fs.writeFileSync(file, buf);
  const item = { file, label, sourceUrl, bytes: buf.length, sha256: digest };
  saved.push(item);
  console.log('SAVED_PDF', JSON.stringify(item));
  return file;
}

for (const target of targets) {
  const context = await browser.newContext({
    userAgent: UA,
    locale: 'zh-CN',
    acceptDownloads: true,
    viewport: { width: 1440, height: 1200 },
  });
  const page = await context.newPage();
  const events = [];
  const candidateUrls = new Set();

  page.on('response', async response => {
    const url = normalizeUrl(response.url());
    const headers = await response.allHeaders().catch(() => ({}));
    const ct = String(headers['content-type'] || '').toLowerCase();
    if (/pdf|download|document|attachment|report/i.test(`${url} ${ct}`)) {
      events.push({ type: 'response', status: response.status(), url, contentType: ct, contentLength: headers['content-length'] || '' });
    }
    if (ct.includes('application/pdf') || /\.pdf(?:[?#]|$)/i.test(url)) {
      try {
        const body = await response.body();
        await savePdf(body, `${target.key}_response`, url);
      } catch (e) {
        events.push({ type: 'response_pdf_error', url, error: String(e) });
      }
    }
  });

  page.on('download', async download => {
    try {
      const tempPath = await download.path();
      if (tempPath && fs.existsSync(tempPath)) {
        await savePdf(fs.readFileSync(tempPath), `${target.key}_download_${download.suggestedFilename()}`, download.url());
      }
    } catch (e) {
      events.push({ type: 'download_error', error: String(e) });
    }
  });

  console.log('OPEN', target.key, target.url);
  try {
    const nav = await page.goto(target.url, { waitUntil: 'domcontentloaded', timeout: 90000 });
    console.log('PAGE', target.key, nav?.status(), page.url(), await page.title().catch(() => ''));
    await page.waitForTimeout(9000);

    for (const pattern of [/下载报告/i, /下载PDF/i, /免费下载/i, /查看全文/i, /阅读全文/i, /点击下载/i, /下载/i]) {
      const locator = page.getByText(pattern).first();
      if (await locator.count().catch(() => 0)) {
        try {
          console.log('CLICK', target.key, String(pattern));
          await locator.click({ timeout: 5000, force: true });
          await page.waitForTimeout(7000);
        } catch (e) {
          events.push({ type: 'click_error', pattern: String(pattern), error: String(e) });
        }
      }
    }

    for (const fraction of [0.25, 0.5, 0.75, 1]) {
      await page.evaluate(f => window.scrollTo(0, document.body.scrollHeight * f), fraction).catch(() => {});
      await page.waitForTimeout(1800);
    }

    const html = await page.content().catch(() => '');
    const text = await page.locator('body').innerText().catch(() => '');
    fs.writeFileSync(path.join(OUT, `${target.key}.html`), html);
    fs.writeFileSync(path.join(OUT, `${target.key}.txt`), text);
    await page.screenshot({ path: path.join(OUT, `${target.key}.png`), fullPage: true }).catch(() => {});

    const dom = await page.evaluate(() => ({
      attrs: [...document.querySelectorAll('a,iframe,embed,object,img,source')].flatMap(el =>
        ['href','src','data','data-src','data-url','data-file','currentSrc','srcset']
          .map(key => el[key] || el.getAttribute?.(key) || '')
          .filter(Boolean)
      ),
      resources: performance.getEntriesByType('resource').map(r => r.name),
      scripts: [...document.scripts].map(s => s.src || s.textContent || '').filter(Boolean),
    })).catch(() => ({ attrs: [], resources: [], scripts: [] }));

    const combined = [html, text, ...dom.attrs, ...dom.resources, ...dom.scripts].join('\n');
    const urls = combined.match(/https?:[^"'\\\s<>]+/g) || [];
    for (const raw of urls) {
      const url = normalizeUrl(raw);
      if (/\.pdf(?:[?#]|$)|cdn\.hangyan\.co\/documents|download/i.test(url)) candidateUrls.add(url);
    }

    for (const url of candidateUrls) {
      try {
        const response = await context.request.get(url, {
          timeout: 60000,
          headers: { Referer: target.url, Accept: 'application/pdf,application/octet-stream,*/*' },
        });
        const body = Buffer.from(await response.body());
        const ct = String(response.headers()['content-type'] || '');
        events.push({ type: 'probe', status: response.status(), url, contentType: ct, bytes: body.length });
        await savePdf(body, `${target.key}_probe`, url);
      } catch (e) {
        events.push({ type: 'probe_error', url, error: String(e) });
      }
    }
  } catch (e) {
    events.push({ type: 'target_error', error: String(e) });
    console.log('TARGET_ERR', target.key, String(e));
  }

  fs.writeFileSync(path.join(OUT, `${target.key}_events.json`), JSON.stringify(events, null, 2));
  await context.close();
}

fs.writeFileSync(path.join(OUT, 'saved_pdfs.json'), JSON.stringify(saved, null, 2));
console.log('DONE_SAVED', saved.length);
await browser.close();
