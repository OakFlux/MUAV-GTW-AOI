import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const OUT = path.resolve('out_ascletis_20260906');
const PDFDIR = path.join(OUT, 'pdfs');
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(PDFDIR, { recursive: true });

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';
const targets = [
  { name: 'book118_dongwu_deep', url: 'https://max.book118.com/html/2025/0407/7161064025010056.shtm', kind: 'book118' },
  { name: 'reportify_guoyuan_2024', url: 'https://reportify.cn/reports/1028312670044033024', kind: 'reportify' },
  { name: 'fx_dongwu_deep_20250401', url: 'https://www.fxbaogao.com/view?id=4757488', kind: 'fx' },
  { name: 'fx_orient_first_20251228', url: 'https://www.fxbaogao.com/view?id=5205547', kind: 'fx' },
  { name: 'hangyan_guoyuan_20240902', url: 'https://www.hangyan.co/reports/3448696034581022433', kind: 'hangyan' },
];

function normalizeUrl(value) {
  return String(value || '')
    .replace(/\\u0026/g, '&')
    .replace(/\\u003[dD]/g, '=')
    .replace(/\\u003[fF]/g, '?')
    .replace(/\\u002F/g, '/')
    .replace(/\\\//g, '/')
    .replace(/&amp;/g, '&')
    .replace(/[\\"'<>),;]+$/g, '');
}

function isPdfBytes(buf) {
  return buf && buf.length > 50000 && buf.subarray(0, 5).toString() === '%PDF-';
}

function safeName(value) {
  return String(value).replace(/[^A-Za-z0-9_.-]+/g, '_').slice(0, 160);
}

const saved = [];
const hashes = new Set();
async function savePdf(buffer, label, sourceUrl) {
  if (!isPdfBytes(buffer)) return null;
  const crypto = await import('crypto');
  const digest = crypto.createHash('sha256').update(buffer).digest('hex');
  if (hashes.has(digest)) return null;
  hashes.add(digest);
  const file = path.join(PDFDIR, `${safeName(label)}_${digest.slice(0, 12)}.pdf`);
  fs.writeFileSync(file, buffer);
  const item = { file, label, sourceUrl, bytes: buffer.length, sha256: digest };
  saved.push(item);
  console.log('SAVED_PDF', JSON.stringify(item));
  return file;
}

const browser = await chromium.launch({ headless: true });

// Search Reportify's public API first; it often exposes report IDs and signed assets.
const apiQueries = ['歌礼制药', '全新GLP-1减重不减肌', '口服小分子率先破局'];
for (const query of apiQueries) {
  const url = `https://api.reportify.cn/reports?query=${encodeURIComponent(query)}&page_num=1&page_size=50`;
  try {
    const response = await fetch(url, { headers: { 'User-Agent': UA, Accept: 'application/json', Referer: 'https://reportify.cn/' } });
    const text = await response.text();
    fs.writeFileSync(path.join(OUT, `reportify_api_${safeName(query)}.json`), text);
    console.log('REPORTIFY_API', query, response.status, text.length);
    let obj = null;
    try { obj = JSON.parse(text); } catch {}
    const items = Array.isArray(obj?.items) ? obj.items : Array.isArray(obj?.data) ? obj.data : [];
    for (const item of items) {
      const blob = JSON.stringify(item);
      if (!/歌礼制药|Ascletis|01672|1672\.HK/i.test(blob)) continue;
      console.log('REPORTIFY_ITEM', JSON.stringify(item));
      const urls = blob.match(/https?:[^"'\\\s<>]+/g) || [];
      for (const raw of urls) {
        const candidate = normalizeUrl(raw);
        if (!/\.pdf(?:[?#]|$)|url_pdf|download/i.test(candidate)) continue;
        try {
          const r = await fetch(candidate, { headers: { 'User-Agent': UA, Referer: 'https://reportify.cn/' } });
          const buf = Buffer.from(await r.arrayBuffer());
          await savePdf(buf, `reportify_api_${item.report_id || item.id || 'item'}`, candidate);
        } catch (e) { console.log('REPORTIFY_API_PDF_ERR', String(e), candidate); }
      }
    }
  } catch (e) {
    console.log('REPORTIFY_API_ERR', query, String(e));
  }
}

for (const target of targets) {
  const context = await browser.newContext({ userAgent: UA, locale: 'zh-CN', acceptDownloads: true, viewport: { width: 1440, height: 1200 } });
  const page = await context.newPage();
  const events = [];
  const candidateUrls = new Set();

  page.on('response', async response => {
    const url = normalizeUrl(response.url());
    const headers = await response.allHeaders().catch(() => ({}));
    const ct = String(headers['content-type'] || '').toLowerCase();
    if (/pdf|report|download|document|file|attachment|preview/i.test(`${url} ${ct}`)) {
      events.push({ type: 'response', status: response.status(), url, contentType: ct, contentLength: headers['content-length'] || '' });
    }
    if (ct.includes('application/pdf') || /\.pdf(?:[?#]|$)/i.test(url)) {
      try {
        const body = await response.body();
        await savePdf(body, `${target.name}_response`, url);
      } catch {}
    }
  });
  page.on('download', async download => {
    try {
      const temp = await download.path();
      if (temp && fs.existsSync(temp)) {
        const body = fs.readFileSync(temp);
        await savePdf(body, `${target.name}_download_${download.suggestedFilename()}`, download.url());
      }
    } catch (e) { console.log('DOWNLOAD_ERR', target.name, String(e)); }
  });

  console.log('OPEN', target.name, target.url);
  try {
    const nav = await page.goto(target.url, { waitUntil: 'domcontentloaded', timeout: 90000 });
    console.log('PAGE', target.name, nav?.status(), page.url(), await page.title().catch(() => ''));
    await page.waitForTimeout(10000);

    // Public/free controls only. Do not authenticate or bypass a paywall.
    const patterns = target.kind === 'book118'
      ? [/原文免费试下载/i, /免费试下载/i, /试下载/i]
      : target.kind === 'fx'
        ? [/点击免费查看完整报告/i, /免费查看完整报告/i]
        : [/查看全文/i, /阅读全文/i];
    for (const pattern of patterns) {
      const locator = page.getByText(pattern).first();
      if (await locator.count().catch(() => 0)) {
        try {
          console.log('CLICK', target.name, String(pattern));
          await locator.click({ timeout: 8000, force: true });
          await page.waitForTimeout(8000);
        } catch (e) { console.log('CLICK_ERR', target.name, String(e)); }
      }
    }

    // Scroll through the page so lazy-loaded viewers request their assets.
    for (const fraction of [0.25, 0.5, 0.75, 1]) {
      await page.evaluate(f => window.scrollTo(0, document.body.scrollHeight * f), fraction).catch(() => {});
      await page.waitForTimeout(2500);
    }

    const html = await page.content().catch(() => '');
    const text = await page.locator('body').innerText().catch(() => '');
    fs.writeFileSync(path.join(OUT, `${target.name}.html`), html);
    fs.writeFileSync(path.join(OUT, `${target.name}.txt`), text);
    await page.screenshot({ path: path.join(OUT, `${target.name}.png`), fullPage: true }).catch(() => {});

    const dom = await page.evaluate(() => {
      const attrs = [];
      for (const el of document.querySelectorAll('a,iframe,embed,object,img,source')) {
        for (const key of ['href','src','data','data-src','data-url','data-file','currentSrc','srcset']) {
          const value = el[key] || el.getAttribute?.(key) || '';
          if (value) attrs.push(String(value));
        }
      }
      return {
        attrs,
        resources: performance.getEntriesByType('resource').map(r => r.name),
        scripts: [...document.scripts].map(s => s.src || s.textContent || '').filter(Boolean),
      };
    }).catch(() => ({ attrs: [], resources: [], scripts: [] }));

    const combined = [html, ...dom.attrs, ...dom.resources, ...dom.scripts].join('\n');
    const matches = combined.match(/https?:[^"'\s<>]+/g) || [];
    for (const raw of matches) {
      const url = normalizeUrl(raw);
      if (/\.pdf(?:[?#]|$)|s\.reportify\.cn|cdn\.hangyan\.co\/documents|try_down|download/i.test(url)) candidateUrls.add(url);
    }

    // Known public preview APIs sometimes return the real file URL or public page assets.
    if (target.kind === 'fx') {
      const id = new URL(target.url).searchParams.get('id');
      if (id) candidateUrls.add(`https://api.fxbaogao.com/mofoun/report/report/getReportPreviewImages?reportId=${id}`);
    }

    for (const url of [...candidateUrls]) {
      try {
        const r = await context.request.get(url, { timeout: 45000, headers: { Referer: page.url(), Accept: 'application/pdf,application/json,*/*' } });
        const body = Buffer.from(await r.body());
        const ct = String(r.headers()['content-type'] || '');
        events.push({ type: 'probe', status: r.status(), url, contentType: ct, bytes: body.length, preview: ct.includes('json') ? body.toString('utf8').slice(0, 5000) : '' });
        if (isPdfBytes(body)) await savePdf(body, `${target.name}_probe`, url);
        if (ct.includes('json')) {
          const t = body.toString('utf8');
          const nested = t.match(/https?:[^"'\\\s<>]+/g) || [];
          for (const rawNested of nested) {
            const nestedUrl = normalizeUrl(rawNested);
            if (!/\.pdf(?:[?#]|$)|s\.reportify\.cn|cdn\.hangyan\.co\/documents/i.test(nestedUrl)) continue;
            try {
              const rr = await context.request.get(nestedUrl, { timeout: 45000, headers: { Referer: page.url(), Accept: 'application/pdf,*/*' } });
              const bb = Buffer.from(await rr.body());
              if (isPdfBytes(bb)) await savePdf(bb, `${target.name}_nested`, nestedUrl);
            } catch {}
          }
        }
      } catch (e) { events.push({ type: 'probe_error', url, error: String(e) }); }
    }
  } catch (e) {
    console.log('TARGET_ERR', target.name, String(e));
  }

  fs.writeFileSync(path.join(OUT, `${target.name}_events.json`), JSON.stringify(events, null, 2));
  await context.close();
}

fs.writeFileSync(path.join(OUT, 'saved_pdfs.json'), JSON.stringify(saved, null, 2));
await browser.close();
console.log('DONE', saved.length);
