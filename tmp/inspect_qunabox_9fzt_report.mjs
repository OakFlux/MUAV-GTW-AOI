import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import crypto from 'crypto';

const OUT = path.resolve('out_qunabox_9fzt_report');
const DL = path.join(OUT, 'downloads');
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(DL, { recursive: true });

const targets = [
  ['boci', 'https://gmg.9fzt.com/report/HKSE/00917/790250427564.html'],
];
const interesting = /(pdf|download|file|attach|report|research|790250427564|00917|qunabox|趣致)/i;
const browser = await chromium.launch({ headless: true });
const saved = [];

async function savePdf(buffer, label, url, source) {
  if (!buffer || buffer.length < 50000 || buffer.subarray(0, 5).toString() !== '%PDF-') return;
  const sha = crypto.createHash('sha256').update(buffer).digest('hex');
  const file = path.join(DL, `${label}_${sha.slice(0,12)}.pdf`);
  if (!fs.existsSync(file)) fs.writeFileSync(file, buffer);
  const row = { label, url, source, file, bytes: buffer.length, sha256: sha };
  saved.push(row);
  console.log('PDF_SAVED', JSON.stringify(row));
}

for (const [label, url] of targets) {
  const context = await browser.newContext({
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36',
    locale: 'zh-CN',
    acceptDownloads: true,
    ignoreHTTPSErrors: true,
    viewport: { width: 1440, height: 1100 },
  });
  const page = await context.newPage();
  const events = [];
  const urls = new Set();
  page.on('request', req => {
    const u = req.url();
    if (interesting.test(u)) events.push({type:'request', method:req.method(), url:u, resourceType:req.resourceType(), postData:req.postData()});
  });
  page.on('response', async resp => {
    const u = resp.url();
    const h = await resp.allHeaders().catch(()=>({}));
    const ct = h['content-type'] || '';
    if (interesting.test(`${u} ${ct}`)) {
      const item = {type:'response', status:resp.status(), url:u, contentType:ct, headers:h};
      if (/json|text|html|javascript/i.test(ct)) {
        try {
          const text = await resp.text();
          item.preview = text.slice(0,50000);
          for (const m of text.matchAll(/https?:\\?\/\\?\/[^"'<>\\s]+/g)) {
            const clean=m[0].replaceAll('\\/','/').replace(/[),;]+$/,'');
            if (interesting.test(clean)) urls.add(clean);
          }
        } catch {}
      }
      events.push(item);
    }
    if (/application\/pdf|application\/octet-stream/i.test(ct) || /\.pdf(?:\?|$)/i.test(u)) {
      try { await savePdf(await resp.body(), `${label}_network`, u, 'network'); } catch (e) { console.log('BODY_ERR',u,String(e)); }
    }
  });
  page.on('download', async d => {
    try {
      const temp = path.join(DL, `${label}_${Date.now()}_${(d.suggestedFilename()||'download').replace(/[^A-Za-z0-9._-]+/g,'_')}`);
      await d.saveAs(temp);
      const body=fs.readFileSync(temp);
      await savePdf(body, `${label}_download`, d.url(), 'download');
      fs.unlinkSync(temp);
    } catch(e) { console.log('DOWNLOAD_ERR',String(e)); }
  });

  console.log('OPEN',url);
  try {
    const r = await page.goto(url,{waitUntil:'domcontentloaded',timeout:90000});
    await page.waitForTimeout(12000);
    console.log('PAGE',r?.status(),page.url(),await page.title());
    const html=await page.content();
    const text=await page.locator('body').innerText().catch(()=> '');
    fs.writeFileSync(path.join(OUT,`${label}.html`),html);
    fs.writeFileSync(path.join(OUT,`${label}.txt`),text);
    await page.screenshot({path:path.join(OUT,`${label}.png`),fullPage:true}).catch(()=>{});
    const dom=await page.evaluate(()=>({
      url:location.href,title:document.title,
      anchors:[...document.querySelectorAll('a')].map((a,i)=>({i,text:(a.innerText||a.textContent||'').trim(),href:a.href,download:a.download||'',outer:a.outerHTML.slice(0,3000)})),
      buttons:[...document.querySelectorAll('button,[role="button"],[onclick]')].map((b,i)=>({i,text:(b.innerText||b.textContent||'').trim(),onclick:b.getAttribute('onclick')||'',outer:b.outerHTML.slice(0,3000)})),
      scripts:[...document.scripts].map((s,i)=>({i,src:s.src,text:(s.textContent||'').slice(0,200000)})),
      iframes:[...document.querySelectorAll('iframe,embed,object')].map((e,i)=>({i,src:e.src||e.data||'',outer:e.outerHTML.slice(0,3000)})),
    }));
    fs.writeFileSync(path.join(OUT,`${label}_dom.json`),JSON.stringify(dom,null,2));
    for (const a of dom.anchors) if (interesting.test(`${a.text} ${a.href}`)) urls.add(a.href);
    for (const s of dom.scripts) {
      const blob=`${s.src}\n${s.text}`;
      for (const m of blob.matchAll(/https?:\\?\/\\?\/[^"'<>\\s]+/g)) {
        const clean=m[0].replaceAll('\\/','/').replace(/[),;]+$/,'');
        if (interesting.test(clean)) urls.add(clean);
      }
    }
    // Click only visible public download/view controls; no login/payment actions.
    for (const pat of [/下载PDF/i,/下载报告/i,/报告原文/i,/查看原文/i,/阅读全文/i]) {
      const locs=await page.getByText(pat).all().catch(()=>[]);
      for (const loc of locs.slice(0,3)) {
        try {
          if (!(await loc.isVisible())) continue;
          const before=page.url();
          const popupP=page.waitForEvent('popup',{timeout:3000}).catch(()=>null);
          await loc.click({timeout:5000});
          const popup=await popupP;
          await page.waitForTimeout(5000);
          console.log('CLICK',pat.toString(),before,'=>',page.url(),popup?popup.url():'no-popup');
          if (popup) { urls.add(popup.url()); await popup.close(); }
          if (page.url()!==before) { urls.add(page.url()); await page.goBack({waitUntil:'domcontentloaded',timeout:30000}).catch(()=>{}); }
        } catch {}
      }
    }
  } catch(e) { console.log('PAGE_ERR',String(e)); }

  for (const u of [...urls]) {
    if (!u || /^javascript:|^mailto:/.test(u) || /login|signin|register|pay|member|checkout/i.test(u)) continue;
    try {
      const r=await context.request.get(u,{timeout:45000,headers:{Referer:url}});
      const body=await r.body();
      const ct=r.headers()['content-type']||'';
      console.log('PROBE',r.status(),ct,body.length,u);
      await savePdf(body,`${label}_probe`,u,'public-exposed-url');
    } catch {}
  }
  fs.writeFileSync(path.join(OUT,`${label}_events.json`),JSON.stringify({events,urls:[...urls]},null,2));
  await context.close();
}
fs.writeFileSync(path.join(OUT,'saved.json'),JSON.stringify(saved,null,2));
console.log('DONE',saved.length);
await browser.close();
