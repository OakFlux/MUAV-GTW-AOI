import { chromium } from 'playwright';
import fs from 'node:fs/promises';
import fsSync from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const years = [2020, 2021, 2022, 2023, 2024, 2025];
const outDir = path.resolve('out_melco_international_20260903');
const reportDir = path.join(outDir, 'reports');
await fs.rm(outDir, { recursive: true, force: true });
await fs.mkdir(reportDir, { recursive: true });

const UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 1440, height: 1100 },
  locale: 'zh-HK',
  userAgent: UA,
});

function normalizeText(value) {
  return String(value || '').replace(/\s+/g, ' ').trim();
}

function extractUrl(raw, baseUrl) {
  if (!raw) return '';
  const decoded = raw.replace(/&amp;/g, '&');
  const match = decoded.match(/https?:\/\/[^'"\s<>]+\.pdf(?:\?[^'"\s<>]*)?/i)
    || decoded.match(/(?:\.\.\/|\.\/|\/)[^'"\s<>]+\.pdf(?:\?[^'"\s<>]*)?/i);
  const candidate = match ? match[0] : decoded;
  if (/^javascript:/i.test(candidate) && !match) return '';
  try { return new URL(candidate, baseUrl).href; } catch { return ''; }
}

async function collectLinks(pageUrl) {
  const page = await context.newPage();
  console.log(`Loading index: ${pageUrl}`);
  await page.goto(pageUrl, { waitUntil: 'domcontentloaded', timeout: 120000 });
  await page.waitForTimeout(3500);
  try { await page.waitForLoadState('networkidle', { timeout: 20000 }); } catch {}
  await page.evaluate(async () => {
    const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
    for (let y = 0; y < Math.min(document.documentElement.scrollHeight, 15000); y += 800) {
      window.scrollTo(0, y);
      await delay(70);
    }
    window.scrollTo(0, 0);
  });
  const rows = await page.evaluate(() => [...document.querySelectorAll('a')].map((a, index) => {
    const parent = a.closest('tr, li, article, section, .item, .row, .report, .news, .list-item') || a.parentElement;
    return {
      index,
      text: (a.innerText || a.textContent || '').replace(/\s+/g, ' ').trim(),
      parentText: (parent?.innerText || parent?.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 1000),
      href: a.href || '',
      rawHref: a.getAttribute('href') || '',
      onclick: a.getAttribute('onclick') || '',
      title: a.getAttribute('title') || '',
    };
  }));
  await page.close();
  return rows.map(row => {
    const url = extractUrl(row.href, pageUrl)
      || extractUrl(row.rawHref, pageUrl)
      || extractUrl(row.onclick, pageUrl);
    return {
      ...row,
      pageUrl,
      url,
      combined: normalizeText(`${row.text} ${row.title} ${row.parentText}`),
    };
  }).filter(row => row.url);
}

function chineseYear(year) {
  const map = { '0': '零', '1': '一', '2': '二', '3': '三', '4': '四', '5': '五', '6': '六', '7': '七', '8': '八', '9': '九' };
  return String(year).split('').map(d => map[d]).join('');
}

function selectAnnual(links, year) {
  const cy = chineseYear(year);
  const patterns = [
    `${year}年年報`, `${year}年年报`, `${cy}年年報`, `${cy}年年报`,
    `${year} Annual Report`, `Annual Report ${year}`,
  ];
  const candidates = links.map(item => {
    const text = item.combined;
    const lower = text.toLowerCase();
    let score = 0;
    if (patterns.some(pattern => lower.includes(pattern.toLowerCase()))) score += 500;
    if (String(item.text).includes(String(year))) score += 80;
    if (/年報|年报|annual report/i.test(text)) score += 100;
    if (/\.pdf(?:$|\?)/i.test(item.url)) score += 100;
    if (/\/tc\//i.test(item.pageUrl)) score += 30;
    if (/中期|interim|環境|环境|esg|sustainability|notification|通知|通函|circular/i.test(text)) score -= 700;
    return { ...item, score };
  }).filter(item => item.score >= 500).sort((a, b) => b.score - a.score);
  if (!candidates.length) {
    throw new Error(`No annual report link found for ${year}. Relevant links: ${links.filter(x => x.combined.includes(String(year))).slice(0, 20).map(x => `${x.combined} -> ${x.url}`).join('\n')}`);
  }
  return candidates[0];
}

function selectLatestInterim(links) {
  const candidates = links.map(item => {
    const text = item.combined;
    let score = 0;
    if (/截至二零二六年六月三十日止六個月之中期業績/.test(text)) score += 700;
    if (/interim results for the six months ended 30 june 2026/i.test(text)) score += 700;
    if (/31\/08\/2026/.test(text)) score += 100;
    if (/中期業績|interim results/i.test(text)) score += 120;
    if (/\.pdf(?:$|\?)/i.test(item.url)) score += 80;
    if (/上市附屬公司|listed subsidiary|melco resorts|second quarter|第二季度/i.test(text)) score -= 900;
    return { ...item, score };
  }).filter(item => item.score >= 700).sort((a, b) => b.score - a.score);
  if (!candidates.length) throw new Error('No valid 2026 parent-company interim-results link found.');
  return candidates[0];
}

async function fetchPdf(url, referer) {
  const headers = {
    'User-Agent': UA,
    'Accept': 'application/pdf,application/octet-stream;q=0.9,*/*;q=0.5',
    'Referer': referer,
  };
  let response = await context.request.get(url, { headers, timeout: 180000, failOnStatusCode: false });
  let body = await response.body();
  if (!response.ok() || body.subarray(0, 5).toString('ascii') !== '%PDF-') {
    console.log(`Direct request returned ${response.status()} for ${url}; retrying through browser page.`);
    const page = await context.newPage();
    const browserResponse = await page.goto(url, { waitUntil: 'load', timeout: 180000, referer });
    if (!browserResponse) throw new Error(`No response while opening ${url}`);
    body = await browserResponse.body();
    await page.close();
  }
  if (body.subarray(0, 5).toString('ascii') !== '%PDF-') {
    throw new Error(`Downloaded content is not a PDF: ${url}; bytes=${body.length}`);
  }
  if (body.length < 150000) throw new Error(`PDF unexpectedly small: ${url}; bytes=${body.length}`);
  return body;
}

const reportLinks = [
  ...(await collectLinks('https://www.melco-group.com/tc/Reports.html')),
  ...(await collectLinks('https://www.melco-group.com/en/Reports.html')),
];
const announcementLinks = [
  ...(await collectLinks('https://www.melco-group.com/tc/Announcements.html')),
  ...(await collectLinks('https://www.melco-group.com/en/Announcements.html')),
  ...(await collectLinks('https://www1.hkexnews.hk/search/titlesearch.xhtml?category=0&market=SEHK&stockId=354')),
];

const manifest = [];
for (let i = 0; i < years.length; i++) {
  const year = years[i];
  const selected = selectAnnual(reportLinks, year);
  console.log(`Selected ${year}: ${selected.combined} -> ${selected.url}`);
  const body = await fetchPdf(selected.url, selected.pageUrl);
  const filename = `${String(i + 1).padStart(2, '0')}_新濠国际发展_${year}年年度报告.pdf`;
  const dest = path.join(reportDir, filename);
  await fs.writeFile(dest, body);
  manifest.push({
    type: 'annual_report', year, filename, source_url: selected.url,
    index_page: selected.pageUrl, bytes: body.length,
    sha256: crypto.createHash('sha256').update(body).digest('hex'),
  });
}

const interim = selectLatestInterim(announcementLinks);
console.log(`Selected latest interim: ${interim.combined} -> ${interim.url}`);
const interimBody = await fetchPdf(interim.url, interim.pageUrl);
const interimFilename = '07_新濠国际发展_2026年中期业绩_截至2026年6月30日.pdf';
await fs.writeFile(path.join(reportDir, interimFilename), interimBody);
manifest.push({
  type: 'latest_interim_results', period_end: '2026-06-30', publication_date: '2026-08-31',
  filename: interimFilename, source_url: interim.url, index_page: interim.pageUrl,
  bytes: interimBody.length,
  sha256: crypto.createHash('sha256').update(interimBody).digest('hex'),
});

const readme = `新濠国际发展有限公司（00200.HK）财务报告合集\n\n内容：\n- 2020年至2025年年度报告，共6份；\n- 截至2026年6月30日止六个月的2026年中期业绩公告，共1份。\n\n说明：\n新濠国际发展为香港上市公司，母公司通常披露年度报告和中期报告，并不按A股模式发布普通季度报告。截至2026年9月3日，最新母公司定期财务披露为2026年8月31日发布的2026年中期业绩公告。本合集未以其上市附属公司新濠博亚娱乐的季度业绩替代母公司报告。\n\n来源：新濠国际发展官方网站及香港交易所披露易。\n仅供个人研究使用，版权归公司及原发布机构所有。\n`;
await fs.writeFile(path.join(reportDir, 'README_文件说明.txt'), readme, 'utf8');
await fs.writeFile(path.join(reportDir, '文件清单与校验值.json'), JSON.stringify(manifest, null, 2), 'utf8');

await browser.close();

const pdfFiles = (await fs.readdir(reportDir)).filter(name => name.toLowerCase().endsWith('.pdf'));
if (pdfFiles.length !== 7) throw new Error(`Expected 7 PDFs, got ${pdfFiles.length}`);
for (const name of pdfFiles) {
  const p = path.join(reportDir, name);
  const head = Buffer.alloc(5);
  const fd = fsSync.openSync(p, 'r');
  fsSync.readSync(fd, head, 0, 5, 0);
  fsSync.closeSync(fd);
  if (head.toString('ascii') !== '%PDF-') throw new Error(`Invalid PDF signature: ${name}`);
}
console.log(`READY: ${pdfFiles.length} PDFs; total bytes=${manifest.reduce((sum, x) => sum + x.bytes, 0)}`);
