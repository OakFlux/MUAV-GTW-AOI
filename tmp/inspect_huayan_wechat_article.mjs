import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const OUT = path.resolve('out_huayan_wechat_article');
fs.rmSync(OUT, {recursive:true, force:true});
fs.mkdirSync(OUT,{recursive:true});
const URL='https://mp.weixin.qq.com/s/ykbXicJzYXyYVs6M0GIYYg';
const UA='Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.56(0x1800382e) NetType/WIFI Language/zh_CN';

async function rawFetch() {
  for (const [idx, ua] of [UA, 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/131 Mobile Safari/537.36 MicroMessenger/8.0.56'].entries()) {
    try {
      const r=await fetch(URL,{headers:{'User-Agent':ua,'Accept-Language':'zh-CN,zh;q=0.9','Referer':'https://weixin.qq.com/'},redirect:'follow'});
      const b=Buffer.from(await r.arrayBuffer());
      fs.writeFileSync(path.join(OUT,`raw_${idx}.html`),b);
      console.log('RAW',idx,r.status,r.headers.get('content-type'),b.length,r.url);
      const t=b.toString('utf8');
      for (const term of ['.pdf','download','attachment','file','网盘','百度','夸克','提取码','下载','链接','media','mmbiz','cdn_url','msg_link']) {
        let count=0;
        for (const m of t.matchAll(new RegExp(term.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'),'gi'))) {
          console.log('RAW_CTX',idx,term,t.slice(Math.max(0,m.index-500),Math.min(t.length,m.index+1600)).replace(/\n/g,' ').slice(0,2200));
          if (++count>=12) break;
        }
      }
    } catch(e) { console.log('RAW_ERR',idx,String(e)); }
  }
}
await rawFetch();

const browser=await chromium.launch({headless:true});
const context=await browser.newContext({userAgent:UA,locale:'zh-CN',viewport:{width:430,height:1200},acceptDownloads:true});
const page=await context.newPage();
const events=[]; const downloads=[];
page.on('response', async response=>{
  const u=response.url(); let headers={}; try{headers=await response.allHeaders();}catch{}
  const ct=headers['content-type']||'';
  if (/pdf|octet|download|file|attach|media|mmbiz|weixin|qq\.com/i.test(`${u} ${ct}`)) {
    const row={status:response.status(),url:u,ct,len:headers['content-length']||''};
    if (/json|text|html|javascript/i.test(ct)) { try { row.preview=(await response.text()).slice(0,12000); } catch{} }
    events.push(row); console.log('RESP',JSON.stringify(row).slice(0,16000));
  }
});
page.on('requestfailed',request=>{const row={failed:true,url:request.url(),err:request.failure()?.errorText||''};events.push(row);console.log('FAIL',JSON.stringify(row));});
page.on('download',async d=>{const n=d.suggestedFilename();const dest=path.join(OUT,`download_${Date.now()}_${n}`);try{await d.saveAs(dest);}catch{}downloads.push({n,dest,failure:await d.failure().catch(()=>null)});console.log('DOWNLOAD',n,dest);});
try { await page.goto(URL,{waitUntil:'domcontentloaded',timeout:90000}); } catch(e){console.log('GOTO_ERR',String(e));}
await page.waitForTimeout(10000);
console.log('PAGE',page.url(),await page.title().catch(()=>''));
const body=await page.locator('body').innerText().catch(()=> '');
const html=await page.content().catch(()=> '');
fs.writeFileSync(path.join(OUT,'page.txt'),body);
fs.writeFileSync(path.join(OUT,'page.html'),html);
await page.screenshot({path:path.join(OUT,'page.png'),fullPage:true}).catch(()=>{});
const anchors=await page.locator('a').evaluateAll(ns=>ns.map((a,i)=>({i,text:(a.innerText||a.textContent||'').trim(),href:a.href,outer:a.outerHTML.slice(0,1500)}))).catch(()=>[]);
const images=await page.locator('img').evaluateAll(ns=>ns.map((img,i)=>({i,alt:img.alt,src:img.src,dataSrc:img.getAttribute('data-src'),dataOriginal:img.getAttribute('data-original'),class:img.className,outer:img.outerHTML.slice(0,1500)}))).catch(()=>[]);
const iframes=await page.locator('iframe').evaluateAll(ns=>ns.map((f,i)=>({i,src:f.src,outer:f.outerHTML.slice(0,1500)}))).catch(()=>[]);
const buttons=await page.locator('button,[role="button"]').evaluateAll(ns=>ns.map((b,i)=>({i,text:(b.innerText||b.textContent||'').trim(),outer:b.outerHTML.slice(0,1500)}))).catch(()=>[]);
fs.writeFileSync(path.join(OUT,'dom.json'),JSON.stringify({anchors,images,iframes,buttons},null,2));
console.log('BODY',body.slice(0,15000).replace(/\n/g,' | '));
console.log('ANCHORS',JSON.stringify(anchors));
console.log('IFRAMES',JSON.stringify(iframes));
console.log('IMAGES',JSON.stringify(images));

// Download public article images for visual inspection; do not invoke auth or gated controls.
let imageNo=0;
for (const item of images) {
  const u=item.dataSrc||item.src||item.dataOriginal;
  if (!u || !/^https?:/i.test(u)) continue;
  try {
    const r=await fetch(u,{headers:{'User-Agent':UA,'Referer':URL},redirect:'follow'});
    const b=Buffer.from(await r.arrayBuffer()); const ct=r.headers.get('content-type')||'';
    if (r.status===200 && b.length>5000 && /^image\//i.test(ct)) {
      const ext=(ct.match(/image\/(png|jpeg|jpg|webp|gif)/i)?.[1]||'bin').replace('jpeg','jpg');
      fs.writeFileSync(path.join(OUT,`image_${String(imageNo).padStart(3,'0')}.${ext}`),b); imageNo++;
    }
  } catch(e) { console.log('IMAGE_ERR',u,String(e)); }
}
const resources=await page.evaluate(()=>performance.getEntriesByType('resource').map(r=>r.name)).catch(()=>[]);
fs.writeFileSync(path.join(OUT,'network.json'),JSON.stringify({events,downloads,resources},null,2));
await context.close();await browser.close();
console.log('READY',OUT,'images',imageNo);
