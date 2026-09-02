import { chromium } from 'playwright';
import fs from 'node:fs/promises';
import fsSync from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

const reports = [
  {
    date: '2026-03-06',
    broker: '国金证券',
    title: '信义玻璃港股公司深度研究：浮法领先，汽玻加码',
    sources: [
      'https://finance.sina.com.cn/wm/2026-03-07/doc-inhqcymk1737606.shtml',
      'https://caifuhao.eastmoney.com/news/20260309150932596410230'
    ],
    filename: '01_国金证券_信义玻璃_浮法领先汽玻加码_20260306.pdf',
    minChars: 9000,
    minPages: 8
  },
  {
    date: '2021-06-28',
    broker: '天风证券',
    title: '全球领先综合玻璃龙头制造商，行业变革红利受益者',
    sources: [
      'https://finance.sina.cn/hkstock/gsxw/2021-06-28/detail-ikqcfnca3773995.d.html'
    ],
    filename: '02_天风证券_信义玻璃_全球领先综合玻璃龙头制造商_20210628.pdf',
    minChars: 12000,
    minPages: 10
  }
];

const outDir = path.resolve('out_xinyi_glass_20260902');
const pdfDir = path.join(outDir, 'reports');
await fs.rm(outDir, { recursive: true, force: true });
await fs.mkdir(pdfDir, { recursive: true });

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 1440, height: 1100 },
  deviceScaleFactor: 1,
  locale: 'zh-CN',
  userAgent: 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
});

async function dismissObstructions(page) {
  const clickPatterns = [/同意/, /接受/, /我知道了/, /关闭/, /继续访问/, /展开全文/, /阅读全文/, /查看更多/];
  for (const pattern of clickPatterns) {
    const loc = page.getByText(pattern, { exact: false }).first();
    try {
      if (await loc.isVisible({ timeout: 700 })) {
        await loc.click({ timeout: 1500, force: true });
        await page.waitForTimeout(400);
      }
    } catch {}
  }
  await page.evaluate(() => {
    const obstructionSelectors = [
      '[class*="cookie" i]', '[id*="cookie" i]', '[class*="consent" i]', '[id*="consent" i]',
      '[class*="modal" i]', '[class*="popup" i]', '[class*="mask" i]', '[class*="login" i]',
      '[class*="download-app" i]', '[class*="open-app" i]', '[class*="float" i]'
    ];
    for (const sel of obstructionSelectors) {
      document.querySelectorAll(sel).forEach(el => {
        const text = (el.innerText || '').replace(/\s+/g, ' ').trim();
        if (text.length < 500 || /登录|打开APP|下载|隐私|同意|广告/.test(text)) el.remove();
      });
    }
    document.documentElement.style.overflow = 'auto';
    document.body.style.overflow = 'auto';
  });
}

async function scrollAndLoad(page) {
  await page.evaluate(async () => {
    const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
    const height = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
    const step = Math.max(700, Math.floor(window.innerHeight * 0.8));
    for (let y = 0; y < height; y += step) {
      window.scrollTo(0, y);
      await delay(120);
    }
    window.scrollTo(0, 0);
    await delay(500);
  });
}

async function extractArticle(page) {
  return await page.evaluate(() => {
    const selectors = [
      '#artibody', '#article-content', '#articleContent', '#ContentBody',
      '.art_content', '.article-content', '.article__content', '.article-body',
      '.article_body', '.article-main', '.article', '.main-content',
      '.rich_media_content', '.content-detail', '.content', 'article'
    ];
    const candidates = [];
    const seen = new Set();
    for (const selector of selectors) {
      for (const node of document.querySelectorAll(selector)) {
        if (seen.has(node)) continue;
        seen.add(node);
        const text = (node.innerText || '').replace(/\s+/g, ' ').trim();
        const imgCount = node.querySelectorAll('img').length;
        if (text.length >= 1200) {
          let score = text.length + Math.min(imgCount, 100) * 120;
          if (node.id === 'artibody' || node.classList.contains('art_content')) score += 8000;
          candidates.push({ node, text, imgCount, score });
        }
      }
    }
    if (!candidates.length) {
      const node = document.body;
      const text = (node.innerText || '').replace(/\s+/g, ' ').trim();
      candidates.push({ node, text, imgCount: node.querySelectorAll('img').length, score: text.length });
    }
    candidates.sort((a, b) => b.score - a.score);
    const picked = candidates[0];
    const clone = picked.node.cloneNode(true);

    const removeSelectors = [
      'script', 'style', 'noscript', 'iframe', 'video', 'audio', 'form', 'button', 'nav',
      '[class*="share" i]', '[id*="share" i]', '[class*="comment" i]', '[id*="comment" i]',
      '[class*="recommend" i]', '[id*="recommend" i]', '[class*="related" i]', '[id*="related" i]',
      '[class*="advert" i]', '[id*="advert" i]', '[class*="ad-" i]', '[id^="ad" i]',
      '[class*="toolbar" i]', '[class*="footer" i]', '[class*="header" i]',
      '[class*="download" i]', '[class*="app" i]', '[class*="qrcode" i]'
    ];
    for (const sel of removeSelectors) clone.querySelectorAll(sel).forEach(el => el.remove());

    const usedImages = new Set();
    for (const img of [...clone.querySelectorAll('img')]) {
      let src = img.getAttribute('data-src') || img.getAttribute('data-original') ||
        img.getAttribute('data-lazyload') || img.getAttribute('data-actualsrc') ||
        img.getAttribute('data-url') || img.getAttribute('src') || '';
      if (!src || /^data:image\/gif/i.test(src) || /beacon|pixel|spacer|logo|avatar|qrcode/i.test(src)) {
        img.remove();
        continue;
      }
      try { src = new URL(src, location.href).href; } catch {}
      if (usedImages.has(src)) {
        img.remove();
        continue;
      }
      usedImages.add(src);
      img.setAttribute('src', src);
      img.removeAttribute('srcset');
      img.removeAttribute('data-src');
      img.removeAttribute('data-original');
      img.removeAttribute('data-lazyload');
      img.removeAttribute('data-actualsrc');
      img.removeAttribute('loading');
      img.setAttribute('referrerpolicy', 'no-referrer');
    }

    clone.querySelectorAll('a').forEach(a => {
      const span = document.createElement('span');
      span.innerHTML = a.innerHTML;
      a.replaceWith(span);
    });
    clone.querySelectorAll('*').forEach(el => {
      el.removeAttribute('onclick');
      el.removeAttribute('onload');
      el.removeAttribute('onerror');
      if (el.getAttribute('style')?.match(/display\s*:\s*none/i)) el.removeAttribute('style');
    });

    const title = (document.querySelector('h1')?.innerText || document.title || '').replace(/\s+/g, ' ').trim();
    const text = (clone.innerText || '').replace(/\s+/g, ' ').trim();
    return {
      title,
      html: clone.innerHTML,
      text,
      imageCount: clone.querySelectorAll('img').length,
      selectorHint: picked.node.id ? `#${picked.node.id}` : picked.node.className || picked.node.tagName
    };
  });
}

function cleanDocument(report, sourceUrl, extracted) {
  const escapeHtml = value => String(value).replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));
  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>${escapeHtml(report.title)}</title>
<style>
  @page { size: A4; margin: 18mm 14mm 17mm; }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: "Noto Sans CJK SC", "Source Han Sans SC", "Microsoft YaHei", Arial, sans-serif; color: #161616; background: #fff; }
  .cover { min-height: 245mm; display: flex; flex-direction: column; justify-content: center; border-top: 7px solid #202020; border-bottom: 1px solid #b8b8b8; page-break-after: always; }
  .cover .type { font-size: 14px; letter-spacing: 0.16em; color: #555; margin-bottom: 22px; }
  .cover h1 { font-size: 30px; line-height: 1.35; margin: 0 0 28px; font-weight: 700; }
  .cover .meta { font-size: 16px; line-height: 1.9; }
  .cover .note { margin-top: 42px; padding-top: 14px; border-top: 1px solid #ddd; color: #666; font-size: 10px; line-height: 1.6; }
  article { font-size: 11.2px; line-height: 1.72; overflow-wrap: anywhere; }
  article h1, article h2, article h3, article h4 { page-break-after: avoid; break-after: avoid; line-height: 1.4; color: #111; }
  article h1 { font-size: 22px; margin: 22px 0 12px; }
  article h2 { font-size: 17px; margin: 22px 0 9px; border-left: 4px solid #333; padding-left: 9px; }
  article h3 { font-size: 14px; margin: 18px 0 7px; }
  article p { margin: 0 0 9px; text-align: justify; }
  article img { display: block; max-width: 100%; height: auto; margin: 10px auto 13px; page-break-inside: avoid; break-inside: avoid; }
  article figure, article table, article blockquote { max-width: 100%; page-break-inside: avoid; break-inside: avoid; }
  article table { border-collapse: collapse; width: 100%; font-size: 9px; margin: 10px 0; }
  article td, article th { border: 1px solid #aaa; padding: 4px; }
  article br + br { display: none; }
  .source-footer { margin-top: 24px; border-top: 1px solid #aaa; padding-top: 8px; color: #666; font-size: 9px; line-height: 1.5; }
</style>
</head>
<body>
<section class="cover">
  <div class="type">券商公司深度研究 · 信义玻璃（00868.HK）</div>
  <h1>${escapeHtml(report.title)}</h1>
  <div class="meta"><strong>${escapeHtml(report.broker)}</strong><br>${escapeHtml(report.date)}</div>
  <div class="note">本文件根据公开可访问的券商研究全文转载页面制作清洁版 PDF，保留正文与公开图表，移除网页导航、广告及弹窗。报告观点、数据及版权归原研究机构和发布方所有，仅供个人研究使用，不构成投资建议。</div>
</section>
<article>${extracted.html}</article>
<div class="source-footer">公开来源页面：${escapeHtml(sourceUrl)}<br>整理日期：2026-09-02</div>
</body>
</html>`;
}

for (const report of reports) {
  let success = false;
  let lastError = null;
  for (const sourceUrl of report.sources) {
    const page = await context.newPage();
    try {
      console.log(`Opening ${sourceUrl}`);
      await page.goto(sourceUrl, { waitUntil: 'domcontentloaded', timeout: 120000 });
      await page.waitForTimeout(3500);
      try { await page.waitForLoadState('networkidle', { timeout: 20000 }); } catch {}
      await dismissObstructions(page);
      await scrollAndLoad(page);
      await dismissObstructions(page);

      const bodyText = (await page.locator('body').innerText()).replace(/\s+/g, ' ');
      if (!/信义玻璃|Xinyi Glass/i.test(bodyText)) throw new Error('Source page does not contain Xinyi Glass');

      const extracted = await extractArticle(page);
      console.log(`Selected ${extracted.selectorHint}; text=${extracted.text.length}; images=${extracted.imageCount}`);
      if (!/信义玻璃|Xinyi Glass/i.test(extracted.text)) throw new Error('Extracted article misses company name');
      if (extracted.text.length < report.minChars) throw new Error(`Article too short: ${extracted.text.length} < ${report.minChars}`);

      const cleanPage = await context.newPage();
      await cleanPage.setContent(cleanDocument(report, sourceUrl, extracted), { waitUntil: 'domcontentloaded', timeout: 120000 });
      await cleanPage.evaluate(async () => {
        const imgs = [...document.images];
        await Promise.all(imgs.map(img => {
          if (img.complete) return Promise.resolve();
          return new Promise(resolve => {
            const done = () => resolve();
            img.addEventListener('load', done, { once: true });
            img.addEventListener('error', done, { once: true });
            setTimeout(done, 12000);
          });
        }));
      });
      await cleanPage.waitForTimeout(1000);

      const pdfPath = path.join(pdfDir, report.filename);
      await cleanPage.pdf({
        path: pdfPath,
        format: 'A4',
        printBackground: true,
        preferCSSPageSize: true,
        displayHeaderFooter: true,
        headerTemplate: `<div style="font-size:8px;width:100%;text-align:center;color:#666;">${report.broker} · 信义玻璃（00868.HK）· ${report.date}</div>`,
        footerTemplate: '<div style="font-size:8px;width:100%;text-align:center;color:#777;"><span class="pageNumber"></span> / <span class="totalPages"></span></div>',
        margin: { top: '16mm', bottom: '15mm', left: '12mm', right: '12mm' }
      });
      await cleanPage.close();

      const stat = await fs.stat(pdfPath);
      const head = Buffer.alloc(5);
      const fd = fsSync.openSync(pdfPath, 'r');
      fsSync.readSync(fd, head, 0, 5, 0);
      fsSync.closeSync(fd);
      if (head.toString('ascii') !== '%PDF-') throw new Error(`Invalid PDF signature: ${pdfPath}`);
      if (stat.size < 120000) throw new Error(`PDF unexpectedly small: ${stat.size}`);
      console.log(`Created ${pdfPath} (${stat.size} bytes)`);
      success = true;
      await page.close();
      break;
    } catch (error) {
      lastError = error;
      console.error(`Failed source ${sourceUrl}:`, error);
      await page.close();
    }
  }
  if (!success) throw lastError || new Error(`No source worked for ${report.title}`);
}

await browser.close();

const readme = [
  '信义玻璃控股有限公司（00868.HK）券商深度报告合集',
  '',
  '1. 2026-03-06 | 国金证券 | 信义玻璃港股公司深度研究：浮法领先，汽玻加码',
  '   公开全文来源：https://finance.sina.com.cn/wm/2026-03-07/doc-inhqcymk1737606.shtml',
  '',
  '2. 2021-06-28 | 天风证券 | 全球领先综合玻璃龙头制造商，行业变革红利受益者',
  '   公开全文来源：https://finance.sina.cn/hkstock/gsxw/2021-06-28/detail-ikqcfnca3773995.d.html',
  '',
  '说明：公开网页未提供可直接下载的券商原始 PDF，本合集将公开全文和图表整理为清洁版 PDF，移除了网页导航、广告及弹窗。报告版权归原研究机构及发布方所有，仅供个人投资研究使用，不构成投资建议。',
  '整理日期：2026-09-02'
].join('\n');
await fs.writeFile(path.join(pdfDir, 'README.txt'), readme, 'utf8');

const zipPath = path.join(outDir, 'Xinyi_Glass_00868_Broker_Deep_Reports_2.zip');
execFileSync('zip', ['-j', '-9', zipPath, ...reports.map(r => path.join(pdfDir, r.filename)), path.join(pdfDir, 'README.txt')], { stdio: 'inherit' });
console.log(`ZIP created: ${zipPath}`);
