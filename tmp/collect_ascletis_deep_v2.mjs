import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import crypto from 'crypto';

const OUT = path.resolve('out_ascletis_deep_v2');
const PDFDIR = path.join(OUT, 'pdfs');
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(PDFDIR, { recursive: true });

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36';
const targetTerms = /歌礼制药|歌禮製藥|Ascletis|01672|1672\.HK/i;
const desiredTerms = /全新GLP-1减重不减肌|口服小分子率先破局|创新药研发推进顺利|BD合作空间广阔|首次覆盖|歌礼制药-B/i;

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
  return String(value || 'file').replace(/[^A-Za-z0-9_.-]+/g, '_').slice(0, 150);
}

const saved = [];
const seenHashes = new Set();
async function savePdf(buffer, label, sourceUrl, context = {}) {
  if (!isPdfBytes(buffer)) return null;
  const sha256 = crypto.createHash('sha256').update(buffer).digest('hex');
  if (seenHashes.has(sha256)) return null;
  seenHashes.add(sha256);
  const file = path.join(PDFDIR, `${safeName(label)}_${sha256.slice(0, 12)}.pdf`);
  fs.writeFileSync(file, buffer);
  const item = { file, label, sourceUrl, bytes: buffer.length, sha256, ...context };
  saved.push(item);
  console.log('SAVED_PDF', JSON.stringify(item));
  return file;
}

function extractUrls(text) {
  const raw = String(text || '').match(/https?:[^"'\\\s<>]+/g) || [];
  return [...new Set(raw.map(normalizeUrl).filter(u => /^https?:\/\//i.test(u)))];
}

async function fetchAndMaybeSave(url, label, referer, context = {}) {
  try {
    const response = await fetch(url, {
      headers: { 'User-Agent': UA, Referer: referer || 'https://reportify.cn/', Accept: 'application/pdf,application/json,text/plain,*/*' },
      redirect: 'follow',
    });
    const buffer = Buffer.from(await response.arrayBuffer());
    const ct = response.headers.get('content-type') || '';
    console.log('FETCH', response.status, ct, buffer.length, url);
    if (isPdfBytes(buffer)) return await savePdf(buffer, label, response.url, context);
    if (/json|text|html|javascript/i.test(ct) && buffer.length < 3000000) {
      const text = buffer.toString('utf8');
      for (const nested of extractUrls(text)) {
        if (!/\.pdf(?:[?#]|$)|s\.reportify\.cn|cdn\.hangyan\.co\/documents|try_down|download/i.test(nested)) continue;
        await fetchAndMaybeSave(nested, `${label}_nested`, url, context);
      }
    }
  } catch (e) {
    console.log('FETCH_ERR', url, String(e));
  }
  return null;
}

// 1) Query Reportify exact titles and institutions. Capture all matching report IDs.
const reportifyQueries = [
  '歌礼制药 全新GLP-1减重不减肌',
  '歌礼制药 口服小分子率先破局',
  '歌礼制药 创新药研发推进顺利 BD合作空间广阔',
  '歌礼制药 东吴证券',
  '歌礼制药 东方证券',
  '歌礼制药 国元国际',
];
const reportifyItems = new Map();
for (const query of reportifyQueries) {
  const api = `https://api.reportify.cn/reports?query=${encodeURIComponent(query)}&page_num=1&page_size=100`;
  try {
    const r = await fetch(api, { headers: { 'User-Agent': UA, Accept: 'application/json', Referer: 'https://reportify.cn/' } });
    const text = await r.text();
    fs.writeFileSync(path.join(OUT, `reportify_${safeName(query)}.json`), text);
    console.log('REPORTIFY_SEARCH', query, r.status, text.length);
    const obj = JSON.parse(text);
    const items = Array.isArray(obj?.items) ? obj.items : Array.isArray(obj?.data) ? obj.data : [];
    for (const item of items) {
      const blob = JSON.stringify(item);
      if (!targetTerms.test(blob) || !desiredTerms.test(blob)) continue;
      const id = String(item.report_id || item.id || '');
      if (!id) continue;
      reportifyItems.set(id, item);
      console.log('REPORTIFY_MATCH', id, item.institution_name || '', item.publish_at || '', item.title || item.report_title || '');
      for (const url of extractUrls(blob)) {
        if (/\.pdf(?:[?#]|$)|s\.reportify\.cn|download/i.test(url)) {
          await fetchAndMaybeSave(url, `reportify_api_${id}`, api, { reportId: id, title: item.title || item.report_title || '', institution: item.institution_name || '' });
        }
      }
    }
  } catch (e) { console.log('REPORTIFY_SEARCH_ERR', query, String(e)); }
}
// Known report IDs as a hard fallback.
for (const id of ['1104529108471255040','1104550200514580480','1028312670044033024','1153059671414804480']) {
  if (!reportifyItems.has(id)) reportifyItems.set(id, { report_id: id, title: 'known Ascletis report' });
}

// Probe plausible public detail/download API endpoints.
for (const [id, item] of reportifyItems.entries()) {
  const endpoints = [
    `https://api.reportify.cn/reports/${id}`,
    `https://api.reportify.cn/report/${id}`,
    `https://api.reportify.cn/reports?report_id=${id}`,
    `https://api.reportify.cn/reports?id=${id}`,
    `https://api.reportify.cn/reports/${id}/download`,
    `https://api.reportify.cn/report/${id}/download`,
    `https://reportify.cn/api/reports/${id}`,
  ];
  for (const endpoint of endpoints) {
    await fetchAndMaybeSave(endpoint, `reportify_endpoint_${id}`, `https://reportify.cn/reports/${id}`, { reportId: id, title: item.title || item.report_title || '', institution: item.institution_name || '' });
  }
}

// 2) Use Bing to discover mirrors and duplicate public uploads for exact titles.
const bingQueries = [
  '"歌礼制药-B" "全新GLP-1减重不减肌" PDF',
  '"歌礼制药-B" "口服小分子率先破局" PDF',
  '"歌礼制药-B" "创新药研发推进顺利" PDF',
  'site:max.book118.com 歌礼制药 全新GLP-1减重不减肌',
  'site:max.book118.com 歌礼制药 口服小分子率先破局',
  'site:sgpjbg.com 歌礼制药 研报',
  'site:hangyan.co/reports 歌礼制药',
];
const discoveredPages = new Set([
  'https://max.book118.com/html/2025/0407/7161064025010056.shtm',
  'https://reportify.cn/reports/1104529108471255040',
  'https://reportify.cn/reports/1104550200514580480',
  'https://reportify.cn/reports/1028312670044033024',
  'https://www.fxbaogao.com/view?id=4757488',
  'https://www.fxbaogao.com/view?id=5205547',
  'https://www.hangyan.co/reports/3448696034581022433',
]);
for (const query of bingQueries) {
  try {
    const url = `https://www.bing.com/search?q=${encodeURIComponent(query)}&count=50`;
    const r = await fetch(url, { headers: { 'User-Agent': UA, Accept: 'text/html' } });
    const html = await r.text();
    fs.writeFileSync(path.join(OUT, `bing_${safeName(query)}.html`), html);
    console.log('BING', query, r.status, html.length);
    const hrefs = [...html.matchAll(/href="(https?:[^"#]+)"/g)].map(m => normalizeUrl(m[1]));
    for (const href of hrefs) {
      if (/book118|fxbaogao|hangyan|sgpjbg|reportify|hibor|nxny|sdyanbao|sina|dwzq|dfzq|guoyuan|pdf\.dfcfw/i.test(href)) discoveredPages.add(href);
    }
  } catch (e) { console.log('BING_ERR', query, String(e)); }
}

const browser = await chromium.launch({ headless: true });
for (const pageUrl of [...discoveredPages].slice(0, 80)) {
  const context = await browser.newContext({ userAgent: UA, locale: 'zh-CN', acceptDownloads: true, viewport: { width: 1440, height: 1200 } });
  const page = await context.newPage();
  const label = safeName(new URL(pageUrl).hostname + '_' + path.basename(new URL(pageUrl).pathname) + '_' + new URL(pageUrl).search);
  const events = [];
  const candidates = new Set();
  page.on('response', async response => {
    const u = normalizeUrl(response.url());
    const h = await response.allHeaders().catch(() => ({}));
    const ct = String(h['content-type'] || '').toLowerCase();
    if (/pdf|report|download|document|file|attachment|preview/i.test(`${u} ${ct}`)) events.push({ type: 'response', status: response.status(), url: u, contentType: ct, contentLength: h['content-length'] || '' });
    if (ct.includes('application/pdf') || /\.pdf(?:[?#]|$)/i.test(u)) {
      try { await savePdf(await response.body(), `${label}_response`, u, { pageUrl }); } catch {}
    }
    if (/json/i.test(ct) && /reportify|fxbaogao|hangyan/i.test(u)) {
      try {
        const body = await response.text();
        events.push({ type: 'json', url: u, preview: body.slice(0, 10000) });
        for (const nested of extractUrls(body)) if (/\.pdf(?:[?#]|$)|s\.reportify\.cn|cdn\.hangyan\.co\/documents|download/i.test(nested)) candidates.add(nested);
      } catch {}
    }
  });
  page.on('download', async download => {
    try {
      const temp = await download.path();
      if (temp && fs.existsSync(temp)) await savePdf(fs.readFileSync(temp), `${label}_download_${download.suggestedFilename()}`, download.url(), { pageUrl });
    } catch (e) { console.log('DOWNLOAD_ERR', pageUrl, String(e)); }
  });

  try {
    console.log('OPEN', pageUrl);
    const nav = await page.goto(pageUrl, { waitUntil: 'domcontentloaded', timeout: 90000 });
    console.log('PAGE', nav?.status(), page.url(), await page.title().catch(() => ''));
    await page.waitForTimeout(7000);
    const publicPatterns = [/原文免费试下载/i,/免费试下载/i,/试下载/i,/点击免费查看完整报告/i,/免费查看完整报告/i,/查看全文/i,/阅读全文/i,/下载报告/i];
    for (const pattern of publicPatterns) {
      const loc = page.getByText(pattern).first();
      if (await loc.count().catch(() => 0)) {
        try { console.log('CLICK', pageUrl, String(pattern)); await loc.click({ timeout: 6000, force: true }); await page.waitForTimeout(7000); } catch (e) { console.log('CLICK_ERR', String(e).slice(0,300)); }
      }
    }
    for (const fraction of [0.25,0.5,0.75,1]) {
      await page.evaluate(f => window.scrollTo(0, document.body.scrollHeight * f), fraction).catch(() => {});
      await page.waitForTimeout(1500);
    }
    const html = await page.content().catch(() => '');
    const text = await page.locator('body').innerText().catch(() => '');
    fs.writeFileSync(path.join(OUT, `${label}.html`), html);
    fs.writeFileSync(path.join(OUT, `${label}.txt`), text);
    const dom = await page.evaluate(() => ({
      attrs: [...document.querySelectorAll('a,iframe,embed,object,img,source,script')].flatMap(el => ['href','src','data','data-src','data-url','data-file','currentSrc','srcset'].map(k => el[k] || el.getAttribute?.(k) || '')).filter(Boolean),
      resources: performance.getEntriesByType('resource').map(r => r.name),
      html: document.documentElement.outerHTML,
    })).catch(() => ({ attrs: [], resources: [], html: '' }));
    for (const u of extractUrls([html, dom.html, ...dom.attrs, ...dom.resources].join('\n'))) {
      if (/\.pdf(?:[?#]|$)|s\.reportify\.cn|cdn\.hangyan\.co\/documents|try_down|download/i.test(u)) candidates.add(u);
    }
    // FxBaogao public preview API: may expose more than images or a source field.
    if (/fxbaogao\.com/.test(pageUrl)) {
      const id = new URL(pageUrl).searchParams.get('id') || (pageUrl.match(/detail\/(\d+)/) || [])[1];
      if (id) candidates.add(`https://api.fxbaogao.com/mofoun/report/report/getReportPreviewImages?reportId=${id}`);
    }
    for (const candidate of [...candidates]) {
      try {
        const r = await context.request.get(candidate, { timeout: 45000, headers: { Referer: page.url(), Accept: 'application/pdf,application/json,*/*' } });
        const body = Buffer.from(await r.body());
        const ct = String(r.headers()['content-type'] || '');
        events.push({ type: 'probe', status: r.status(), url: candidate, contentType: ct, bytes: body.length, preview: /json|text/.test(ct) ? body.toString('utf8').slice(0,10000) : '' });
        if (isPdfBytes(body)) await savePdf(body, `${label}_probe`, candidate, { pageUrl });
        if (/json|text/.test(ct)) {
          for (const nested of extractUrls(body.toString('utf8'))) {
            if (!/\.pdf(?:[?#]|$)|s\.reportify\.cn|cdn\.hangyan\.co\/documents|try_down|download/i.test(nested)) continue;
            try {
              const rr = await context.request.get(nested, { timeout: 45000, headers: { Referer: page.url(), Accept: 'application/pdf,*/*' } });
              const bb = Buffer.from(await rr.body());
              if (isPdfBytes(bb)) await savePdf(bb, `${label}_nested`, nested, { pageUrl });
            } catch {}
          }
        }
      } catch (e) { events.push({ type: 'probe_error', url: candidate, error: String(e) }); }
    }
  } catch (e) { console.log('PAGE_ERR', pageUrl, String(e)); }
  fs.writeFileSync(path.join(OUT, `${label}_events.json`), JSON.stringify(events, null, 2));
  await context.close();
}
await browser.close();
fs.writeFileSync(path.join(OUT, 'saved_pdfs.json'), JSON.stringify(saved, null, 2));
fs.writeFileSync(path.join(OUT, 'reportify_items.json'), JSON.stringify([...reportifyItems.values()], null, 2));
fs.writeFileSync(path.join(OUT, 'discovered_pages.json'), JSON.stringify([...discoveredPages], null, 2));
console.log('DONE', saved.length);
