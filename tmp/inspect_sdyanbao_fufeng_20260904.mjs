import { chromium } from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';

const targets = [
  {id:'817436', title:'西南证券-生物发酵龙头，多品类蓄势待发'}
];
const out = path.resolve('out_fufeng_sdyanbao_inspect');
await fs.rm(out,{recursive:true,force:true});
await fs.mkdir(out,{recursive:true});

const browser=await chromium.launch({headless:true});
const context=await browser.newContext({
  viewport:{width:1440,height:1000},
  locale:'zh-CN',
  userAgent:'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
  acceptDownloads:true
});

for(const t of targets){
  const page=await context.newPage();
  const net=[]; const downloads=[]; const consoleLogs=[];
  page.on('console',m=>consoleLogs.push({type:m.type(),text:m.text()}));
  page.on('request',req=>{
    const u=req.url();
    if(/pdf|download|report|detail|file|preview|api|oss|cos|cdn/i.test(u)) net.push({kind:'request',url:u,method:req.method(),type:req.resourceType(),postData:req.postData()});
  });
  page.on('response',async res=>{
    const u=res.url(); const h=await res.allHeaders().catch(()=>({})); const ct=h['content-type']||'';
    if(/pdf|download|report|detail|file|preview|api|oss|cos|cdn/i.test(u)||/pdf|octet-stream|json/i.test(ct)) net.push({kind:'response',url:u,status:res.status(),contentType:ct,length:h['content-length']||'',disposition:h['content-disposition']||''});
  });
  page.on('download',async d=>{
    const name=d.suggestedFilename(); const save=path.join(out,`${t.id}_${name}`);
    await d.saveAs(save).catch(()=>{}); downloads.push({url:d.url(),name,save});
  });
  try{
    const url=`https://www.sdyanbao.com/detail/${t.id}`;
    console.log('OPEN',url);
    const r=await page.goto(url,{waitUntil:'domcontentloaded',timeout:120000});
    await page.waitForTimeout(5000);
    try{await page.waitForLoadState('networkidle',{timeout:20000});}catch{}
    const pre=await page.evaluate(()=>({
      title:document.title,url:location.href,
      anchors:[...document.querySelectorAll('a')].map(a=>({text:(a.innerText||a.textContent||'').replace(/\s+/g,' ').trim(),href:a.href||'',download:a.getAttribute('download')||'',onclick:a.getAttribute('onclick')||''})),
      buttons:[...document.querySelectorAll('button')].map(b=>({text:(b.innerText||b.textContent||'').replace(/\s+/g,' ').trim(),onclick:b.getAttribute('onclick')||'',outer:b.outerHTML.slice(0,1000)})),
      scripts:[...document.scripts].map(s=>({src:s.src||'',text:(s.textContent||'').slice(0,100000)})),
      images:[...document.images].map(i=>({src:i.currentSrc||i.src||'',alt:i.alt||'',w:i.naturalWidth,h:i.naturalHeight})),
      html:document.documentElement.outerHTML
    }));
    await fs.writeFile(path.join(out,`${t.id}_before.json`),JSON.stringify({status:r?.status(),pre,net,consoleLogs},null,2));
    await fs.writeFile(path.join(out,`${t.id}.html`),pre.html);
    console.log('ANCHORS'); for(const a of pre.anchors){if(/下载|pdf|report|file|download/i.test(`${a.text} ${a.href} ${a.onclick}`)) console.log(JSON.stringify(a));}
    console.log('BUTTONS'); for(const b of pre.buttons){if(/下载|pdf|report|file|download/i.test(`${b.text} ${b.onclick} ${b.outer}`)) console.log(JSON.stringify(b));}
    // Click each visible "立即下载" control, one at a time, observing navigation/download.
    const controls=page.getByText('立即下载',{exact:true});
    const count=await controls.count();
    console.log('DOWNLOAD CONTROLS',count);
    for(let i=0;i<count;i++){
      const c=controls.nth(i);
      if(!(await c.isVisible().catch(()=>false))) continue;
      try{
        const before=page.url();
        await c.click({timeout:5000});
        await page.waitForTimeout(5000);
        console.log('CLICKED',i,'before',before,'after',page.url());
        if(page.url()!==url){
          await page.goBack({waitUntil:'domcontentloaded',timeout:30000}).catch(()=>{});
          await page.waitForTimeout(2000);
        }
      }catch(e){console.log('CLICKERR',i,String(e));}
    }
    await page.evaluate(async()=>{const d=ms=>new Promise(r=>setTimeout(r,ms));for(let y=0;y<document.documentElement.scrollHeight;y+=1000){window.scrollTo(0,y);await d(120);}});
    await page.waitForTimeout(3000);
    const post=await page.evaluate(()=>({url:location.href,html:document.documentElement.outerHTML,localStorage:{...localStorage},sessionStorage:{...sessionStorage}}));
    await fs.writeFile(path.join(out,`${t.id}_result.json`),JSON.stringify({target:t,pre,post,net,downloads,consoleLogs},null,2));
    await page.screenshot({path:path.join(out,`${t.id}.png`),fullPage:true}).catch(()=>{});
    console.log('NETWORK',net.length,'DOWNLOADS',downloads.length);
    for(const n of net){if((n.kind==='response'&&(/pdf/i.test(n.contentType)||/\.pdf/i.test(n.url)))||n.kind==='download') console.log('POTENTIAL',JSON.stringify(n));}
    for(const d of downloads) console.log('DOWNLOAD',JSON.stringify(d));
  }catch(e){console.error('ERR',String(e));}
  await page.close();
}
await browser.close();
console.log('READY',out);
