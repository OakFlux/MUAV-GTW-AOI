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
  const selectors = [
    'button:has-text("Accept")',
    'a:has-text("Accept")',
    '[role="button"]:has-text("Accept")',
    'button:has-text("I Accept")',
    'a:has-text("I Accept")'
  ];

  for (const selector of selectors) {
    const candidates = page.locator(selector);
    const count = await candidates.count();
    for (let i = 0; i < count; i++) {
      const el = candidates.nth(i);
      const text = ((await el.innerText().catch(() => '')) || '').trim();
      if (!/^I?\s*Accept$/i.test(text)) continue;
      if (await el.isVisible().catch(() => false)) {
        await el.click({ force: true }).catch(() => {});
        await page.waitForTimeout(1500);
        break;
      }
    }
  }

  // Defensive cleanup if the consent handler is blocked by the page's scripts.
  await page.evaluate(() => {
    const titleNodes = Array.from(document.querySelectorAll('body *')).filter((el) => {
      const t = (el.textContent || '').trim();
      return t === 'DBS Research Disclaimer';
    });

    for (const title of titleNodes) {
      let node = title;
      let candidate = null;
      for (let depth = 0; depth < 8 && node && node !== document.body; depth++, node = node.parentElement) {
        const style = getComputedStyle(node);
        const rect = node.getBoundingClientRect();
        const text = (node.textContent || '');
        if (text.includes('DBS Research Disclaimer') && text.includes('Accept') &&
            (style.position === 'fixed' || style.position === 'absolute' || rect.width > innerWidth * 0.35)) {
          candidate = node;
        }
      }
      if (candidate && candidate !== document.body) candidate.remove();
    }

    // Remove fixed full-screen backdrops left behind after the dialog is removed.
    for (const el of Array.from(document.querySelectorAll('body *'))) {
      const style = getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      const z = Number.parseInt(style.zIndex || '0', 10) || 0;
      const coversScreen = rect.width >= innerWidth * 0.85 && rect.height >= innerHeight * 0.85;
      const mostlyEmpty = ((el.textContent || '').trim().length < 80);
      if (style.position === 'fixed' && coversScreen && z >= 10 && mostlyEmpty) el.remove();
    }

    document.documentElement.style.overflow = 'auto';
    document.body.style.overflow = 'auto';
    document.body.classList.remove('modal-open', 'overflow-hidden', 'no-scroll');
  });

  await page.waitForTimeout(500);
  const visible = await page.locator('text=DBS Research Disclaimer').evaluateAll((els) =>
    els.some((el) => {
      const s = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      return s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity || 1) > 0 && r.width > 0 && r.height > 0;
    })
  ).catch(() => false);
  if (visible) throw new Error('DBS Research Disclaimer dialog is still visible after dismissal');
}

for (const report of reports) {
  const page = await context.newPage();
  console.log(`Opening ${report.url}`);
  await page.goto(report.url, { waitUntil: 'domcontentloaded', timeout: 120000 });
  await page.waitForTimeout(5000);
  try { await page.waitForLoadState('networkidle', { timeout: 30000 }); } catch {}

  await dismissResearchDisclaimer(page);

  const title = (await page.title()).trim();
  const bodyText = (await page.locator('body').innerText()).replace(/\s+/g, ' ');
  if (!/K\.?\s*Wah International/i.test(bodyText) || bodyText.length < 2000) {
    throw new Error(`Page validation failed for ${report.url}; title=${title}; body chars=${bodyText.length}`);
  }

  await page.emulateMedia({ media: 'screen' });
  await page.addStyleTag({ content: `
    @media print {
      body { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; overflow: visible !important; }
      header, footer, nav, [class*="cookie" i], [id*="cookie" i], [class*="breadcrumb" i],
      [class*="chat" i], [class*="contact" i], [class*="related" i], [class*="offer" i],
      [class*="login" i], [class*="navigation" i], [class*="modal" i], [class*="overlay" i],
      [class*="backdrop" i], [role="dialog"] { display: none !important; }
      a { color: inherit !important; text-decoration: none !important; }
    }
  `});

  const pdfPath = path.join(pdfDir, report.filename);
  await page.pdf({
    path: pdfPath,
    format: 'A4',
    printBackground: true,
    preferCSSPageSize: false,
    displayHeaderFooter: true,
    headerTemplate: `<div style="font-size:8px;width:100%;text-align:center;color:#666;">DBS Research - K. Wah International (00173.HK) - ${report.date}</div>`,
    footerTemplate: '<div style="font-size:8px;width:100%;text-align:center;color:#777;"><span class="pageNumber"></span> / <span class="totalPages"></span></div>',
    margin: { top: '18mm', bottom: '16mm', left: '12mm', right: '12mm' }
  });

  const stat = await fs.stat(pdfPath);
  if (stat.size < 30000) throw new Error(`Generated PDF is unexpectedly small: ${pdfPath} (${stat.size})`);
  const head = Buffer.alloc(5);
  const fd = fsSync.openSync(pdfPath, 'r');
  fsSync.readSync(fd, head, 0, 5, 0);
  fsSync.closeSync(fd);
  if (head.toString('ascii') !== '%PDF-') throw new Error(`Invalid PDF signature: ${pdfPath}`);
  console.log(`Created ${pdfPath} (${stat.size} bytes)`);
  await page.close();
}

await browser.close();

const readme = [
  'K. Wah International Holdings Limited (00173.HK) - DBS Research Pack',
  '',
  'The files are print-to-PDF copies of publicly accessible official DBS research pages.',
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
