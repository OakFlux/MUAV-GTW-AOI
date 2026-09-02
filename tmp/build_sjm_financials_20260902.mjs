import { chromium } from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import { execFileSync } from 'node:child_process';

const REPORTS_ZH = 'https://www.sjmholdings.com/zh/%E6%8A%95%E8%B3%87%E8%80%85%E9%97%9C%E4%BF%82/%E8%B2%A1%E5%8B%99%E5%A0%B1%E5%91%8A';
const REPORTS_EN = 'https://www.sjmholdings.com/en/investor-relations/financial-reports';
const ANNOUNCEMENTS_ZH = 'https://www.sjmholdings.com/zh/%E6%8A%95%E8%B3%87%E8%80%85%E9%97%9C%E4%BF%82/%E5%85%AC%E5%91%8A%E9%80%9A%E5%91%8A%E5%8F%8A%E5%A0%B1%E8%A1%A8';
const ANNOUNCEMENTS_EN = 'https://www.sjmholdings.com/en/investor-relations/announcements-notices-returns';

const annualYears = [2020, 2021, 2022, 2023, 2024, 2025];
const outDir = path.resolve('out_sjm_financials_20260902');
const reportDir = path.join(outDir, 'reports');
await fs.rm(outDir, { recursive: true, force: true });
await fs.mkdir(reportDir, { recursive: true });

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 1440, height: 1100 },
  locale: 'zh-HK',
  userAgent: 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
});

async function dismissAndExpand(page) {
  const patterns = [/同意/, /接受/, /我知道了/, /關閉/, /关闭/, /繼續/, /继续/, /^More/i, /更多/];
  for (let round = 0; round < 12; round++) {
    let clicked = false;
    for (const pattern of patterns) {
      const candidates = page.getByText(pattern, { exact: false });
      const count = Math.min(await candidates.count(), 6);
      for (let i = 0; i < count; i++) {
        const loc = candidates.nth(i);
        try {
          if (await loc.isVisible({ timeout: 300 })) {
            const text = ((await loc.innerText().catch(() => '')) || '').trim();
            if (text.length < 80) {
              await loc.click({ timeout: 1200, force: true });
              await page.waitForTimeout(500);
              clicked = true;
            }
          }
        } catch {}
      }
    }
    if (!clicked) break;
  }
  await page.evaluate(() => {
    document.querySelectorAll('[class*="cookie" i],[id*="cookie" i],[class*="modal" i],[class*="popup" i],[class*="mask" i]').forEach(el => {
      const text = (el.innerText || '').replace(/\s+/g, ' ').trim();
      if (text.length < 700 || /同意|接受|隱私|隐私|cookie|登入|登录/.test(text)) el.remove();
    });
    document.documentElement.style.overflow = 'auto';
    document.body.style.overflow = 'auto';
  });
}

async function loadPage(url) {
  const page = await context.newPage();
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 120000 });
  await page.waitForTimeout(2500);
  try { await page.waitForLoadState('networkidle', { timeout: 20000 }); } catch {}
  await dismissAndExpand(page);
  await page.evaluate(async () => {
    const delay = ms => new Promise(r => setTimeout(r, ms));
    for (let y = 0; y <= document.documentElement.scrollHeight; y += 900) {
      window.scrollTo(0, y);
      await delay(80);
    }
    window.scrollTo(0, 0);
    await delay(250);
  });
  await dismissAndExpand(page);
  return page;
}

async function anchorRecords(page) {
  return await page.locator('a').evaluateAll(anchors => anchors.map(a => {
    let node = a;
    let contextText = (a.innerText || a.textContent || '').replace(/\s+/g, ' ').trim();
    for (let depth = 0; depth < 6 && node.parentElement; depth++) {
      node = node.parentElement;
      const t = (node.innerText || '').replace(/\s+/g, ' ').trim();
      if (t && t.length <= 500 && t.length > contextText.length) contextText = t;
    }
    const attrs = {};
    for (const attr of a.attributes) attrs[attr.name] = attr.value;
    let href = a.href || attrs['data-href'] || attrs['data-url'] || attrs['data-link'] || '';
    if ((!href || href === location.href || href.startsWith('javascript:')) && attrs.onclick) {
      const m = attrs.onclick.match(/https?:\/\/[^'"\s)]+|['"]([^'"]+\.pdf(?:\?[^'"]*)?)['"]/i);
      if (m) href = m[1] || m[0];
    }
    try { href = href ? new URL(href, location.href).href : ''; } catch {}
    return { href, text: (a.innerText || '').replace(/\s+/g, ' ').trim(), contextText, attrs };
  }));
}

function isPdfCandidate(record) {
  const h = record.href || '';
  return /\.pdf(?:$|[?#])/i.test(h) || /download|pdf/i.test(record.text || '') || /\.pdf/i.test(JSON.stringify(record.attrs || {}));
}

function pickAnnual(records, year) {
  const patterns = [
    new RegExp(`${year}\\s*年報`),
    new RegExp(`${year}\\s*年度報告`),
    new RegExp(`${year}\\s*Annual Report`, 'i')
  ];
  const candidates = records.filter(r => r.href && isPdfCandidate(r) && patterns.some(p => p.test(r.contextText)) && !/中期|Interim/i.test(r.contextText));
  candidates.sort((a, b) => {
    const ap = /\.pdf(?:$|[?#])/i.test(a.href) ? 1 : 0;
    const bp = /\.pdf(?:$|[?#])/i.test(b.href) ? 1 : 0;
    return bp - ap || a.contextText.length - b.contextText.length;
  });
  return candidates[0] || null;
}

function pickLatestInterim(records) {
  const exactPatterns = [
    /截至\s*2026\s*年\s*6\s*月\s*30\s*日止六個月中期業績公佈/,
    /2026.*中期業績公佈/,
    /Interim Results Announcement for the Six Months Ended 30 June 2026/i
  ];
  const candidates = records.filter(r => r.href && isPdfCandidate(r) && exactPatterns.some(p => p.test(r.contextText)));
  candidates.sort((a, b) => {
    const ap = /\.pdf(?:$|[?#])/i.test(a.href) ? 1 : 0;
    const bp = /\.pdf(?:$|[?#])/i.test(b.href) ? 1 : 0;
    return bp - ap || a.contextText.length - b.contextText.length;
  });
  return candidates[0] || null;
}

async function resolveLinks() {
  const annualMap = new Map();
  for (const sourcePage of [REPORTS_ZH, REPORTS_EN]) {
    const page = await loadPage(sourcePage);
    const records = await anchorRecords(page);
    console.log(`Financial page ${sourcePage}: ${records.length} anchors`);
    for (const year of annualYears) {
      if (annualMap.has(year)) continue;
      const hit = pickAnnual(records, year);
      if (hit) {
        annualMap.set(year, { ...hit, sourcePage });
        console.log(`Annual ${year}: ${hit.href} | ${hit.contextText}`);
      }
    }
    await page.close();
    if (annualMap.size === annualYears.length) break;
  }
  if (annualMap.size !== annualYears.length) {
    throw new Error(`Could not resolve all annual reports. Found years: ${[...annualMap.keys()].join(', ')}`);
  }

  let interim = null;
  for (const sourcePage of [ANNOUNCEMENTS_ZH, ANNOUNCEMENTS_EN]) {
    const page = await loadPage(sourcePage);
    const records = await anchorRecords(page);
    console.log(`Announcements page ${sourcePage}: ${records.length} anchors`);
    interim = pickLatestInterim(records);
    if (interim) {
      interim = { ...interim, sourcePage };
      console.log(`Latest interim: ${interim.href} | ${interim.contextText}`);
      await page.close();
      break;
    }
    await page.close();
  }
  if (!interim) throw new Error('Could not resolve 2026 interim results announcement');
  return { annualMap, interim };
}

async function downloadPdf(url, referer, dest) {
  const response = await context.request.get(url, {
    timeout: 300000,
    maxRedirects: 12,
    headers: {
      Referer: referer,
      Accept: 'application/pdf,application/octet-stream;q=0.9,*/*;q=0.8'
    }
  });
  if (!response.ok()) throw new Error(`HTTP ${response.status()} for ${url}`);
  const body = await response.body();
  const contentType = response.headers()['content-type'] || '';
  if (body.length < 100000) throw new Error(`Downloaded file too small (${body.length}) from ${url}`);
  if (body.subarray(0, 5).toString('ascii') !== '%PDF-') {
    throw new Error(`Not a PDF (${contentType}) from ${url}; prefix=${body.subarray(0, 40).toString('utf8')}`);
  }
  await fs.writeFile(dest, body);
  return {
    size: body.length,
    sha256: crypto.createHash('sha256').update(body).digest('hex'),
    finalUrl: response.url(),
    contentType
  };
}

const { annualMap, interim } = await resolveLinks();
const manifest = [];
let index = 1;
for (const year of annualYears) {
  const record = annualMap.get(year);
  const filename = `${String(index).padStart(2, '0')}_澳博控股_${year}年年度报告.pdf`;
  const dest = path.join(reportDir, filename);
  const info = await downloadPdf(record.href, record.sourcePage, dest);
  manifest.push({ filename, type: `${year}年年度报告`, sourcePage: record.sourcePage, sourceUrl: record.href, ...info });
  console.log(`Downloaded ${filename}: ${info.size} bytes`);
  index++;
}

const interimFilename = '07_澳博控股_2026年中期业绩公告_截至2026年6月30日.pdf';
const interimDest = path.join(reportDir, interimFilename);
const interimInfo = await downloadPdf(interim.href, interim.sourcePage, interimDest);
manifest.push({ filename: interimFilename, type: '2026年中期业绩公告（最新定期财务披露）', sourcePage: interim.sourcePage, sourceUrl: interim.href, ...interimInfo });
console.log(`Downloaded ${interimFilename}: ${interimInfo.size} bytes`);

await browser.close();

const readme = `澳博控股有限公司（00880.HK）财务报告合集\n\n内容：\n- 2020年至2025年年度报告，共6份；\n- 截至2026年6月30日止六个月的中期业绩公告，共1份。\n\n说明：\n澳博控股为香港上市公司。香港上市公司通常以年度报告、半年度中期报告/中期业绩公告为主要定期财务报告，并可自愿披露第一季度及第三季度经营指标。截至2026年9月2日，最新完整定期财务披露为2026年8月25日发布的2026年中期业绩公告，因此将其作为“最新季报/最新定期财务披露”收录。公司于2026年5月7日另行发布第一季度节选未经审核主要业务表现指标，但该披露期早于本次收录的中期业绩。\n\n来源：澳博控股官方网站。\n仅供个人研究使用，文件版权归澳博控股及原发布机构所有。\n`;
await fs.writeFile(path.join(reportDir, 'README_文件说明.txt'), readme, 'utf8');

const manifestText = manifest.map((m, i) => [
  `${i + 1}. ${m.filename}`,
  `   类型：${m.type}`,
  `   文件大小：${m.size} bytes`,
  `   SHA-256：${m.sha256}`,
  `   官方来源页：${m.sourcePage}`,
  `   PDF地址：${m.finalUrl || m.sourceUrl}`
].join('\n')).join('\n\n') + '\n';
await fs.writeFile(path.join(reportDir, '文件清单与校验值.txt'), manifestText, 'utf8');

const zipPath = path.join(outDir, 'SJM_Holdings_00880_2020_2025_Annual_Reports_2026_Interim.zip');
const files = (await fs.readdir(reportDir)).sort().map(name => path.join(reportDir, name));
execFileSync('zip', ['-j', '-9', zipPath, ...files], { stdio: 'inherit' });
console.log(`ZIP created: ${zipPath}`);
