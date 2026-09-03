import { chromium } from 'playwright';
import fs from 'node:fs/promises';
import fsSync from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const outDir = path.resolve('out_melco_international_20260903');
const reportDir = path.join(outDir, 'reports');
await fs.rm(outDir, { recursive: true, force: true });
await fs.mkdir(reportDir, { recursive: true });

const UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';
const annualReports = [
  {
    year: 2020,
    url: 'https://www1.hkexnews.hk/listedco/listconews/sehk/2021/0427/2021042701623_c.pdf',
    indexPage: 'https://www.melco-group.com/tc/Reports.html',
  },
  {
    year: 2021,
    url: 'https://www.melco-group.com/doc/c0200_220417_ar.pdf',
    indexPage: 'https://www.melco-group.com/tc/Reports.html',
  },
  {
    year: 2022,
    url: 'https://www.melco-group.com/doc/MI-2022AR-tc.pdf',
    indexPage: 'https://www.melco-group.com/tc/Reports.html',
  },
  {
    year: 2023,
    url: 'https://www.melco-group.com/doc/MI-2023AR-tc.pdf',
    indexPage: 'https://www.melco-group.com/tc/Reports.html',
  },
  {
    year: 2024,
    url: 'https://www.melco-group.com/doc/MI-2024AR-tc.pdf',
    indexPage: 'https://www.melco-group.com/tc/Reports.html',
  },
  {
    year: 2025,
    url: 'https://www.melco-group.com/doc/MI-2025AR-tc.pdf',
    indexPage: 'https://www.melco-group.com/tc/Reports.html',
  },
];

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 1440, height: 1100 },
  locale: 'zh-HK',
  userAgent: UA,
});

function normalize(value) {
  return String(value || '').replace(/\s+/g, ' ').trim();
}

function absolutePdf(raw, baseUrl) {
  if (!raw) return '';
  const decoded = raw.replace(/&amp;/g, '&');
  const match = decoded.match(/https?:\/\/[^'"\s<>]+\.pdf(?:\?[^'"\s<>]*)?/i)
    || decoded.match(/(?:\.\.\/|\.\/|\/)[^'"\s<>]+\.pdf(?:\?[^'"\s<>]*)?/i);
  const candidate = match ? match[0] : decoded;
  if (/^javascript:/i.test(candidate) && !match) return '';
  try { return new URL(candidate, baseUrl).href; } catch { return ''; }
}

async function collectAnnouncementLinks(pageUrl) {
  const page = await context.newPage();
  console.log(`Loading announcements: ${pageUrl}`);
  await page.goto(pageUrl, { waitUntil: 'domcontentloaded', timeout: 120000 });
  await page.waitForTimeout(3500);
  try { await page.waitForLoadState('networkidle', { timeout: 20000 }); } catch {}
  const links = await page.evaluate(() => [...document.querySelectorAll('a')].map(a => {
    const parent = a.closest('tr, li, .item, .row, .news, .list-item') || a.parentElement;
    return {
      text: (a.innerText || a.textContent || '').replace(/\s+/g, ' ').trim(),
      title: (a.getAttribute('title') || '').replace(/\s+/g, ' ').trim(),
      href: a.href || '',
      rawHref: a.getAttribute('href') || '',
      onclick: a.getAttribute('onclick') || '',
      parentText: (parent?.innerText || parent?.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 500),
    };
  }));
  await page.close();
  return links.map(item => ({
    ...item,
    pageUrl,
    anchorText: normalize(`${item.text} ${item.title}`),
    url: absolutePdf(item.href, pageUrl)
      || absolutePdf(item.rawHref, pageUrl)
      || absolutePdf(item.onclick, pageUrl),
  })).filter(item => item.url && /\.pdf(?:$|\?)/i.test(item.url));
}

function selectLatestParentInterim(items) {
  const ranked = items.map(item => {
    const anchor = item.anchorText;
    let score = 0;
    if (/截至二零二六年六月三十日止六個月之中期業績/.test(anchor)) score += 2000;
    if (/interim results for the six months ended 30 june 2026/i.test(anchor)) score += 2000;
    if (/中期業績|interim results/i.test(anchor)) score += 150;
    if (/31\/08\/2026/.test(item.parentText)) score += 100;
    if (/上市附屬公司|listed subsidiary|melco resorts|second quarter|第二季度/i.test(anchor)) score -= 3000;
    return { ...item, score };
  }).filter(item => item.score >= 2000).sort((a, b) => b.score - a.score);
  if (!ranked.length) {
    const relevant = items.filter(item => /2026|二零二六|interim|中期/i.test(`${item.anchorText} ${item.parentText}`));
    throw new Error(`No parent-company 2026 interim results PDF found. Candidates:\n${relevant.map(x => `${x.anchorText} | ${x.parentText} -> ${x.url}`).join('\n')}`);
  }
  return ranked[0];
}

async function fetchPdf(url, referer) {
  const headers = {
    'User-Agent': UA,
    'Accept': 'application/pdf,application/octet-stream;q=0.9,*/*;q=0.5',
    'Referer': referer,
  };
  let response = await context.request.get(url, { headers, timeout: 240000, failOnStatusCode: false });
  let body = await response.body();
  if (!response.ok() || body.subarray(0, 5).toString('ascii') !== '%PDF-') {
    console.log(`Direct request returned ${response.status()} for ${url}; retrying through Chromium.`);
    const page = await context.newPage();
    const browserResponse = await page.goto(url, { waitUntil: 'load', timeout: 240000, referer });
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

const manifest = [];
for (let index = 0; index < annualReports.length; index++) {
  const report = annualReports[index];
  console.log(`Downloading ${report.year} annual report: ${report.url}`);
  const body = await fetchPdf(report.url, report.indexPage);
  const filename = `${String(index + 1).padStart(2, '0')}_新濠国际发展_${report.year}年年度报告.pdf`;
  await fs.writeFile(path.join(reportDir, filename), body);
  manifest.push({
    type: 'annual_report',
    year: report.year,
    filename,
    source_url: report.url,
    index_page: report.indexPage,
    bytes: body.length,
    sha256: crypto.createHash('sha256').update(body).digest('hex'),
  });
}

const announcementLinks = [
  ...(await collectAnnouncementLinks('https://www.melco-group.com/tc/Announcements.html')),
  ...(await collectAnnouncementLinks('https://www.melco-group.com/en/Announcements.html')),
];
const interim = selectLatestParentInterim(announcementLinks);
console.log(`Downloading latest parent-company interim results: ${interim.anchorText} -> ${interim.url}`);
const interimBody = await fetchPdf(interim.url, interim.pageUrl);
const interimFilename = '07_新濠国际发展_2026年中期业绩_截至2026年6月30日.pdf';
await fs.writeFile(path.join(reportDir, interimFilename), interimBody);
manifest.push({
  type: 'latest_interim_results',
  period_end: '2026-06-30',
  publication_date: '2026-08-31',
  filename: interimFilename,
  source_url: interim.url,
  index_page: interim.pageUrl,
  bytes: interimBody.length,
  sha256: crypto.createHash('sha256').update(interimBody).digest('hex'),
});

const readme = `新濠国际发展有限公司（00200.HK）财务报告合集\n\n内容：\n- 2020年至2025年年度报告，共6份；\n- 截至2026年6月30日止六个月的2026年中期业绩公告，共1份。\n\n说明：\n新濠国际发展为香港上市公司，母公司通常披露年度报告和中期报告，并不按A股模式发布普通季度报告。截至2026年9月3日，最新母公司定期财务披露为2026年8月31日发布的2026年中期业绩公告。本合集没有以其上市附属公司新濠博亚娱乐的季度业绩替代母公司报告。\n\n来源：新濠国际发展官方网站及香港交易所披露易。\n仅供个人研究使用，版权归公司及原发布机构所有。\n`;
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
console.log(`READY: ${pdfFiles.length} PDFs; total bytes=${manifest.reduce((sum, item) => sum + item.bytes, 0)}`);
