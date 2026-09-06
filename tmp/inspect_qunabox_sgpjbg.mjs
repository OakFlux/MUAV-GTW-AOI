import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const OUT='out_qunabox_sgpjbg_discovery';
fs.rmSync(OUT,{recursive:true,force:true});fs.mkdirSync(OUT,{recursive:true});
const browser=await chromium.launch({headless:true});
const context=await browser.newContext({userAgent:'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36',locale:'zh-CN',acceptDownloads:true});
const page=await context.newPage();
const network=[];
page.on('response',async r=>{const h=await r.allHeaders().catch(()=>({}));const ct=h['content-type']||'';const u=r.url();if(/pdf|file|book|view|download|report|api|ajax|label|baogao|bgdown/i.test(`${u} ${ct}`)){let preview='';if(/json|text|html|javascript/i.test(ct)&&Number(h['content-length']||0)<2000000){try{preview=(await r.text()).slice(0,150000);}catch{}}network.push({status:r.status(),url:u,ct,headers:h,preview});}});
page.on('download',async d=>{const dest=path.join(OUT,'download_'+d.suggestedFilename());await d.saveAs(dest).catch(()=>{});console.log('DOWNLOAD',d.suggestedFilename(),dest,await d.failure().catch(()=>null));});

const urls=[
 'https://www.sgpjbg.com/labels/quzhijituanesgbaogao.html',
 'https://www.sgpjbg.com/bgdown/464567.html',
 'https://www.sgpjbg.com/baogao/464567.html',
];
const reportLinks=new Set();
for(const [idx,url] of urls.entries()){
 console.log('OPEN',url);
 try{
  const r=await page.goto(url,{waitUntil:'domcontentloaded',timeout:90000});await page.waitForTimeout(8000);
  const html=await page.content();const text=await page.locator('body').innerText().catch(()=>'');
  fs.writeFileSync(path.join(OUT,`page_${idx}.html`),html);fs.writeFileSync(path.join(OUT,`page_${idx}.txt`),text);
  const anchors=await page.locator('a').evaluateAll(ns=>ns.map(a=>({text:(a.innerText||a.textContent||'').trim(),href:a.href,outer:a.outerHTML.slice(0,3000)})));
  const interesting=anchors.filter(a=>/趣致|AIoT|互动营销|00917|0917|464567|下载PDF|在线阅读|查看报告/i.test(`${a.text} ${a.href} ${a.outer}`));
  fs.writeFileSync(path.join(OUT,`page_${idx}_anchors.json`),JSON.stringify(interesting,null,2));
  for(const a of interesting){console.log('ANCHOR',idx,JSON.stringify(a));if(/sgpjbg\.com\/(?:baogao|bgdown)\/\d+\.html/.test(a.href))reportLinks.add(a.href);}
  console.log('META',idx,r?.status(),page.url(),await page.title(),text.slice(0,500).replace(/\n/g,' '));
 }catch(e){console.log('ERR',url,String(e));}
}

// Visit every Qunabox report link found on the label page and inspect public viewer assets.
for(const [i,url] of [...reportLinks].entries()){
 console.log('REPORT_OPEN',url);
 try{
  const r=await page.goto(url,{waitUntil:'domcontentloaded',timeout:90000});await page.waitForTimeout(10000);
  const html=await page.content();const text=await page.locator('body').innerText().catch(()=>'');
  fs.writeFileSync(path.join(OUT,`report_${i}.html`),html);fs.writeFileSync(path.join(OUT,`report_${i}.txt`),text);
  const dom=await page.evaluate(()=>({
   url:location.href,title:document.title,
   anchors:[...document.querySelectorAll('a')].map(a=>({text:(a.innerText||'').trim(),href:a.href,onclick:a.getAttribute('onclick'),outer:a.outerHTML.slice(0,4000)})),
   images:[...document.images].map(im=>({src:im.src,currentSrc:im.currentSrc,alt:im.alt,w:im.naturalWidth,h:im.naturalHeight,outer:im.outerHTML.slice(0,3000)})),
   frames:[...document.querySelectorAll('iframe,embed,object')].map(e=>({src:e.src||e.data||'',outer:e.outerHTML.slice(0,4000)})),
   scripts:[...document.scripts].map(s=>({src:s.src,text:(s.textContent||'').slice(0,50000)})),
  }));
  fs.writeFileSync(path.join(OUT,`report_${i}_dom.json`),JSON.stringify(dom,null,2));
  console.log('REPORT_META',i,r?.status(),page.url(),dom.title,'images',dom.images.length,'frames',dom.frames.length);
  for(const a of dom.anchors.filter(a=>/pdf|download|bookread|view|file|下载|阅读/i.test(`${a.text} ${a.href} ${a.onclick} ${a.outer}`)).slice(0,200)) console.log('REPORT_LINK',i,JSON.stringify(a));
  for(const im of dom.images.filter(im=>/fileroot|page|pdf|book|report/i.test(`${im.src} ${im.outer}`)).slice(0,200)) console.log('REPORT_IMAGE',i,JSON.stringify(im));
  for(const f of dom.frames) console.log('REPORT_FRAME',i,JSON.stringify(f));
 }catch(e){console.log('REPORT_ERR',url,String(e));}
}
fs.writeFileSync(path.join(OUT,'network.json'),JSON.stringify(network,null,2));
fs.writeFileSync(path.join(OUT,'report_links.json'),JSON.stringify([...reportLinks],null,2));
console.log('DONE',reportLinks.size,network.length);
await browser.close();
