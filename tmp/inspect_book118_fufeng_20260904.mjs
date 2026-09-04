import { chromium } from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';

const url='https://max.book118.com/html/2024/1226/8040063113007012.shtm';
const out=path.resolve('out_book118_fufeng_inspect');
await fs.rm(out,{recursive:true,force:true}); await fs.mkdir(out,{recursive:true});
const browser=await chromium.launch({headless:true});
const context=await browser.newContext({viewport:{width:1440,height:1100},locale:'zh-CN',userAgent:'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36'});
const page=await context.newPage();
const net=[];
page.on('request',req=>{const u=req.url(); if(/image|img|page|preview|book|pdf|file|download|api/i.test(u)) net.push({kind:'request',url:u,method:req.method(),type:req.resourceType(),postData:req.postData()});});
page.on('response',async res=>{const u=res.url(); const h=await res.allHeaders().catch(()=>({})); const ct=h['content-type']||''; if(/image|img|page|preview|book|pdf|file|download|api/i.test(u)||/image|pdf|json|octet/i.test(ct)) net.push({kind:'response',url:u,status:res.status(),ct,len:h['content-length']||'',disp:h['content-disposition']||''});});
try{
 const r=await page.goto(url,{waitUntil:'domcontentloaded',timeout:120000}); await page.waitForTimeout(7000); try{await page.waitForLoadState('networkidle',{timeout:20000})}catch{}
 await page.evaluate(async()=>{const d=ms=>new Promise(r=>setTimeout(r,ms)); for(let i=0;i<100;i++){window.scrollTo(0,Math.min(document.documentElement.scrollHeight,i*1200)); await d(150); if(window.scrollY+innerHeight>=document.documentElement.scrollHeight-20) {await d(1000); if(window.scrollY+innerHeight>=document.documentElement.scrollHeight-20) break;}}});
 await page.waitForTimeout(7000);
 const data=await page.evaluate(()=>({
  title:document.title,url:location.href,text:(document.body?.innerText||'').replace(/\s+/g,' ').slice(0,100000),
  images:[...document.images].map((i,index)=>({index,src:i.currentSrc||i.src||'',dataSrc:i.getAttribute('data-src')||'',dataOriginal:i.getAttribute('data-original')||'',alt:i.alt||'',w:i.naturalWidth,h:i.naturalHeight,outer:i.outerHTML.slice(0,1000)})),
  embeds:[...document.querySelectorAll('iframe,embed,object')].map(e=>({tag:e.tagName,src:e.getAttribute('src')||'',data:e.getAttribute('data')||'',outer:e.outerHTML.slice(0,1000)})),
  anchors:[...document.querySelectorAll('a')].map(a=>({text:(a.innerText||a.textContent||'').replace(/\s+/g,' ').trim(),href:a.href||'',onclick:a.getAttribute('onclick')||'',download:a.getAttribute('download')||''})),
  scripts:[...document.scripts].map(s=>({src:s.src||'',text:(s.textContent||'').slice(0,200000)})),
  html:document.documentElement.outerHTML
 }));
 await fs.writeFile(path.join(out,'result.json'),JSON.stringify({status:r?.status(),data,net},null,2));
 await fs.writeFile(path.join(out,'page.html'),data.html); await page.screenshot({path:path.join(out,'page.png'),fullPage:true}).catch(()=>{});
 console.log('STATUS',r?.status(),'TITLE',data.title,'IMAGES',data.images.length,'NET',net.length,'TEXTLEN',data.text.length);
 for(const im of data.images){if(im.w>500||im.h>500||/page|preview|doc|book/i.test(`${im.src} ${im.dataSrc} ${im.dataOriginal} ${im.alt}`)) console.log('IMG',JSON.stringify(im));}
 for(const n of net){if(n.kind==='response'&&(/image|pdf|octet/i.test(n.ct)||/page|preview|\.pdf/i.test(n.url))) console.log('NET',JSON.stringify(n));}
 for(const a of data.anchors){if(/下载|pdf|预览|全文|文档/i.test(`${a.text} ${a.href} ${a.onclick}`)) console.log('ANCHOR',JSON.stringify(a));}
 for(const e of data.embeds) console.log('EMBED',JSON.stringify(e));
} catch(e){console.error('ERR',String(e)); process.exitCode=1;} finally {await page.close(); await browser.close();}
