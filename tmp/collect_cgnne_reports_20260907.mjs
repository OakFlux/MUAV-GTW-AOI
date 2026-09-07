import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import crypto from 'crypto';

const OUT = path.resolve('out_cgnne_reports_20260907');
const RAW = path.join(OUT, 'raw_pdfs');
const DIAG = path.join(OUT, 'diagnostics');
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(RAW, { recursive: true });
fs.mkdirSync(DIAG, { recursive: true });

const targets = [
  {
    label: 'hangyan_guoxin_20240523',
    url: 'https://www.hangyan.co/reports/3374738651710752209',
  },
  {
    label: 'hangyan_guoyuan_20250115',
    url: 'https://www.hangyan.co/reports/3545846060268127552',
  },
  {
    label: 'sgpjbg_guoxin_20210711',
    url: 'https://www.sgpjbg.com/baogao/44868.html',
    reportId: '44868',
  },
  {
    label: 'sgpjbg_guoxin_hk_20220422',
    url: 'https://www.sgpjbg.com/baogao/70108.html',
    reportId: '70108',
  },
  {
    label: 'ninefzt_guoxin_20210711',
    url: 'https://gmg.9fzt.com/report/HKSE/01811/679344712485.html',
  },
];

const browser = await chromium.launch({ headless: true });
const savedHashes = new Set();
const saved = [];

function sanitize(value) {
  return value.replace(/[^A-Za-z0-9._-]+/g, '_').slice(0, 180);
}

async function savePdfBuffer(buffer, label, sourceUrl) {
  if (!buffer || buffer.length < 30000 || buffer.subarray(0, 5).toString() !== '%PDF-') return false;
  const sha = crypto.createHash('sha256').update(buffer).digest('hex');
  if (savedHashes.has(sha)) return true;
  savedHashes.add(sha);
  const fileName = `${sanitize(label)}_${sha.slice(0, 12)}.pdf`;
  const filePath = path.join(RAW, fileName);
  fs.writeFileSync(filePath, buffer);
  const row = { file: filePath, label, sourceUrl, bytes: buffer.length, sha256: sha };
  saved.push(row);
  console.log('SAVED_PDF', JSON.stringify(row));
  return true;
}

function extractUrls(html, baseUrl) {
  const result = new Set();
  const decoded = html
    .replaceAll('\\u002F', '/')
    .replaceAll('\\/', '/')
    .replaceAll('&amp;', '&');
  const absolute = decoded.match(/https?:\/\/[^"'<>\s\\]+/g) || [];
  for (const url of absolute) result.add(url.replace(/[),;]+$/, ''));
  const attrRe = /(?:href|src|data-src|data-url|data-file|data-pdf|content)=["']([^"']+)["']/gi;
  let match;
  while ((match = attrRe.exec(decoded))) {
    try { result.add(new URL(match[1], baseUrl).href); } catch {}
  }
  return [...result];
}

async function probeUrl(context, url, label) {
  if (!/^https?:/i.test(url)) return false;
  try {
    const response = await context.request.get(url, {
      timeout: 60000,
      headers: {
        'Accept': 'application/pdf,application/octet-stream;q=0.9,*/*;q=0.5',
        'Referer': url,
      },
    });
    const body = await response.body();
    const contentType = response.headers()['content-type'] || '';
    console.log('PROBE', response.status(), contentType, body.length, url);
    return await savePdfBuffer(body, label, url);
  } catch (error) {
    console.log('PROBE_ERROR', url, String(error));
    return false;
  }
}

for (const target of targets) {
  const context = await browser.newContext({
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36',
    locale: 'zh-CN',
    acceptDownloads: true,
    viewport: { width: 1440, height: 1000 },
  });
  const page = await context.newPage();
  const network = [];

  page.on('response', async (response) => {
    const url = response.url();
    const headers = await response.allHeaders().catch(() => ({}));
    const contentType = headers['content-type'] || '';
    if (/pdf|octet-stream|download|report|document|fileroot|attachment/i.test(`${url} ${contentType}`)) {
      network.push({ status: response.status(), url, contentType, contentLength: headers['content-length'] || '' });
    }
    if (response.status() === 200 && (/application\/pdf/i.test(contentType) || /\.pdf(?:\?|$)/i.test(url))) {
      try {
        const body = await response.body();
        await savePdfBuffer(body, `${target.label}_network`, url);
      } catch {}
    }
  });
  page.on('download', async (download) => {
    const suggested = download.suggestedFilename();
    const temp = path.join(DIAG, `${target.label}_${sanitize(suggested)}`);
    try {
      await download.saveAs(temp);
      const body = fs.readFileSync(temp);
      await savePdfBuffer(body, `${target.label}_download`, download.url());
    } catch (error) {
      console.log('DOWNLOAD_ERROR', target.label, String(error));
    }
  });

  console.log('OPEN', target.label, target.url);
  try {
    await page.goto(target.url, { waitUntil: 'domcontentloaded', timeout: 90000 });
    await page.waitForTimeout(8000);
    const html = await page.content();
    const text = await page.locator('body').innerText().catch(() => '');
    fs.writeFileSync(path.join(DIAG, `${target.label}.html`), html);
    fs.writeFileSync(path.join(DIAG, `${target.label}.txt`), text);
    await page.screenshot({ path: path.join(DIAG, `${target.label}.png`), fullPage: true }).catch(() => {});

    const domUrls = await page.evaluate(() => {
      const urls = [];
      for (const element of document.querySelectorAll('a,iframe,embed,object,img,script,link')) {
        for (const attr of ['href','src','data','data-src','data-url','data-file','data-pdf']) {
          const value = element.getAttribute(attr);
          if (value) urls.push(value);
        }
      }
      return urls;
    }).catch(() => []);

    const candidates = new Set(extractUrls(html, page.url()));
    for (const value of domUrls) {
      try { candidates.add(new URL(value, page.url()).href); } catch {}
    }

    if (target.reportId) {
      candidates.add(`https://www.sgpjbg.com/sgpjbg/View.aspx?id=${target.reportId}`);
      candidates.add(`https://www.sgpjbg.com/bgdown/${target.reportId}.html`);
      candidates.add(`https://www.sgpjbg.com/baogao/${target.reportId}.html`);
    }

    const candidateList = [...candidates];
    fs.writeFileSync(path.join(DIAG, `${target.label}_urls.json`), JSON.stringify(candidateList, null, 2));

    // Probe explicit document/file candidates without credentials.
    for (const url of candidateList) {
      if (/\.pdf(?:\?|$)|download|attachment|fileroot|bookread|view\.aspx|report-image/i.test(url)) {
        await probeUrl(context, url, `${target.label}_candidate`);
      }
    }

    // Visit public iframe/viewer pages and inspect them for a direct PDF URL.
    const helperUrls = candidateList.filter((url) => /view\.aspx|bookread|viewer|bgdown/i.test(url)).slice(0, 12);
    for (const helper of helperUrls) {
      try {
        const helperPage = await context.newPage();
        await helperPage.goto(helper, { waitUntil: 'domcontentloaded', timeout: 60000 });
        await helperPage.waitForTimeout(5000);
        const helperHtml = await helperPage.content();
        fs.writeFileSync(path.join(DIAG, `${target.label}_helper_${sanitize(helper).slice(-90)}.html`), helperHtml);
        for (const url of extractUrls(helperHtml, helperPage.url())) {
          if (/\.pdf(?:\?|$)|download|attachment|fileroot/i.test(url)) {
            await probeUrl(context, url, `${target.label}_helper`);
          }
        }
        await helperPage.close();
      } catch (error) {
        console.log('HELPER_ERROR', helper, String(error));
      }
    }

    // Click only ordinary public download controls. Stop if the site requests login/payment.
    for (const selector of ['text=立即下载', 'text=下载报告', 'text=下载PDF', 'text=下载原文', 'text=立即查看']) {
      const locator = page.locator(selector).first();
      if (await locator.count().catch(() => 0)) {
        try {
          await locator.click({ timeout: 3000 });
          await page.waitForTimeout(5000);
          if (/login|signin|vip|member|pay/i.test(page.url())) {
            console.log('ACCESS_CONTROL_REACHED', target.label, page.url());
            break;
          }
        } catch {}
      }
    }
  } catch (error) {
    console.log('TARGET_ERROR', target.label, String(error));
  }

  fs.writeFileSync(path.join(DIAG, `${target.label}_network.json`), JSON.stringify(network, null, 2));
  await context.close();
}

fs.writeFileSync(path.join(OUT, 'collected.json'), JSON.stringify(saved, null, 2));
console.log('DONE_SAVED', saved.length);
await browser.close();
