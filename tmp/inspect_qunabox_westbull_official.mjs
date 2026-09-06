import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import crypto from 'crypto';

const OUT = path.resolve('out_qunabox_westbull_official');
const PDFS = path.join(OUT, 'pdfs');
fs.rmSync(OUT, {recursive:true, force:true});
fs.mkdirSync(PDFS, {recursive:true});
const browser = await chromium.launch({headless:true});
const context = await browser.newContext({
  ignoreHTTPSErrors: true,
  userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36',
  locale: 'zh-CN',
  viewport: {width:1440,height:1200},
});
const events=[]; const pdfUrls=new Set(); const saved=[]; const assetUrls=new Set();
function safe(s){return s.replace(/[^a-zA-Z0-9._-]+/g,'_').slice(0,140)}
async function savePdf(url, referer, label){
  if (!url || [...saved].some(x=>x.url===url)) return;
  try {
    const r=await context.request.get(url,{timeout:90000,ignoreHTTPSErrors:true,headers:{Referer:referer,'User-Agent':'Mozilla/5.0'}});
    const b=await r.body(); const ct=r.headers()['content-type']||'';
    console.log('FETCH_PDF',r.status(),ct,b.length,url);
    if(r.status()===200 && b.length>50000 && b.slice(0,5).toString()==='%PDF-'){
      const sha=crypto.createHash('sha256').update(b).digest('hex');
      const fn=`${safe(label)}_${sha.slice(0,12)}.pdf`; fs.writeFileSync(path.join(PDFS,fn),b);
      saved.push({url,referer,fileName:fn,bytes:b.length,sha256:sha});
      console.log('SAVED',fn,b.length);
    }
  } catch(e){console.log('FETCH_PDF_ERR',url,String(e));}
}

async function visit(url,label){
 const page=await context.newPage();
 page.on('response',async resp=>{
   const u=resp.url(); const h=await resp.allHeaders().catch(()=>({})); const ct=h['content-type']||'';
   if(/\.pdf(?:\?|$)/i.test(u)||/application\/pdf/i.test(ct)) pdfUrls.add(u);
   if(/javascript|json|api|research|report|download|file|pdf/i.test(`${u} ${ct}`)){
     const row={page:url,url:u,status:resp.status(),ct,len:h['content-length']||''};
     if(/json|text|javascript/i.test(ct) && Number(row.len||0)<3000000) row.preview=(await resp.text().catch(()=>'' )).slice(0,250000);
     events.push(row);
   }
   if(/javascript/i.test(ct)||/\.js(?:\?|$)/i.test(u)) assetUrls.add(u);
 });
 console.log('VISIT',url);
 try{
   const r=await page.goto(url,{waitUntil:'networkidle',timeout:90000});
   console.log('STATUS',r?.status(),page.url(),await page.title().catch(()=>''));
   await page.waitForTimeout(8000);
   const html=await page.content(); const text=await page.locator('body').innerText().catch(()=> '');
   fs.writeFileSync(path.join(OUT,`${safe(label)}.html`),html); fs.writeFileSync(path.join(OUT,`${safe(label)}.txt`),text);
   const dom=await page.evaluate(()=>({
     url:location.href,title:document.title,
     anchors:[...document.querySelectorAll('a')].map(a=>({text:(a.innerText||'').trim(),href:a.href,download:a.download||''})),
     scripts:[...document.scripts].map(s=>({src:s.src,text:(s.textContent||'').slice(0,100000)})),
     iframes:[...document.querySelectorAll('iframe,embed,object')].map(e=>({src:e.src||e.data||'',outer:e.outerHTML.slice(0,5000)})),
     body:document.body.innerText,
   }));
   fs.writeFileSync(path.join(OUT,`${safe(label)}_dom.json`),JSON.stringify(dom,null,2));
   const blob=JSON.stringify(dom)+'\n'+html+'\n'+JSON.stringify(events);
   for(const m of blob.matchAll(/https?:\\?\/\\?\/[^"'<>\s\\]+\.pdf(?:\?[^"'<>\s\\]*)?/gi)) pdfUrls.add(m[0].replace(/\\\//g,'/').replace(/&amp;/g,'&'));
   for(const a of dom.anchors) if(/\.pdf(?:\?|$)/i.test(a.href)) pdfUrls.add(a.href);
   for(const e of dom.iframes) if(/\.pdf(?:\?|$)/i.test(e.src)) pdfUrls.add(e.src);
   // Click visible research cards and Qunabox text links.
   for(const pat of [/趣致集团/i,/趣致集團/i,/Qunabox/i,/00917/i,/存量终端/i,/存量終端/i]){
     const loc=page.getByText(pat).first();
     if(await loc.count().catch(()=>0)){
       try{await loc.click({force:true,timeout:4000}); await page.waitForTimeout(5000); console.log('CLICKED',pat.toString(),page.url());}catch{}
     }
   }
 }catch(e){console.log('VISIT_ERR',url,String(e));}
 await page.close();
}

for(const u of [
 'https://www.westbullsec.com.hk/',
 'https://www.westbullsec.com.hk/research',
 'http://www.westbullsec.com.hk/',
 'http://www.westbullsec.com.hk/research',
]) await visit(u,safe(u));

// Inspect all public JS bundles for endpoints and report objects.
for(const u of [...assetUrls]){
 try{
   const r=await context.request.get(u,{timeout:60000,ignoreHTTPSErrors:true}); const b=await r.body(); const t=b.toString('utf8');
   const fn=`asset_${crypto.createHash('sha1').update(u).digest('hex').slice(0,10)}.js`; fs.writeFileSync(path.join(OUT,fn),b);
   console.log('ASSET',r.status(),b.length,u);
   const contexts=[];
   for(const pat of [/00917/gi,/qunabox/gi,/趣致/gi,/research/gi,/report/gi,/download/gi,/\.pdf/gi,/axios/gi,/baseURL/gi]){
     for(const m of [...t.matchAll(pat)].slice(0,100)) contexts.push({pat:String(pat),ctx:t.slice(Math.max(0,m.index-800),m.index+1800)});
   }
   fs.writeFileSync(path.join(OUT,fn+'.contexts.json'),JSON.stringify(contexts,null,2));
   for(const m of t.matchAll(/https?:\/\/[^"'`\\\s<>]+/g)){
     const x=m[0]; if(/\.pdf(?:\?|$)/i.test(x)) pdfUrls.add(x);
   }
 }catch(e){console.log('ASSET_ERR',u,String(e));}
}

// Mine response bodies for URLs, endpoint paths, and Qunabox objects.
const eventBlob=JSON.stringify(events);
for(const m of eventBlob.matchAll(/https?:\\?\/\\?\/[^"'<>\s\\]+\.pdf(?:\?[^"'<>\s\\]*)?/gi)) pdfUrls.add(m[0].replace(/\\\//g,'/'));
fs.writeFileSync(path.join(OUT,'events.json'),JSON.stringify(events,null,2));
fs.writeFileSync(path.join(OUT,'pdf_urls.json'),JSON.stringify([...pdfUrls],null,2));

for(const u of [...pdfUrls]) await savePdf(u,'https://www.westbullsec.com.hk/research','westbull_qunabox');

// Probe plausible official static paths learned from common Vue/CMS conventions.
const dates=['20260824','20260825','2026-08-24','2026-08-25'];
const names=[];
for(const d of dates){
 for(const code of ['00917','0917','917','Qunabox','qunabox']){
  for(const ext of ['pdf','.pdf']) names.push(`${code}-${d}${ext.startsWith('.')?'':'.'}${ext.replace('.','')}`.replace('.pdfpdf','.pdf'));
 }
}
const prefixes=[
 'https://www.westbullsec.com.hk/uploads/research/',
 'https://www.westbullsec.com.hk/upload/research/',
 'https://www.westbullsec.com.hk/static/upload/research/',
 'https://www.westbullsec.com.hk/api/file/',
 'https://www.westbullsec.com.hk/files/research/',
];
for(const p of prefixes) for(const n of names.slice(0,40)) await savePdf(p+n,'https://www.westbullsec.com.hk/research','westbull_probe');

fs.writeFileSync(path.join(OUT,'manifest.json'),JSON.stringify(saved,null,2));
console.log('DONE','assets',assetUrls.size,'pdfUrls',pdfUrls.size,'saved',saved.length);
await browser.close();
