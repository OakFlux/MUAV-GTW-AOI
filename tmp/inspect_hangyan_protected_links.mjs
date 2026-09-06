import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const OUT='out_hangyan_protected_links';
fs.rmSync(OUT,{recursive:true,force:true});fs.mkdirSync(OUT,{recursive:true});
const browser=await chromium.launch({headless:true});
const context=await browser.newContext({userAgent:'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36',locale:'zh-CN'});
const targets=[
 ['boci_chart1','https://www.hangyan.co/charts/3545791843998368928'],
 ['boci_chart2','https://www.hangyan.co/charts/3545791848435942587'],
];
for(const [name,url] of targets){
 const page=await context.newPage();
 const events=[];
 page.on('request',req=>events.push({type:'request',method:req.method(),url:req.url(),resourceType:req.resourceType(),postData:req.postData(),headers:req.headers()}));
 page.on('response',async resp=>{
   const h=await resp.allHeaders().catch(()=>({}));
   let preview='';
   const ct=h['content-type']||'';
   if(/json|text|javascript|turbo-stream|html/i.test(ct) && Number(h['content-length']||0)<2000000){try{preview=(await resp.text()).slice(0,200000);}catch{}}
   events.push({type:'response',status:resp.status(),url:resp.url(),contentType:ct,headers:h,preview});
 });
 await page.goto(url,{waitUntil:'domcontentloaded',timeout:90000});
 await page.waitForTimeout(6000);
 const html=await page.content();
 fs.writeFileSync(path.join(OUT,`${name}_before.html`),html);
 const jsUrls=await page.locator('script[src]').evaluateAll(ns=>ns.map(s=>s.src));
 fs.writeFileSync(path.join(OUT,`${name}_jsurls.json`),JSON.stringify(jsUrls,null,2));
 console.log('JSURLS',name,JSON.stringify(jsUrls));
 for(const [i,js] of jsUrls.entries()){
   if(!/hangyan\.co/.test(js)) continue;
   try{
     const r=await context.request.get(js,{timeout:60000});const text=await r.text();
     fs.writeFileSync(path.join(OUT,`${name}_asset_${i}.js`),text);
     for(const pat of ['protected-link','protected_link','tokenValue','decrypt','links/','resolve','redirect']){
       let pos=0,count=0;while((pos=text.toLowerCase().indexOf(pat.toLowerCase(),pos))>=0 && count<20){
         console.log('JS_CONTEXT',name,pat,text.slice(Math.max(0,pos-500),pos+1500).replace(/\n/g,' '));pos+=pat.length;count++;
       }
     }
   }catch(e){console.log('JSERR',js,String(e));}
 }
 const links=page.locator('[data-controller="protected-link"]');
 const n=await links.count();console.log('PROTECTED_COUNT',name,n);
 for(let i=0;i<n;i++){
   const el=links.nth(i);
   const attrs=await el.evaluate(e=>Object.fromEntries([...e.attributes].map(a=>[a.name,a.value])));
   const text=(await el.innerText().catch(()=>'' )).trim();
   console.log('PROTECTED',name,i,text,JSON.stringify(attrs));
   const start=events.length;
   try{await el.click({force:true,timeout:10000});await page.waitForTimeout(5000);}catch(e){console.log('CLICKERR',name,i,String(e));}
   console.log('AFTER_CLICK',name,i,page.url(),await page.locator('#modal-content').innerText().catch(()=>''));
   fs.writeFileSync(path.join(OUT,`${name}_after_${i}.html`),await page.content());
   fs.writeFileSync(path.join(OUT,`${name}_click_${i}_events.json`),JSON.stringify(events.slice(start),null,2));
 }
 fs.writeFileSync(path.join(OUT,`${name}_all_events.json`),JSON.stringify(events,null,2));
 await page.close();
}
await browser.close();
