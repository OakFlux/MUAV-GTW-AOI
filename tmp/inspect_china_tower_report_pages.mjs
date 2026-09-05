import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const OUT = path.resolve('out_china_tower_report_pages_inspect');
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(OUT, { recursive: true });

const targets = [
  ['galaxy_nxny', 'https://www.nxny.com/report/view_6151053.html'],
  ['zheshang_vzkoo', 'https://www.vzkoo.com/read/202402195208828749e4ee37845e6ce0.html'],
  ['debon_hangyan', 'https://www.hangyan.co/reports/3485236846772881072'],
  ['fx_query', 'https://www.fxbaogao.com/q/2606281108649532'],
  ['debon_9fzt', 'https://gmg.9fzt.com/report/HKSE/00788/783044824450.html'],
  ['tianfeng_catalog', 'https://299sucai.com/hybg/12302/'],
];

const interesting = /(pdf|download|report|file|attachment|document|oss|cos|cdn|preview|image|api|6151053|3485236846772881072|202402195208828749e4ee37845e6ce0|00788|0788)/i;
const browser = await chromium.launch({ headless: true });

for (const [name, url] of targets) {
  const context = await browser.newContext({
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131 Safari/537.36',
    locale: 'zh-CN',
    viewport: { width: 1440, height: 1200 },
    acceptDownloads: true,
  });
  const page = await context.newPage();
  const events = [];
  const downloads = [];

  page.on('request', req => {
    const u = req.url();
    const postData = req.postData();
    if (interesting.test(`${u} ${postData || ''}`)) {
      events.push({ type: 'request', method: req.method(), resourceType: req.resourceType(), url: u, postData });
    }
  });
  page.on('response', async resp => {
    const u = resp.url();
    const h = await resp.allHeaders().catch(() => ({}));
    const ct = h['content-type'] || '';
    if (!interesting.test(`${u} ${ct}`)) return;
    const item = {
      type: 'response', status: resp.status(), url: u,
      contentType: ct, contentLength: h['content-length'] || '', headers: h,
    };
    if (/json|text|javascript|xml|html/i.test(ct)) {
      const size = Number(item.contentLength || 0);
      if (!size || size < 2000000) item.preview = (await resp.text().catch(() => '')).slice(0, 150000);
    }
    events.push(item);
  });
  page.on('download', async d => {
    const suggested = d.suggestedFilename();
    const dest = path.join(OUT, `${name}_${suggested}`);
    try { await d.saveAs(dest); } catch {}
    downloads.push({ suggested, dest, failure: await d.failure().catch(() => null) });
  });

  console.log('VISIT', name, url);
  try {
    const nav = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 90000 });
    console.log('NAV', name, nav?.status(), page.url(), await page.title().catch(() => ''));
    await page.waitForTimeout(12000);

    // Exercise only buttons presented as free/public viewing. Never log in or bypass paywalls.
    const patterns = [
      /免费查看完整报告/i, /点击免费查看/i, /阅读全文/i, /查看全文/i,
      /展开全文/i, /报告原文/i, /预览报告/i, /在线阅读/i,
    ];
    for (const pat of patterns) {
      const locator = page.getByText(pat).first();
      if (await locator.count().catch(() => 0)) {
        try {
          await locator.click({ timeout: 4000, force: true });
          console.log('CLICK', name, pat.toString(), page.url());
          await page.waitForTimeout(5000);
        } catch (e) {
          console.log('CLICK_ERR', name, pat.toString(), String(e));
        }
      }
    }

    // Scroll to trigger lazy-loaded report pages/resources.
    for (let i = 0; i < 10; i++) {
      await page.mouse.wheel(0, 1500);
      await page.waitForTimeout(800);
    }
    await page.waitForTimeout(5000);

    const dom = await page.evaluate(() => ({
      currentUrl: location.href,
      title: document.title,
      bodyText: (document.body?.innerText || '').slice(0, 500000),
      anchors: [...document.querySelectorAll('a')].map((a, i) => ({
        i, text: (a.innerText || a.textContent || '').trim(), href: a.href,
        download: a.getAttribute('download') || '', outer: a.outerHTML.slice(0, 3000),
      })),
      images: [...document.images].map((im, i) => ({
        i, src: im.src, currentSrc: im.currentSrc, alt: im.alt,
        naturalWidth: im.naturalWidth, naturalHeight: im.naturalHeight,
        outer: im.outerHTML.slice(0, 3000),
      })),
      frames: [...document.querySelectorAll('iframe,embed,object')].map((e, i) => ({
        i, src: e.src || e.data || '', outer: e.outerHTML.slice(0, 5000),
      })),
      scripts: [...document.scripts].map((s, i) => ({
        i, src: s.src, text: (s.textContent || '').slice(0, 100000),
      })),
      linksInText: [...new Set((document.documentElement.outerHTML.match(/https?:\\?\/\\?\/[^"'<>\\s]+/g) || []))].slice(0, 5000),
      localStorage: {...localStorage}, sessionStorage: {...sessionStorage},
    }));
    fs.writeFileSync(path.join(OUT, `${name}_dom.json`), JSON.stringify(dom, null, 2));
    fs.writeFileSync(path.join(OUT, `${name}.html`), await page.content());
    fs.writeFileSync(path.join(OUT, `${name}.txt`), dom.bodyText);
    await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true }).catch(() => {});
  } catch (e) {
    console.log('PAGE_ERR', name, String(e));
  }

  const resources = await page.evaluate(() => performance.getEntriesByType('resource').map(r => ({name:r.name, initiatorType:r.initiatorType, duration:r.duration, transferSize:r.transferSize}))).catch(() => []);
  fs.writeFileSync(path.join(OUT, `${name}_network.json`), JSON.stringify({ events, downloads, resources }, null, 2));
  console.log('SUMMARY', name, 'events', events.length, 'resources', resources.length, 'downloads', downloads.length);
  for (const e of events.filter(x => /pdf|download|attachment|file|api|preview/i.test(`${x.url} ${x.contentType || ''}`)).slice(-100)) {
    console.log('EVENT', name, JSON.stringify(e).slice(0, 3000));
  }
  await context.close();
}

await browser.close();
console.log('READY', OUT);
