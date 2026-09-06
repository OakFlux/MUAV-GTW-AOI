import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import crypto from 'crypto';

const OUT = path.resolve('out_qunabox_futu_report_inspection');
const DL = path.join(OUT, 'downloads');
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(DL, { recursive: true });

const targets = [
  ['futu_ratings', 'https://www.futunn.com/stock/00917-HK/institutional-ratings'],
  ['reportify_boci', 'https://reportify.cn/reports/1076889793637519360'],
  ['sgpjbg_csc', 'https://www.sgpjbg.com/baogao/357464.html'],
  ['sgpjbg_boci', 'https://www.sgpjbg.com/baogao/464567.html'],
];

const keywords = [
  '趣致集团', '趣致集團', 'Qunabox', '00917', '0917.HK',
  'AI互动营销领导者', '国内领先的AIoT营销服务平台', '深耕KA客户',
  '物理AI构建营销闭环', 'AI营销加速放量'
];
const interesting = /(pdf|download|attachment|file|report|research|rating|article|news|post|00917|0917|qunabox|趣致)/i;

const browser = await chromium.launch({ headless: true });
const globalSaved = [];

async function savePdfBuffer(buffer, label, url, source) {
  if (!buffer || buffer.length < 50000 || buffer.subarray(0, 5).toString() !== '%PDF-') return null;
  const sha = crypto.createHash('sha256').update(buffer).digest('hex');
  const filePath = path.join(DL, `${label}_${sha.slice(0, 12)}.pdf`);
  if (!fs.existsSync(filePath)) fs.writeFileSync(filePath, buffer);
  const row = { label, url, source, filePath, bytes: buffer.length, sha256: sha };
  globalSaved.push(row);
  console.log('PDF_SAVED', JSON.stringify(row));
  return row;
}

async function inspectTarget(label, url) {
  const context = await browser.newContext({
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36',
    locale: 'zh-CN',
    ignoreHTTPSErrors: true,
    acceptDownloads: true,
    viewport: { width: 1440, height: 1100 },
  });
  const page = await context.newPage();
  const events = [];
  const discoveredUrls = new Set();
  const openedPages = new Set();

  page.on('request', request => {
    const u = request.url();
    if (interesting.test(u)) {
      events.push({ type: 'request', method: request.method(), url: u, resourceType: request.resourceType(), postData: request.postData() });
    }
  });
  page.on('response', async response => {
    const u = response.url();
    const headers = await response.allHeaders().catch(() => ({}));
    const ct = headers['content-type'] || '';
    if (interesting.test(`${u} ${ct}`)) {
      const item = { type: 'response', status: response.status(), url: u, contentType: ct, headers };
      if (/json|text|javascript|html/i.test(ct)) {
        try {
          const text = await response.text();
          item.preview = text.slice(0, 20000);
          for (const m of text.matchAll(/https?:\\?\/\\?\/[^"'<>\\s]+/g)) {
            const clean = m[0].replaceAll('\\/', '/').replace(/[),;]+$/, '');
            if (interesting.test(clean)) discoveredUrls.add(clean);
          }
        } catch {}
      }
      events.push(item);
    }
    if (/application\/pdf|application\/octet-stream/i.test(ct) || /\.pdf(?:\?|$)/i.test(u)) {
      try {
        const body = await response.body();
        await savePdfBuffer(body, `${label}_network`, u, 'network-response');
      } catch (e) {
        console.log('PDF_BODY_ERROR', label, u, String(e));
      }
    }
  });
  page.on('download', async download => {
    try {
      const suggested = (download.suggestedFilename() || 'download.bin').replace(/[^A-Za-z0-9._-]+/g, '_');
      const temp = path.join(DL, `${label}_${Date.now()}_${suggested}`);
      await download.saveAs(temp);
      const body = fs.readFileSync(temp);
      const saved = await savePdfBuffer(body, `${label}_download`, download.url(), 'browser-download');
      if (!saved) fs.unlinkSync(temp);
      else if (temp !== saved.filePath) fs.unlinkSync(temp);
    } catch (e) {
      console.log('DOWNLOAD_ERROR', label, String(e));
    }
  });

  console.log('OPEN', label, url);
  try {
    const response = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 90000 });
    await page.waitForTimeout(12000);
    console.log('PAGE', label, response?.status(), page.url(), await page.title());
    openedPages.add(page.url());

    // For Futu, try the relevant visible analyst-rating entries without logging in.
    if (label === 'futu_ratings') {
      for (const pattern of [/AI互动营销领导者/i, /国内领先的AIOT营销服务平台/i, /深耕KA客户/i]) {
        const candidates = await page.getByText(pattern).all().catch(() => []);
        for (const loc of candidates.slice(0, 3)) {
          try {
            if (!(await loc.isVisible())) continue;
            const popupPromise = page.waitForEvent('popup', { timeout: 4000 }).catch(() => null);
            const before = page.url();
            await loc.click({ timeout: 8000 });
            const popup = await popupPromise;
            await page.waitForTimeout(5000);
            console.log('CLICKED', label, pattern.toString(), before, '=>', page.url(), popup ? popup.url() : 'no-popup');
            if (popup) {
              await popup.waitForLoadState('domcontentloaded', { timeout: 30000 }).catch(() => {});
              await popup.waitForTimeout(5000);
              discoveredUrls.add(popup.url());
              fs.writeFileSync(path.join(OUT, `${label}_popup_${Date.now()}.html`), await popup.content().catch(() => ''));
              fs.writeFileSync(path.join(OUT, `${label}_popup_${Date.now()}.txt`), await popup.locator('body').innerText().catch(() => ''));
              await popup.close();
            }
            if (page.url() !== before) {
              discoveredUrls.add(page.url());
              await page.goBack({ waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => {});
              await page.waitForTimeout(4000);
            }
          } catch (e) {
            console.log('CLICK_ERROR', label, pattern.toString(), String(e));
          }
        }
      }
    }

    // Click only visible public download/read buttons. Do not log in, pay, or solve CAPTCHA.
    for (const pattern of [/下载PDF/i, /下载报告/i, /免费下载/i, /查看原文/i, /阅读原文/i, /阅读全文/i]) {
      const candidates = await page.getByText(pattern).all().catch(() => []);
      for (const loc of candidates.slice(0, 3)) {
        try {
          if (!(await loc.isVisible())) continue;
          const before = page.url();
          const popupPromise = page.waitForEvent('popup', { timeout: 3000 }).catch(() => null);
          await loc.click({ timeout: 6000 });
          const popup = await popupPromise;
          await page.waitForTimeout(5000);
          console.log('PUBLIC_CLICK', label, pattern.toString(), before, '=>', page.url(), popup ? popup.url() : 'no-popup');
          if (popup) {
            discoveredUrls.add(popup.url());
            await popup.close();
          }
          if (page.url() !== before && !/login|signin|member|pay/i.test(page.url())) discoveredUrls.add(page.url());
          if (page.url() !== before) {
            await page.goBack({ waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => {});
            await page.waitForTimeout(3000);
          }
        } catch {}
      }
    }

    const html = await page.content();
    const text = await page.locator('body').innerText().catch(() => '');
    fs.writeFileSync(path.join(OUT, `${label}.html`), html);
    fs.writeFileSync(path.join(OUT, `${label}.txt`), text);
    await page.screenshot({ path: path.join(OUT, `${label}.png`), fullPage: true }).catch(() => {});

    const dom = await page.evaluate(() => ({
      url: location.href,
      title: document.title,
      anchors: [...document.querySelectorAll('a')].map((a, i) => ({ i, text: (a.innerText || a.textContent || '').trim(), href: a.href, download: a.download || '', outer: a.outerHTML.slice(0, 2000) })),
      buttons: [...document.querySelectorAll('button,[role="button"],[onclick]')].map((b, i) => ({ i, text: (b.innerText || b.textContent || '').trim(), onclick: b.getAttribute('onclick') || '', outer: b.outerHTML.slice(0, 2000) })),
      scripts: [...document.scripts].map((s, i) => ({ i, src: s.src, text: (s.textContent || '').slice(0, 100000) })),
      iframes: [...document.querySelectorAll('iframe,embed,object')].map((e, i) => ({ i, src: e.src || e.data || '', outer: e.outerHTML.slice(0, 3000) })),
    }));
    fs.writeFileSync(path.join(OUT, `${label}_dom.json`), JSON.stringify(dom, null, 2));
    for (const a of dom.anchors) if (interesting.test(`${a.text} ${a.href}`)) discoveredUrls.add(a.href);
    for (const s of dom.scripts) {
      const blob = `${s.src}\n${s.text}`;
      for (const m of blob.matchAll(/https?:\\?\/\\?\/[^"'<>\\s]+/g)) {
        const clean = m[0].replaceAll('\\/', '/').replace(/[),;]+$/, '');
        if (interesting.test(clean)) discoveredUrls.add(clean);
      }
    }
  } catch (e) {
    console.log('PAGE_ERROR', label, String(e));
  }

  // Probe only URLs visibly exposed by the public page/network.
  for (const u of [...discoveredUrls]) {
    if (!u || /^javascript:|^mailto:/.test(u) || /login|signin|register|member|pay|checkout/i.test(u)) continue;
    if (!interesting.test(u)) continue;
    try {
      const response = await context.request.get(u, { timeout: 45000, headers: { Referer: url } });
      const body = await response.body();
      const ct = response.headers()['content-type'] || '';
      console.log('PROBE', label, response.status(), ct, body.length, u);
      if (body.length > 50000 && body.subarray(0, 5).toString() === '%PDF-') {
        await savePdfBuffer(body, `${label}_probe`, u, 'public-exposed-url');
      }
    } catch {}
  }

  fs.writeFileSync(path.join(OUT, `${label}_events.json`), JSON.stringify({ events, discoveredUrls: [...discoveredUrls], openedPages: [...openedPages] }, null, 2));
  await context.close();
}

for (const [label, url] of targets) await inspectTarget(label, url);
fs.writeFileSync(path.join(OUT, 'saved_pdfs.json'), JSON.stringify(globalSaved, null, 2));
console.log('DONE saved', globalSaved.length);
await browser.close();
