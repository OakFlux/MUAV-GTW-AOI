import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const OUT = path.resolve('out_hangyan_china_tower_resolve');
const PDFDIR = path.join(OUT, 'pdfs');
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(PDFDIR, { recursive: true });

const query = '中国铁塔';
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131 Safari/537.36',
  locale: 'zh-CN',
  viewport: { width: 1440, height: 1200 },
  acceptDownloads: true,
});

const discovered = [];

async function collectPage(pageNo) {
  const page = await context.newPage();
  const url = `https://www.hangyan.co/reports?q=${encodeURIComponent(query)}&page=${pageNo}`;
  console.log('COLLECT', pageNo, url);
  try {
    const response = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 90000 });
    console.log('COLLECT_NAV', pageNo, response?.status(), page.url(), await page.title());
    await page.waitForTimeout(5000);
    const body = await page.locator('body').innerText().catch(() => '');
    fs.writeFileSync(path.join(OUT, `list_${pageNo}.txt`), body);
    fs.writeFileSync(path.join(OUT, `list_${pageNo}.html`), await page.content());
    const cards = await page.locator('#infinite-entries > div').evaluateAll((nodes, pageNoValue) => nodes.map((node, index) => {
      const a = node.querySelector('a[data-controller="protected-link"]');
      return {
        pageNo: pageNoValue,
        index,
        text: (node.innerText || '').trim(),
        title: (a?.innerText || a?.textContent || '').trim(),
        token: a?.getAttribute('data-protected-link-token-value') || '',
        outer: node.outerHTML.slice(0, 12000),
      };
    }), pageNo);
    console.log('CARD_COUNT', pageNo, cards.length);
    for (const card of cards) {
      if (/中国铁塔|中國鐵塔|China Tower|00788|0788\.HK/i.test(`${card.title} ${card.text}`)) {
        discovered.push(card);
        console.log('CARD_MATCH', JSON.stringify({pageNo: card.pageNo, index: card.index, title: card.title, text: card.text.slice(0, 1000), token: card.token}));
      }
    }
    return { cards: cards.length, body };
  } catch (error) {
    console.log('COLLECT_ERR', pageNo, String(error));
    return { cards: 0, body: '' };
  } finally {
    await page.close();
  }
}

for (let pageNo = 1; pageNo <= 12; pageNo++) {
  const result = await collectPage(pageNo);
  if (pageNo > 1 && result.cards === 0) break;
  if (pageNo > 1 && !/中国铁塔|中國鐵塔|China Tower|00788|0788\.HK/i.test(result.body)) break;
}

// Deduplicate title/token pairs.
const cards = [...new Map(discovered.map(x => [`${x.title}|${x.token}`, x])).values()];
fs.writeFileSync(path.join(OUT, 'discovered_cards.json'), JSON.stringify(cards, null, 2));
console.log('DISCOVERED_UNIQUE', cards.length);

const reportUrls = new Map();
const resolutionLog = [];

async function resolveCard(card, sequence) {
  const page = await context.newPage();
  const listUrl = `https://www.hangyan.co/reports?q=${encodeURIComponent(query)}&page=${card.pageNo}`;
  const requests = [];
  let popup = null;
  page.on('request', req => {
    const u = req.url();
    if (/protected|reports|login|redirect/i.test(u)) requests.push({type:'request',method:req.method(),url:u,postData:req.postData()});
  });
  page.on('response', async resp => {
    const u = resp.url();
    if (/protected|reports|login|redirect/i.test(u)) {
      const h = await resp.allHeaders().catch(() => ({}));
      requests.push({type:'response',status:resp.status(),url:u,location:h.location || '',contentType:h['content-type'] || ''});
    }
  });
  page.on('popup', p => { popup = p; });
  try {
    await page.goto(listUrl, { waitUntil: 'domcontentloaded', timeout: 90000 });
    await page.waitForTimeout(2500);
    const candidates = page.locator('a[data-controller="protected-link"]');
    const count = await candidates.count();
    let targetIndex = -1;
    for (let i = 0; i < count; i++) {
      const token = await candidates.nth(i).getAttribute('data-protected-link-token-value');
      const text = ((await candidates.nth(i).innerText().catch(() => '')) || '').trim();
      if ((card.token && token === card.token) || (card.title && text === card.title)) {
        targetIndex = i;
        break;
      }
    }
    if (targetIndex < 0) throw new Error(`target anchor not found: ${card.title}`);
    const target = candidates.nth(targetIndex);
    const before = page.url();
    await target.scrollIntoViewIfNeeded().catch(() => {});
    await target.click({ timeout: 8000, force: true });
    await page.waitForTimeout(6000);
    let after = page.url();
    if (popup) {
      await popup.waitForLoadState('domcontentloaded', { timeout: 10000 }).catch(() => {});
      after = popup.url();
    }
    const reportCandidates = [after, ...requests.map(r => r.url), ...requests.map(r => r.location)].filter(Boolean);
    const matched = reportCandidates.find(u => /https?:\/\/www\.hangyan\.co\/reports\/\d+/.test(u));
    if (matched) {
      const clean = matched.match(/https?:\/\/www\.hangyan\.co\/reports\/\d+/)?.[0];
      if (clean) reportUrls.set(clean, { source: 'resolved-card', card });
    }
    const modalText = await page.locator('#modal').innerText().catch(() => '');
    resolutionLog.push({sequence, card, before, after, matched: matched || '', modalText, requests});
    console.log('RESOLVED', sequence, card.title, before, after, matched || '', modalText.slice(0, 300));
  } catch (error) {
    resolutionLog.push({sequence, card, error: String(error), requests});
    console.log('RESOLVE_ERR', sequence, card.title, String(error));
  } finally {
    if (popup) await popup.close().catch(() => {});
    await page.close();
  }
}

for (let i = 0; i < cards.length; i++) {
  await resolveCard(cards[i], i + 1);
}

// Known publicly indexed China Tower report pages are safe fallbacks.
for (const [url, title] of [
  ['https://www.hangyan.co/reports/3485236846772881072', '一体两翼营收稳定，利润提升支撑分红增长'],
  ['https://www.hangyan.co/reports/3429851902681023749', '中国铁塔2024年中期业绩点评报告：业绩符合预期，首次中期派息'],
]) {
  reportUrls.set(url, { source: 'public-index-fallback', card: {title, text: title} });
}

fs.writeFileSync(path.join(OUT, 'resolution_log.json'), JSON.stringify(resolutionLog, null, 2));
fs.writeFileSync(path.join(OUT, 'resolved_report_urls.json'), JSON.stringify([...reportUrls.entries()], null, 2));
console.log('REPORT_URL_COUNT', reportUrls.size);

const downloaded = [];
let seq = 0;
for (const [reportUrl, origin] of reportUrls.entries()) {
  seq += 1;
  const page = await context.newPage();
  const pdfResponses = [];
  page.on('response', async resp => {
    const h = await resp.allHeaders().catch(() => ({}));
    if (/\.pdf(?:\?|$)/i.test(resp.url()) || /application\/pdf/i.test(h['content-type'] || '')) {
      pdfResponses.push({url: resp.url(), status: resp.status(), headers: h});
    }
  });
  try {
    const nav = await page.goto(reportUrl, { waitUntil: 'domcontentloaded', timeout: 90000 });
    await page.waitForTimeout(5000);
    const html = await page.content();
    const bodyText = await page.locator('body').innerText().catch(() => '');
    const h1 = ((await page.locator('h1').first().innerText().catch(() => '')) || '').trim();
    const iframeSrc = await page.locator('iframe[src*=".pdf"]').first().getAttribute('src').catch(() => null);
    const filename = await page.locator('[data-native-pdf-filename-value]').first().getAttribute('data-native-pdf-filename-value').catch(() => null);
    const pdfUrls = new Set();
    if (iframeSrc) pdfUrls.add(new URL(iframeSrc, reportUrl).href);
    for (const item of pdfResponses) if (item.status === 200) pdfUrls.add(item.url);
    for (const match of html.matchAll(/https?:\/\/cdn\.hangyan\.co\/documents\/[^"'<>\s]+\.pdf(?:\?[^"'<>\s]*)?/gi)) pdfUrls.add(match[0].replace(/&amp;/g, '&'));
    console.log('DETAIL', seq, nav?.status(), reportUrl, h1, filename || '', [...pdfUrls]);
    fs.writeFileSync(path.join(OUT, `detail_${seq}.html`), html);
    fs.writeFileSync(path.join(OUT, `detail_${seq}.txt`), bodyText);
    for (const pdfUrl of pdfUrls) {
      try {
        const response = await context.request.get(pdfUrl, { timeout: 120000, headers: {Referer: reportUrl, Accept: 'application/pdf,*/*'} });
        const buffer = await response.body();
        console.log('PDF_GET', response.status(), response.headers()['content-type'], buffer.length, pdfUrl);
        if (response.status() === 200 && buffer.length > 50000 && buffer.subarray(0,5).toString() === '%PDF-') {
          const safe = `${String(seq).padStart(2,'0')}_${reportUrl.split('/').pop()}_${(filename || 'report.pdf').replace(/[\\/:*?"<>|]/g,'_')}`;
          const outPath = path.join(PDFDIR, safe.endsWith('.pdf') ? safe : `${safe}.pdf`);
          fs.writeFileSync(outPath, buffer);
          downloaded.push({reportUrl, h1, filename, pdfUrl, outPath, bytes: buffer.length, bodyText: bodyText.slice(0, 10000), origin});
          break;
        }
      } catch (error) {
        console.log('PDF_GET_ERR', pdfUrl, String(error));
      }
    }
  } catch (error) {
    console.log('DETAIL_ERR', reportUrl, String(error));
  } finally {
    await page.close();
  }
}

fs.writeFileSync(path.join(OUT, 'downloaded_raw.json'), JSON.stringify(downloaded, null, 2));
console.log('DOWNLOADED_COUNT', downloaded.length);
await browser.close();
