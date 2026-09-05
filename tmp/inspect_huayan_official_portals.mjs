import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const OUT = path.resolve('out_huayan_official_portals');
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(OUT, { recursive: true });

const portals = [
  { key: 'bocom', url: 'https://research.bocomgroup.com/' },
  { key: 'gtht', url: 'https://irs.gtht.com/irs/fundHome' },
  { key: 'xyzqhk', url: 'https://www.xyzq.com.hk/' },
  { key: 'xyzqcn', url: 'https://www.xyzq.com.cn/' },
];

const browser = await chromium.launch({ headless: true });
const all = {};
for (const portal of portals) {
  const context = await browser.newContext({
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36',
    locale: 'zh-CN',
    viewport: { width: 1440, height: 900 },
  });
  const page = await context.newPage();
  const events = [];
  page.on('response', async response => {
    const url = response.url();
    const headers = await response.allHeaders().catch(() => ({}));
    const ct = headers['content-type'] || '';
    if (/api|search|report|research|download|file|pdf|query|list/i.test(`${url} ${ct}`)) {
      const event = { status: response.status(), url, contentType: ct, contentLength: headers['content-length'] || '' };
      if (/json|text|javascript/i.test(ct)) {
        event.preview = (await response.text().catch(() => '')).slice(0, 12000);
      }
      events.push(event);
    }
  });
  page.on('requestfailed', request => {
    events.push({ status: 0, url: request.url(), failure: request.failure()?.errorText || '' });
  });

  console.log('OPEN', portal.key, portal.url);
  await page.goto(portal.url, { waitUntil: 'domcontentloaded', timeout: 70000 }).catch(err => console.log('GOTO_ERR', portal.key, String(err)));
  await page.waitForTimeout(8000);
  const title = await page.title().catch(() => '');
  const body = await page.locator('body').innerText().catch(() => '');
  const html = await page.content().catch(() => '');
  fs.writeFileSync(path.join(OUT, `${portal.key}_initial.txt`), body);
  fs.writeFileSync(path.join(OUT, `${portal.key}_initial.html`), html);
  await page.screenshot({ path: path.join(OUT, `${portal.key}_initial.png`), fullPage: true }).catch(() => {});
  console.log('LOADED', portal.key, page.url(), title, 'body', body.length, body.slice(0, 1000).replace(/\n/g, ' | '));

  const inputs = await page.locator('input').evaluateAll(nodes => nodes.map((n, i) => ({ i, type: n.type, placeholder: n.placeholder, name: n.name, id: n.id, cls: n.className }))).catch(() => []);
  const buttons = await page.locator('button,[role="button"],a').evaluateAll(nodes => nodes.map((n, i) => ({ i, text: (n.textContent || '').trim(), href: n.href || '', cls: n.className || '' })).filter(x => x.text || x.href)).catch(() => []);
  fs.writeFileSync(path.join(OUT, `${portal.key}_controls.json`), JSON.stringify({ inputs, buttons }, null, 2));
  console.log('INPUTS', portal.key, JSON.stringify(inputs).slice(0, 6000));

  // Use only visible public search controls. Do not attempt authentication.
  let searched = false;
  const candidateInputs = page.locator('input').filter({ has: undefined });
  const count = await candidateInputs.count().catch(() => 0);
  for (let i = 0; i < count; i++) {
    const loc = candidateInputs.nth(i);
    const placeholder = (await loc.getAttribute('placeholder').catch(() => '')) || '';
    const type = (await loc.getAttribute('type').catch(() => '')) || '';
    if (/搜索|检索|search|关键字|关键词|报告|证券/i.test(placeholder) || type === 'search') {
      try {
        console.log('SEARCH_INPUT', portal.key, i, placeholder);
        await loc.fill('华沿机器人');
        await loc.press('Enter');
        searched = true;
        await page.waitForTimeout(7000);
        break;
      } catch (err) {
        console.log('SEARCH_INPUT_ERR', portal.key, i, String(err));
      }
    }
  }
  if (!searched) {
    for (const pattern of [/搜索/i, /检索/i, /Search/i]) {
      const btn = page.getByText(pattern).first();
      if (await btn.count().catch(() => 0)) {
        console.log('SEARCH_BUTTON_ONLY', portal.key, pattern.toString());
      }
    }
  }

  const afterBody = await page.locator('body').innerText().catch(() => '');
  const afterHtml = await page.content().catch(() => '');
  fs.writeFileSync(path.join(OUT, `${portal.key}_after.txt`), afterBody);
  fs.writeFileSync(path.join(OUT, `${portal.key}_after.html`), afterHtml);
  await page.screenshot({ path: path.join(OUT, `${portal.key}_after.png`), fullPage: true }).catch(() => {});
  console.log('AFTER', portal.key, page.url(), 'searched', searched, 'body', afterBody.length, afterBody.slice(0, 1800).replace(/\n/g, ' | '));

  const resources = await page.evaluate(() => performance.getEntriesByType('resource').map(r => r.name)).catch(() => []);
  const storage = await page.evaluate(() => ({
    localStorage: Object.fromEntries(Object.entries(localStorage)),
    sessionStorage: Object.fromEntries(Object.entries(sessionStorage)),
  })).catch(() => ({}));
  all[portal.key] = { url: page.url(), title, searched, inputs, events, resources, storage };
  fs.writeFileSync(path.join(OUT, `${portal.key}_network.json`), JSON.stringify(all[portal.key], null, 2));
  for (const event of events) {
    if (/华沿|1021|report|research|search|pdf|download|api/i.test(`${event.url} ${event.preview || ''}`)) {
      console.log('EVENT', portal.key, JSON.stringify(event).slice(0, 15000));
    }
  }

  // Fetch public JavaScript bundles referenced by the page and grep for API routes.
  const jsUrls = [...new Set(resources.filter(u => /\.js(?:\?|$)/i.test(u)))].slice(0, 80);
  const jsFindings = [];
  for (let i = 0; i < jsUrls.length; i++) {
    const url = jsUrls[i];
    try {
      const response = await context.request.get(url, { timeout: 30000 });
      const text = await response.text();
      if (!/api|report|research|search|download|pdf|file/i.test(text)) continue;
      const contexts = [];
      for (const term of ['api', 'report', 'research', 'search', 'download', 'pdf', 'fileUrl', 'file_url']) {
        const regex = new RegExp(term, 'ig');
        let match;
        let n = 0;
        while ((match = regex.exec(text)) && n < 20) {
          contexts.push({ term, context: text.slice(Math.max(0, match.index - 500), match.index + 1400) });
          n++;
        }
      }
      const urls = [...new Set(text.match(/https?:\/\/[^"'`\\\s<>]+/g) || [])];
      const paths = [...new Set([...text.matchAll(/["'](\/[^"']*(?:api|report|research|search|download|pdf|file)[^"']*)["']/ig)].map(m => m[1]))];
      jsFindings.push({ url, urls, paths, contexts });
      console.log('JS_FINDING', portal.key, url, JSON.stringify({ urls: urls.slice(0, 80), paths: paths.slice(0, 150) }).slice(0, 12000));
    } catch (err) {
      console.log('JS_ERR', portal.key, url, String(err));
    }
  }
  fs.writeFileSync(path.join(OUT, `${portal.key}_js_findings.json`), JSON.stringify(jsFindings, null, 2));
  await context.close();
}
fs.writeFileSync(path.join(OUT, 'all.json'), JSON.stringify(all, null, 2));
await browser.close();
console.log('READY', OUT);
