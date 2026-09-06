import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import crypto from 'crypto';

const OUT = path.resolve('out_qunabox_book118_probe');
const DL = path.join(OUT, 'downloads');
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(DL, { recursive: true });

const targets = [
  ['boci_1', 'https://max.book118.com/html/2025/0115/5021340004012033.shtm'],
  ['boci_2', 'https://max.book118.com/html/2025/0116/5333211113012033.shtm'],
  ['boci_3', 'https://max.book118.com/html/2025/0115/8007070130007021.shtm'],
];

const browser = await chromium.launch({ headless: true });
for (const [label, url] of targets) {
  const context = await browser.newContext({
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36',
    locale: 'zh-CN',
    acceptDownloads: true,
    viewport: { width: 1440, height: 1000 },
  });
  const page = await context.newPage();
  const events = [];
  const saved = [];

  page.on('response', async response => {
    const u = response.url();
    const headers = await response.allHeaders().catch(() => ({}));
    const ct = headers['content-type'] || '';
    if (/pdf|download|file|attach|doc|trial|preview/i.test(`${u} ${ct}`)) {
      events.push({ type: 'response', status: response.status(), url: u, contentType: ct, headers });
      if (/application\/pdf|application\/octet-stream/i.test(ct)) {
        try {
          const body = await response.body();
          if (body.length > 50000 && body.subarray(0, 5).toString() === '%PDF-') {
            const sha = crypto.createHash('sha256').update(body).digest('hex');
            const out = path.join(DL, `${label}_network_${sha.slice(0, 12)}.pdf`);
            fs.writeFileSync(out, body);
            saved.push({ source: 'network', url: u, path: out, bytes: body.length, sha256: sha });
            console.log('SAVED_NETWORK', label, body.length, out, u);
          }
        } catch (e) {
          console.log('NETWORK_BODY_ERROR', label, u, String(e));
        }
      }
    }
  });
  page.on('download', async download => {
    const suggested = download.suggestedFilename() || `${label}.bin`;
    const safe = suggested.replace(/[^A-Za-z0-9._-]+/g, '_');
    const out = path.join(DL, `${label}_${Date.now()}_${safe}`);
    try {
      await download.saveAs(out);
      const body = fs.readFileSync(out);
      const sha = crypto.createHash('sha256').update(body).digest('hex');
      saved.push({ source: 'download', url: download.url(), path: out, bytes: body.length, sha256: sha, suggested });
      console.log('SAVED_DOWNLOAD', label, body.length, out, download.url());
    } catch (e) {
      console.log('DOWNLOAD_ERROR', label, String(e));
    }
  });

  console.log('OPEN', label, url);
  try {
    const response = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 90000 });
    await page.waitForTimeout(8000);
    console.log('PAGE', label, response?.status(), page.url(), await page.title());
    fs.writeFileSync(path.join(OUT, `${label}_before.html`), await page.content());
    fs.writeFileSync(path.join(OUT, `${label}_before.txt`), await page.locator('body').innerText().catch(() => ''));

    const controls = await page.locator('a,button,[role="button"],[onclick]').evaluateAll(nodes => nodes.map((n, i) => ({
      i,
      text: (n.innerText || n.textContent || '').trim(),
      href: n.href || '',
      onclick: n.getAttribute('onclick') || '',
      cls: n.className || '',
      outer: n.outerHTML.slice(0, 1500),
    })).filter(x => x.text || x.href || x.onclick));
    fs.writeFileSync(path.join(OUT, `${label}_controls.json`), JSON.stringify(controls, null, 2));

    const patterns = [
      /原文免费试下载/i,
      /免费试下载/i,
      /试下载/i,
      /下载文档/i,
      /下载本文档/i,
      /下载PDF/i,
    ];
    for (const pattern of patterns) {
      const matches = page.getByText(pattern).all();
      const locators = await matches.catch(() => []);
      for (let i = 0; i < Math.min(locators.length, 5); i++) {
        try {
          const loc = locators[i];
          if (!(await loc.isVisible().catch(() => false))) continue;
          console.log('CLICK', label, pattern.toString(), i);
          await loc.click({ timeout: 8000 });
          await page.waitForTimeout(6000);
          console.log('AFTER_CLICK', label, page.url());
        } catch (e) {
          console.log('CLICK_ERROR', label, pattern.toString(), i, String(e));
        }
      }
    }

    // Inspect visible links after clicks, but do not log in or solve any CAPTCHA.
    const afterLinks = await page.locator('a').evaluateAll(nodes => nodes.map(a => ({ text: (a.innerText || '').trim(), href: a.href, download: a.download || '' })));
    fs.writeFileSync(path.join(OUT, `${label}_after_links.json`), JSON.stringify(afterLinks, null, 2));
    fs.writeFileSync(path.join(OUT, `${label}_after.html`), await page.content());
    fs.writeFileSync(path.join(OUT, `${label}_after.txt`), await page.locator('body').innerText().catch(() => ''));
    await page.screenshot({ path: path.join(OUT, `${label}.png`), fullPage: true }).catch(() => {});
  } catch (e) {
    console.log('PAGE_ERROR', label, String(e));
  }
  fs.writeFileSync(path.join(OUT, `${label}_events.json`), JSON.stringify({ events, saved }, null, 2));
  await context.close();
}
await browser.close();
console.log('DONE');
