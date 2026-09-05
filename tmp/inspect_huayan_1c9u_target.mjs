import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const OUT = path.resolve('out_huayan_1c9u_target');
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(OUT, { recursive: true });

const target = 'https://1c9u.com/zhishiku/document/z-5Lq65b2i5py65Zmo5Lq655-l6K-G5bqTADQ06aG1LTIwMjYwODA3LeS6pOmTtuWbvemZhS3ljY7msr_mnLrlmajkurotMTAyMS5ISy3kurrlvaLmnLrlmajkurrooYzkuJrns7vliJfvvIg077yJ77ya4oCc5Y2W6ZOy5Lq64oCd5Z6L5bmz5Y-w5YWs5Y-477yM6L-Q5Yqo5o6n5Yi25bqV5bGC5Lu35YC85pyJ5pyb6YeN5LywLnBkZg';

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36',
  locale: 'zh-CN',
  viewport: { width: 1440, height: 1000 },
  acceptDownloads: true,
});
const page = await context.newPage();
const events = [];
const downloads = [];

page.on('response', async response => {
  const url = response.url();
  const headers = await response.allHeaders().catch(() => ({}));
  const ct = headers['content-type'] || '';
  if (/weapi|gzhMaterial|getDoc|download|file|pdf|document|zhishiku|storage|oss|cos|cdn/i.test(`${url} ${ct}`)) {
    const entry = { status: response.status(), url, contentType: ct, contentLength: headers['content-length'] || '' };
    if (/json|text|javascript|html/i.test(ct)) {
      entry.preview = (await response.text().catch(() => '')).slice(0, 20000);
    }
    events.push(entry);
    console.log('RESPONSE', JSON.stringify(entry).slice(0, 22000));
  }
});
page.on('request', request => {
  const url = request.url();
  if (/weapi|gzhMaterial|getDoc|download|file|pdf|document/i.test(url)) {
    console.log('REQUEST', request.method(), url, request.postData() || '');
  }
});
page.on('requestfailed', request => {
  console.log('REQUEST_FAILED', request.url(), request.failure()?.errorText || '');
});
page.on('download', async download => {
  const name = download.suggestedFilename();
  const dest = path.join(OUT, name || `download_${downloads.length}.bin`);
  await download.saveAs(dest).catch(() => {});
  const failure = await download.failure().catch(() => null);
  downloads.push({ name, dest, failure });
  console.log('DOWNLOAD', name, failure, dest);
});

console.log('OPEN', target);
await page.goto(target, { waitUntil: 'domcontentloaded', timeout: 70000 }).catch(err => console.log('GOTO_ERR', String(err)));
await page.waitForTimeout(12000);
console.log('PAGE', page.url(), await page.title().catch(() => ''));

const body = await page.locator('body').innerText().catch(() => '');
const html = await page.content().catch(() => '');
fs.writeFileSync(path.join(OUT, 'initial.txt'), body);
fs.writeFileSync(path.join(OUT, 'initial.html'), html);
await page.screenshot({ path: path.join(OUT, 'initial.png'), fullPage: true }).catch(() => {});
console.log('BODY', body.length, body.slice(0, 8000).replace(/\n/g, ' | '));

const controls = await page.locator('a,button,[role="button"],input').evaluateAll(nodes => nodes.map((n, i) => ({
  i,
  tag: n.tagName,
  text: (n.textContent || '').trim(),
  href: n.href || '',
  type: n.type || '',
  placeholder: n.placeholder || '',
  data: Object.fromEntries([...n.attributes].filter(a => a.name.startsWith('data-')).map(a => [a.name, a.value])),
  cls: n.className || '',
})).filter(x => x.text || x.href || x.placeholder)).catch(() => []);
fs.writeFileSync(path.join(OUT, 'controls.json'), JSON.stringify(controls, null, 2));
console.log('CONTROLS', JSON.stringify(controls).slice(0, 30000));

const storage = await page.evaluate(() => ({
  localStorage: Object.fromEntries(Object.entries(localStorage)),
  sessionStorage: Object.fromEntries(Object.entries(sessionStorage)),
  cookies: document.cookie,
})).catch(() => ({}));
fs.writeFileSync(path.join(OUT, 'storage.json'), JSON.stringify(storage, null, 2));
console.log('STORAGE', JSON.stringify(storage).slice(0, 10000));

// Click only ordinary visible public buttons. Do not enter credentials, tokens, or QR login.
for (const pattern of [/下载原文/i, /下载PDF/i, /下载/i, /查看原文/i, /获取文档/i, /打开文档/i]) {
  const matches = page.getByText(pattern, { exact: false });
  const count = await matches.count().catch(() => 0);
  console.log('BUTTON_PATTERN', pattern.toString(), count);
  for (let i = 0; i < Math.min(count, 3); i++) {
    const loc = matches.nth(i);
    if (!(await loc.isVisible().catch(() => false))) continue;
    console.log('CLICK', pattern.toString(), i, await loc.innerText().catch(() => ''));
    await loc.click({ force: true, timeout: 8000 }).catch(err => console.log('CLICK_ERR', String(err)));
    await page.waitForTimeout(7000);
    console.log('AFTER_CLICK', page.url(), (await page.locator('body').innerText().catch(() => '')).slice(-4000).replace(/\n/g, ' | '));
  }
}

const finalBody = await page.locator('body').innerText().catch(() => '');
const finalHtml = await page.content().catch(() => '');
fs.writeFileSync(path.join(OUT, 'final.txt'), finalBody);
fs.writeFileSync(path.join(OUT, 'final.html'), finalHtml);
await page.screenshot({ path: path.join(OUT, 'final.png'), fullPage: true }).catch(() => {});

const resources = await page.evaluate(() => performance.getEntriesByType('resource').map(r => r.name)).catch(() => []);
fs.writeFileSync(path.join(OUT, 'network.json'), JSON.stringify({ events, resources, downloads }, null, 2));

// Download only public URLs already exposed by the unauthenticated page/network.
const candidateUrls = [...new Set([
  ...events.map(e => e.url),
  ...resources,
  ...controls.map(c => c.href).filter(Boolean),
])].filter(u => /\.pdf(?:\?|$)|getDocUrl|getDocLink|download/i.test(u));
console.log('CANDIDATE_URLS', JSON.stringify(candidateUrls).slice(0, 30000));
for (let i = 0; i < candidateUrls.length; i++) {
  const url = candidateUrls[i];
  try {
    const response = await context.request.get(url, { timeout: 30000 });
    const data = await response.body();
    const ct = response.headers()['content-type'] || '';
    console.log('PUBLIC_FETCH', i, response.status(), ct, data.length, url);
    if (response.status() === 200 && data.length > 80000 && data.subarray(0, 5).toString() === '%PDF-') {
      const dest = path.join(OUT, `public_${i}.pdf`);
      fs.writeFileSync(dest, data);
      console.log('PUBLIC_PDF', dest, data.length);
    }
  } catch (err) {
    console.log('PUBLIC_FETCH_ERR', url, String(err));
  }
}

await context.close();
await browser.close();
console.log('READY', OUT);
