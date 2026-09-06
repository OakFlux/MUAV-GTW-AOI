import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import crypto from 'crypto';

const OUT = path.resolve('out_ascletis_baogaobox');
const PDFDIR = path.join(OUT, 'pdfs');
fs.rmSync(OUT, {recursive:true, force:true});
fs.mkdirSync(PDFDIR, {recursive:true});
const UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36';
const targets=[
 ['dongwu','https://www.baogaobox.com/reports/250402000054301.html'],
 ['orient','https://www.baogaobox.com/reports/251229000088797.html'],
 ['dongwu_insight','https://www.baogaobox.com/insights/250519000010254.html'],
];
const browser=await chromium.launch({headless:true});
const saved=[]; const seen=new Set();
function isPdf(b){return b && b.length>50000 && b.subarray(0,5).toString()==='%PDF-';}
function savePdf(buf,label,url){if(!isPdf(buf))return;const sha=crypto.createHash('sha256').update(buf).digest('hex');if(seen.has(sha))return;seen.add(sha);const f=path.join(PDFDIR,`${label}_${sha.slice(0,12)}.pdf`);fs.writeFileSync(f,buf);saved.push({file:f,url,bytes:buf.length,sha256:sha});console.log('SAVED',f,buf.length,url);}
for(const [label,url] of targets){
 const ctx=await browser.newContext({userAgent:UA,locale:'zh-CN',acceptDownloads:true});
 const page=await ctx.newPage(); const events=[];
 page.on('response',async r=>{const u=r.url();const h=await r.allHeaders().catch(()=>({}));const ct=h['content-type']||'';if(/pdf|download|report|file|attachment|api|oss|cos/i.test(`${u} ${ct}`)){const e={status:r.status(),url:u,ct,cl:h['content-length']||''};if(/json|text|javascript/i.test(ct)&&Number(e.cl||0)<1000000)e.preview=(await r.text().catch(()=>'' )).slice(0,20000);events.push(e);}if(ct.includes('application/pdf')||/\.pdf(?:[?#]|$)/i.test(u)){try{savePdf(Buffer.from(await r.body()),label+'_response',u)}catch{}}});
 page.on('download',async d=>{try{const p=await d.path(); if(p) savePdf(fs.readFileSync(p),label+'_download',d.url());}catch{}});
 try{
  const nav=await page.goto(url,{waitUntil:'domcontentloaded',timeout:90000});
  console.log('OPEN',label,nav?.status(),page.url(),await page.title());
  await page.waitForTimeout(8000);
  for(const pat of [/下载报告/i,/立即下载/i,/下载PDF/i,/报告下载/i,/原文/i]){
    const loc=page.getByText(pat).first(); if(await loc.count().catch(()=>0)){try{await loc.click({timeout:5000,force:true});console.log('CLICK',label,String(pat),page.url());await page.waitForTimeout(6000);}catch(e){console.log('CLICKERR',label,String(e));}}
  }
  const html=await page.content(); const text=await page.locator('body').innerText().catch(()=> '');
  fs.writeFileSync(path.join(OUT,label+'.html'),html);fs.writeFileSync(path.join(OUT,label+'.txt'),text);await page.screenshot({path:path.join(OUT,label+'.png'),fullPage:true}).catch(()=>{});
  const dom=await page.evaluate(()=>({attrs:[...document.querySelectorAll('a,img,iframe,embed,object,source,button')].flatMap(el=>['href','src','data','data-src','data-url','data-file','onclick'].map(k=>el[k]||el.getAttribute?.(k)||'')).filter(Boolean),resources:performance.getEntriesByType('resource').map(r=>r.name),scripts:[...document.scripts].map(s=>s.src||s.textContent||'').filter(Boolean)}));
  const blob=[html,...dom.attrs,...dom.resources,...dom.scripts].join('\n').replace(/\\u0026/g,'&').replace(/\\\//g,'/');
  const urls=[...new Set(blob.match(/https?:[^"'\s<>]+/g)||[])].map(x=>x.replace(/&amp;/g,'&').replace(/[\\),;]+$/g,''));
  fs.writeFileSync(path.join(OUT,label+'_urls.json'),JSON.stringify(urls,null,2));
  for(const u of urls){if(!/\.pdf(?:[?#]|$)|download|attachment|file|oss|cos/i.test(u))continue;try{const r=await ctx.request.get(u,{timeout:45000,headers:{Referer:page.url(),Accept:'application/pdf,*/*'}});const b=Buffer.from(await r.body());events.push({type:'probe',status:r.status(),url:u,ct:r.headers()['content-type']||'',bytes:b.length});savePdf(b,label+'_probe',u);}catch(e){events.push({type:'probe_error',url:u,error:String(e)});}}
 }catch(e){console.log('ERR',label,String(e));}
 fs.writeFileSync(path.join(OUT,label+'_events.json'),JSON.stringify(events,null,2));await ctx.close();
}
fs.writeFileSync(path.join(OUT,'saved.json'),JSON.stringify(saved,null,2));
await browser.close();console.log('DONE',saved.length);
