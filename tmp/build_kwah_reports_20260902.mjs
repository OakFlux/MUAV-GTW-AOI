import { chromium } from 'playwright';
import fs from 'node:fs/promises';
import fsSync from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

const reports = [
  {
    date: '2026-07-20',
    title: 'Company update - Strong residential sales drive balance sheet improvement',
    url: 'https://www.dbs.com.hk/treasures/aics/templatedata/article/recentdevelopment/data/en/DBSV/072026/173_HK_07202026.xml',
    filename: '01_DBS_KWah_International_Strong_residential_sales_20260720.pdf'
  },
  {
    date: '2026-01-26',
    title: 'Strong contracted sales',
    url: 'https://www.dbs.com.hk/treasures/aics/templatedata/article/recentdevelopment/data/en/DBSV/012026/173_HK_01262026.xml',
    filename: '02_DBS_KWah_International_Strong_contracted_sales_20260126.pdf'
  },
  {
    date: '2025-08-22',
    title: 'Development margin eroded',
    url: 'https://www.dbs.com.hk/treasures/aics/templatedata/article/recentdevelopment/data/en/DBSV/082025/173_HK_08222025.xml',
    filename: '03_DBS_KWah_International_Development_margin_eroded_20250822.pdf'
  }
];

const outDir = path.resolve('out_kwah_20260902');
const pdfDir = path.join(outDir, 'reports');
await fs.rm(outDir, { recursive: true, force: true });
await fs.mkdir(pdfDir, { recursive: true });

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  userAgent: 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
});

async function dismissResearchDisclaimer(page) {
  const accept = page.locator('button, a, [role="button"]').filter({ hasText: /^\s*(?:I\s*)?Accept\s*$/i });
  for (let i = 0; i < await accept.count(); i++) {
    const el = accept.nth(i);
    if (await el.isVisible().catch(() => false)) {
      await el.click({ force: true }).catch(() => {});
      await page.waitForTimeout(1200);
      break;
    }
  }

  await page.evaluate(() => {
    const normalize = (s) => (s || '').replace(/\s+/g, ' ').trim();
    const titles = Array.from(document.querySelectorAll('body *')).filter((el) => normalize(el.textContent) === 'DBS Research Disclaimer');
    for (const title of titles) {
      let node = title;
      let removeNode = null;
      for (let depth = 0; depth < 9 && node && node !== document.body; depth++, node = node.parentElement) {
        const text = normalize(node.textContent);
        const style = getComputedStyle(node);
        const rect = node.getBoundingClientRect();
        if (text.includes('DBS Research Disclaimer') && text.includes('Accept') &&
            (style.position === 'fixed' || style.position === 'absolute' || rect.width > innerWidth * 0.35)) {
          removeNode = node;
        }
      }
      if (removeNode && removeNode !== document.body) removeNode.remove();
    }
    for (const el of Array.from(document.querySelectorAll('body *'))) {
      const style = getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      const z = Number.parseInt(style.zIndex || '0', 10) || 0;
      if (style.position === 'fixed' && rect.width >= innerWidth * 0.85 && rect.height >= innerHeight * 0.85 &&
          z >= 10 && normalize(el.textContent).length < 80) el.remove();
    }
    document.documentElement.style.overflow = 'auto';
    document.body.style.overflow = 'auto';
    document.body.classList.remove('modal-open', 'overflow-hidden', 'no-scroll');
  });
}

async function expandFullArticle(page) {
  for (let round = 0; round < 4; round++) {
    const controls = page.locator('a, button, [role="button"], span').filter({ hasText: /^\s*Read\s*More\s*$/i });
    let clicked = false;
    for (let i = 0; i < await controls.count(); i++) {
      const el = controls.nth(i);
      if (await el.isVisible().catch(() => false)) {
        await el.scrollIntoViewIfNeeded().catch(() => {});
        await el.click({ force: true }).catch(() => {});
        await page.waitForTimeout(900);
        clicked = true;
        break;
      }
    }
    if (!clicked) break;
  }
}

async function extractCleanArticle(page) {
  return await page.evaluate(() => {
    const normalize = (s) => (s || '').replace(/\s+/g, ' ').trim();
    const companyRe = /K\.?\s*Wah International/i;
    const nodes = Array.from(document.querySelectorAll('article, main, section, div'));
    const candidates = nodes.map((el) => ({
      el,
      text: normalize(el.textContent),
      visibleText: normalize(el.innerText)
    })).filter(({ text }) => companyRe.test(text) && text.length >= 3000 && text.length <= 30000);

    candidates.sort((a, b) => {
      const aNoise = /About Us|Quick Links|Web Conditions of Use/.test(a.text) ? 1 : 0;
      const bNoise = /About Us|Quick Links|Web Conditions of Use/.test(b.text) ? 1 : 0;
      return aNoise - bNoise || a.text.length - b.text.length;
    });

    const root = candidates[0]?.el || document.querySelector('main') || document.body;
    const sourceText = normalize(root.textContent);
    if (!companyRe.test(sourceText) || sourceText.length < 3000) {
      throw new Error(`Could not isolate full article; root text length=${sourceText.length}`);
    }

    const clone = root.cloneNode(true);
    clone.querySelectorAll('script, style, noscript, iframe, video, audio, canvas, nav, footer, form, input, textarea, select, button').forEach((el) => el.remove());

    const removeExact = [
      /^Read More$/i,
      /^Read Less$/i,
      /^Print$/i,
      /^Have a question\?$/i,
      /^Yes, Contact me$/i,
      /^Related Stories$/i,
      /^Market Insights$/i,
      /^Login$/i
    ];
    const removeStarts = [
      /^About Us$/i,
      /^Quick Links$/i,
      /^Other hotlines$/i,
      /^Web Conditions of Use$/i
    ];

    for (const el of Array.from(clone.querySelectorAll('*'))) {
      const text = normalize(el.textContent);
      if ((removeExact.some((re) => re.test(text)) || removeStarts.some((re) => re.test(text))) && text.length < 120) {
        const parent = el.parentElement;
        if (parent && normalize(parent.textContent).length < 500) parent.remove();
        else el.remove();
        continue;
      }
      el.removeAttribute('class');
      el.removeAttribute('id');
      el.removeAttribute('style');
      el.removeAttribute('hidden');
      el.removeAttribute('aria-hidden');
      el.removeAttribute('role');
      if (el.tagName === 'A') {
        el.removeAttribute('href');
        el.removeAttribute('target');
      }
      if (el.tagName === 'IMG') {
        const src = el.getAttribute('src') || '';
        if (!src || /logo|icon|arrow|social|avatar/i.test(src)) el.remove();
      }
    }

    // Remove tiny or empty remnants produced by the site's navigation widgets.
    for (const el of Array.from(clone.querySelectorAll('div, span, a'))) {
      const text = normalize(el.textContent);
      if (!text && el.querySelectorAll('img, table').length === 0) el.remove();
    }

    return {
      html: clone.innerHTML,
      text: sourceText,
      rootTag: root.tagName,
      rootLength: sourceText.length
    };
  });
}

for (const report of reports) {
  const sourcePage = await context.newPage();
  console.log(`Opening ${report.url}`);
  await sourcePage.goto(report.url, { waitUntil: 'domcontentloaded', timeout: 120000 });
  await sourcePage.waitForTimeout(4500);
  try { await sourcePage.waitForLoadState('networkidle', { timeout: 20000 }); } catch {}

  await dismissResearchDisclaimer(sourcePage);
  await expandFullArticle(sourcePage);
  const article = await extractCleanArticle(sourcePage);
  console.log(`Extracted article from ${article.rootTag}; ${article.rootLength} characters`);
  if (article.rootLength < 3000) throw new Error(`Article extraction too short for ${report.url}`);

  const printPage = await context.newPage();
  const cleanHtml = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><base href="${report.url}">
<style>
  @page { size: A4; margin: 16mm 14mm 17mm; }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; background: white; color: #1a1a1a; }
  body { font-family: Arial, Helvetica, sans-serif; font-size: 10.4pt; line-height: 1.52; }
  .source-banner { border-bottom: 2px solid #d62027; padding-bottom: 8px; margin-bottom: 18px; }
  .source-banner .brand { font-size: 9pt; color: #666; letter-spacing: .2px; }
  .source-banner h1 { font-size: 20pt; line-height: 1.2; margin: 5px 0 6px; color: #111; }
  .source-banner .meta { font-size: 9.5pt; color: #555; }
  #article h1, #article h2, #article h3, #article h4 { color: #202020; break-after: avoid; }
  #article h1 { font-size: 18pt; margin: 14px 0 8px; }
  #article h2 { font-size: 14pt; margin: 16px 0 7px; }
  #article h3, #article h4 { font-size: 11.5pt; margin: 13px 0 5px; }
  #article p { margin: 0 0 8px; orphans: 3; widows: 3; }
  #article ul, #article ol { margin: 5px 0 10px 21px; padding: 0; }
  #article li { margin: 0 0 4px; }
  #article table { width: 100%; border-collapse: collapse; font-size: 9pt; margin: 10px 0 14px; page-break-inside: auto; }
  #article th, #article td { border: 1px solid #c9c9c9; padding: 5px 6px; vertical-align: top; }
  #article th { background: #f0f0f0; }
  #article img { display: block; max-width: 100%; height: auto; margin: 8px auto; }
  #article br { line-height: 1.2; }
  #article a { color: inherit; text-decoration: none; }
  .source-note { margin-top: 16px; padding-top: 8px; border-top: 1px solid #bbb; font-size: 8.5pt; color: #666; }
</style></head><body>
<section class="source-banner">
  <div class="brand">DBS Equity Research - K. Wah International Holdings Limited (00173.HK)</div>
  <h1>${report.title.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')}</h1>
  <div class="meta">Publication date: ${report.date} | Official public DBS research page</div>
</section>
<main id="article">${article.html}</main>
<div class="source-note">Source preserved from the official DBS public research page. Copyright remains with DBS and the original publisher.</div>
</body></html>`;

  await printPage.setContent(cleanHtml, { waitUntil: 'domcontentloaded' });
  await printPage.waitForTimeout(1000);
  await printPage.evaluate(() => document.fonts?.ready);

  const printText = (await printPage.locator('body').innerText()).replace(/\s+/g, ' ').trim();
  if (!/K\.?\s*Wah International/i.test(printText) || printText.length < 3000) {
    throw new Error(`Clean print page validation failed; text chars=${printText.length}`);
  }

  const pdfPath = path.join(pdfDir, report.filename);
  await printPage.pdf({
    path: pdfPath,
    format: 'A4',
    printBackground: true,
    preferCSSPageSize: true,
    displayHeaderFooter: true,
    headerTemplate: '<div></div>',
    footerTemplate: '<div style="font-size:8px;width:100%;text-align:center;color:#777;"><span class="pageNumber"></span> / <span class="totalPages"></span></div>',
    margin: { top: '10mm', bottom: '14mm', left: '0mm', right: '0mm' }
  });

  const stat = await fs.stat(pdfPath);
  if (stat.size < 30000) throw new Error(`Generated PDF is unexpectedly small: ${pdfPath} (${stat.size})`);
  const head = Buffer.alloc(5);
  const fd = fsSync.openSync(pdfPath, 'r');
  fsSync.readSync(fd, head, 0, 5, 0);
  fsSync.closeSync(fd);
  if (head.toString('ascii') !== '%PDF-') throw new Error(`Invalid PDF signature: ${pdfPath}`);
  console.log(`Created ${pdfPath} (${stat.size} bytes, clean text ${printText.length} chars)`);

  await printPage.close();
  await sourcePage.close();
}

await browser.close();

const readme = [
  'K. Wah International Holdings Limited (00173.HK) - DBS Research Pack',
  '',
  'The files are clean print-to-PDF copies of publicly accessible official DBS research pages.',
  'The full article text was isolated from the official page, while navigation, consent overlays, and site chrome were removed.',
  'Retrieved: 2026-09-02',
  '',
  ...reports.map((r, i) => `${i + 1}. ${r.date} | DBS | ${r.title}\n   Source: ${r.url}`),
  '',
  'For personal investment research only. Copyright belongs to DBS and the respective publisher.',
  'This package does not constitute investment advice.'
].join('\n');
await fs.writeFile(path.join(pdfDir, 'README.txt'), readme, 'utf8');

const zipPath = path.join(outDir, 'KWah_International_00173_DBS_Research_3_reports.zip');
execFileSync('zip', ['-j', '-9', zipPath, ...reports.map(r => path.join(pdfDir, r.filename)), path.join(pdfDir, 'README.txt')], { stdio: 'inherit' });
console.log(`ZIP created: ${zipPath}`);
