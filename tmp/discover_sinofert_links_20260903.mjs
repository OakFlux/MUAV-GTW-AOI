import { chromium } from 'playwright';
import fs from 'node:fs/promises';

const seeds = [
  'https://www.sinofert.com/',
  'https://www.sinofert.com/sinoferten/index.html',
  'https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=zh&market=SEHK&stockId=2808',
  'https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=en&market=SEHK&stockId=2808'
];

const browser = await chromium.launch({headless:true});
const context = await browser.newContext({
  viewport: {width: 1440, height: 1000},
  locale: 'zh-HK',
  userAgent: 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36'
});

const visited = new Set();
const queue = seeds.map(url => ({url, depth:0}));
const results = [];
const interesting = /invest|report|annual|interim|announcement|financial|download|公告|報告|报告|年報|年报|中期|投資者|投资者|下載|下载/i;

function abs(raw, base) {
  if (!raw) return '';
  const text = String(raw).replace(/&amp;/g,'&');
  const m = text.match(/https?:\/\/[^'"\s<>]+/i) || text.match(/(?:\.\.\/|\.\/|\/)[^'"\s<>]+/i);
  const candidate = m ? m[0] : text;
  if (/^javascript:/i.test(candidate) && !m) return '';
  try { return new URL(candidate, base).href; } catch { return ''; }
}

while (queue.length && visited.size < 80) {
  const {url, depth} = queue.shift();
  if (!url || visited.has(url)) continue;
  visited.add(url);
  const page = await context.newPage();
  try {
    console.log('OPEN', depth, url);
    const res = await page.goto(url, {waitUntil:'domcontentloaded', timeout:120000});
    await page.waitForTimeout(2500);
    try { await page.waitForLoadState('networkidle', {timeout:15000}); } catch {}
    const title = await page.title();
    const body = (await page.locator('body').innerText()).replace(/\s+/g,' ').slice(0,5000);
    const links = await page.evaluate(() => [...document.querySelectorAll('a')].map(a => ({
      text:(a.innerText||a.textContent||'').replace(/\s+/g,' ').trim(),
      href:a.href||'', raw:a.getAttribute('href')||'', onclick:a.getAttribute('onclick')||'', title:a.getAttribute('title')||''
    })));
    const normalized = links.map(x => ({...x, url: abs(x.href,url)||abs(x.raw,url)||abs(x.onclick,url)})).filter(x=>x.url);
    const pdfs = normalized.filter(x => /\.pdf(?:$|[?#])/i.test(x.url));
    results.push({url, depth, status:res?.status()||null, title, body, pdfs, links: normalized.filter(x=>interesting.test(`${x.text} ${x.title} ${x.url}`)).slice(0,300)});
    for (const x of normalized) {
      if (depth >= 2) break;
      let u;
      try { u = new URL(x.url); } catch { continue; }
      const same = /(^|\.)sinofert\.com$/i.test(u.hostname);
      if (same && interesting.test(`${x.text} ${x.title} ${x.url}`) && !visited.has(x.url)) queue.push({url:x.url, depth:depth+1});
    }
  } catch (e) {
    results.push({url, depth, error:String(e)});
    console.error('ERR', url, e.message);
  } finally {
    await page.close();
  }
}

await browser.close();
await fs.mkdir('out_sinofert_discovery_20260903',{recursive:true});
await fs.writeFile('out_sinofert_discovery_20260903/links.json', JSON.stringify(results,null,2));
console.log('VISITED',visited.size,'PAGES');
for (const r of results) {
  for (const p of (r.pdfs||[])) console.log('PDF',r.url,'::',p.text,'::',p.url);
  for (const l of (r.links||[])) if (/年報|年报|annual report|中期業績|中期业绩|interim results/i.test(`${l.text} ${l.title}`)) console.log('KEY',r.url,'::',l.text,'::',l.url);
}
