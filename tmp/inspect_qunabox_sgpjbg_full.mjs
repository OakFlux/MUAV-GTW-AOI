import { chromium, request as playwrightRequest } from 'playwright';
import fs from 'fs';
import path from 'path';
import crypto from 'crypto';

const OUT = path.resolve('out_qunabox_sgpjbg_full');
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(OUT, { recursive: true });
fs.mkdirSync(path.join(OUT, 'downloads'), { recursive: true });

const urls = [
  'https://www.sgpjbg.com/baogao/464567.html',
  'https://www.sgpjbg.com/bgdown/464567.html',
  'https://www.sgpjbg.com/sgpjbg/View.aspx?id=464567',
  'https://www.sgpjbg.com/View.aspx?id=464567',
  'https://www.sgpjbg.com/bookread.aspx?id=464567',
  'https://www.sgpjbg.com/BookRead.aspx?id=464567',
];

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36',
  locale: 'zh-CN',
  acceptDownloads: true,
  ignoreHTTPSErrors: true,
});
const page = await context.newPage();
const net = [];
const candidateUrls = new Set();
const imageUrls = new Set();
const pdfUrls = new Set();

function interesting(u, ct='') {
  return /464567|pdf|book|read|view|fileroot|download|file|image|page|api|ashx/i.test(`${u} ${ct}`);
}
page.on('request', req => {
  const u = req.url();
  if (interesting(u)) net.push({type:'request', method:req.method(), url:u, resourceType:req.resourceType(), postData:req.postData()});
});
page.on('response', async resp => {
  const u=resp.url(); const h=await resp.allHeaders().catch(()=>({})); const ct=h['content-type']||'';
  if (!interesting(u,ct)) return;
  const entry={type:'response', status:resp.status(), url:u, contentType:ct, contentLength:h['content-length']||'', headers:h};
  if ((/json|text|html|javascript|xml/i.test(ct)) && Number(h['content-length']||0)<2000000) entry.preview=(await resp.text().catch(()=>'' )).slice(0,100000);
  net.push(entry);
  candidateUrls.add(u);
  if (/application\/pdf/i.test(ct) || /\.pdf(?:\?|$)/i.test(u)) pdfUrls.add(u);
  if (/image\//i.test(ct) || /\.(?:png|jpe?g|gif|webp)(?:\?|$)/i.test(u)) imageUrls.add(u);
});
page.on('download', async dl => {
  const name=dl.suggestedFilename(); const dest=path.join(OUT,'downloads',`browser_${name}`);
  await dl.saveAs(dest).catch(()=>{}); net.push({type:'download',suggested:name,dest,failure:await dl.failure().catch(()=>null)});
});

for (let i=0;i<urls.length;i++) {
  const u=urls[i]; console.log('OPEN',u);
  try {
    const r=await page.goto(u,{waitUntil:'domcontentloaded',timeout:90000});
    console.log('STATUS',r?.status(),page.url(),await page.title().catch(()=>''));
    await page.waitForTimeout(8000);
    for (const txt of ['在线阅读','在線閱讀','免费阅读','阅读全文','查看全文','下载PDF','立即下载','继续阅读']) {
      const loc=page.getByText(txt,{exact:false}).first();
      if (await loc.count().catch(()=>0)) {
        try { await loc.click({force:true,timeout:5000}); console.log('CLICK',txt,page.url()); await page.waitForTimeout(7000); } catch(e){ console.log('CLICK_ERR',txt,String(e)); }
      }
    }
    await page.evaluate(()=>window.scrollTo(0,document.body.scrollHeight)).catch(()=>{});
    await page.waitForTimeout(4000);
    const html=await page.content().catch(()=> '');
    const text=await page.locator('body').innerText().catch(()=> '');
    fs.writeFileSync(path.join(OUT,`page_${i}.html`),html);
    fs.writeFileSync(path.join(OUT,`page_${i}.txt`),text);
    await page.screenshot({path:path.join(OUT,`page_${i}.png`),fullPage:true}).catch(()=>{});
    const dom=await page.evaluate(()=>({
      url:location.href,title:document.title,
      anchors:[...document.querySelectorAll('a')].map(a=>({text:(a.innerText||'').trim(),href:a.href,onclick:a.getAttribute('onclick')||'',outer:a.outerHTML.slice(0,2000)})),
      images:[...document.images].map(im=>({src:im.src,currentSrc:im.currentSrc,dataSrc:im.dataset.src||'',alt:im.alt,w:im.naturalWidth,h:im.naturalHeight,outer:im.outerHTML.slice(0,2000)})),
      embeds:[...document.querySelectorAll('iframe,embed,object')].map(e=>({src:e.src||e.data||'',outer:e.outerHTML.slice(0,3000)})),
      scripts:[...document.scripts].map(s=>({src:s.src,text:(s.textContent||'').slice(0,30000)})),
      bodyData:{...document.body.dataset},
      storage:{local:{...localStorage},session:{...sessionStorage}},
    })).catch(()=>({}));
    fs.writeFileSync(path.join(OUT,`page_${i}_dom.json`),JSON.stringify(dom,null,2));
    for (const a of (dom.anchors||[])) if (a.href) candidateUrls.add(a.href);
    for (const im of (dom.images||[])) for (const x of [im.src,im.currentSrc,im.dataSrc]) if (x) {candidateUrls.add(x); imageUrls.add(x);}
    for (const e of (dom.embeds||[])) if (e.src) candidateUrls.add(e.src);
    for (const s of (dom.scripts||[])) {
      if (s.src) candidateUrls.add(s.src);
      const matches=(s.text||'').match(/https?:\/\/[^"'`\\\s<>]+/g)||[];
      for (const x of matches) candidateUrls.add(x.replace(/\\\//g,'/'));
    }
  } catch(e) { console.log('PAGE_ERR',u,String(e)); }
}

// Fetch every same-site JS and inspect for viewer endpoints and object roots.
const jsUrls=[...candidateUrls].filter(u=>/\.js(?:\?|$)/i.test(u) || /script/i.test(u));
for (let i=0;i<jsUrls.length;i++) {
  const u=jsUrls[i];
  try {
    const r=await context.request.get(u,{timeout:60000}); const body=await r.body();
    if (body.length>5_000_000) continue;
    fs.writeFileSync(path.join(OUT,`asset_${i}.js`),body);
    const txt=body.toString('utf8');
    if (/BookRead|fileroot|pdf|download|View\.aspx|pageCount|page_count|viewer/i.test(txt)) {
      console.log('JS_INTERESTING',u,r.status(),body.length);
      for (const pat of [/BookRead/gi,/fileroot/gi,/\.pdf/gi,/View\.aspx/gi,/pageCount/gi,/download/gi]) {
        let n=0; for (const m of txt.matchAll(pat)) { console.log('JS_CTX',u,txt.slice(Math.max(0,m.index-500),m.index+1500).replace(/\n/g,' ').slice(0,2000)); if(++n>=8)break; }
      }
    }
  } catch(e) { console.log('JS_ERR',u,String(e)); }
}

fs.writeFileSync(path.join(OUT,'network.json'),JSON.stringify(net,null,2));
fs.writeFileSync(path.join(OUT,'candidate_urls.json'),JSON.stringify([...candidateUrls],null,2));
fs.writeFileSync(path.join(OUT,'image_urls.json'),JSON.stringify([...imageUrls],null,2));
fs.writeFileSync(path.join(OUT,'pdf_urls.json'),JSON.stringify([...pdfUrls],null,2));

// Download candidate PDF/image resources exactly as anonymously exposed.
let counter=0;
for (const u of [...new Set([...pdfUrls,...imageUrls])]) {
  try {
    const r=await context.request.get(u,{timeout:90000,headers:{Referer:'https://www.sgpjbg.com/baogao/464567.html'}});
    const body=await r.body(); const ct=r.headers()['content-type']||'';
    if (r.status()!==200 || body.length<1000) continue;
    const ext=/pdf/i.test(ct)?'.pdf':/png/i.test(ct)?'.png':/jpe?g/i.test(ct)?'.jpg':/gif/i.test(ct)?'.gif':'.bin';
    const hash=crypto.createHash('sha256').update(body).digest('hex');
    const dest=path.join(OUT,'downloads',`${String(counter++).padStart(3,'0')}_${hash.slice(0,12)}${ext}`);
    fs.writeFileSync(dest,body);
    console.log('SAVED',r.status(),ct,body.length,u,dest);
  } catch(e){console.log('DOWNLOAD_ERR',u,String(e));}
}

await browser.close();
console.log('DONE',candidateUrls.size,imageUrls.size,pdfUrls.size);
