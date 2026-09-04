import { chromium } from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';

const targets = [
  {id:'4490043', title:'西南证券-生物发酵龙头，多品类蓄势待发'},
  {id:'3755592', title:'兴证国际-多品类布局全球领先的生物发酵企业'},
  {id:'94798', title:'华创证券-多产品一体化的生物发酵龙头'}
];
const out = path.resolve('out_fufeng_fxbaogao_inspect');
await fs.rm(out,{recursive:true,force:true});
await fs.mkdir(out,{recursive:true});

const browser = await chromium.launch({headless:true});
const context = await browser.newContext({
  viewport:{width:1440,height:1000},
  locale:'zh-CN',
  userAgent:'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
});

for (const t of targets) {
  const rec = {target:t, pages:[]};
  for (const url of [`https://www.fxbaogao.com/detail/${t.id}`, `https://www.fxbaogao.com/view?id=${t.id}`]) {
    const page = await context.newPage();
    const net=[];
    const consoleLogs=[];
    page.on('console',msg=>consoleLogs.push({type:msg.type(),text:msg.text()}));
    page.on('request', req=>{
      const u=req.url();
      if (/pdf|report|file|preview|view|download|image|img|oss|cos|cdn|api/i.test(u)) {
        net.push({kind:'request',url:u,method:req.method(),resourceType:req.resourceType(),postData:req.postData()});
      }
    });
    page.on('response', async res=>{
      const u=res.url();
      const headers=await res.allHeaders().catch(()=>({}));
      const ct=headers['content-type']||'';
      if (/pdf|report|file|preview|view|download|image|img|oss|cos|cdn|api/i.test(u) || /pdf|image|octet-stream|json/i.test(ct)) {
        net.push({kind:'response',url:u,status:res.status(),contentType:ct,contentLength:headers['content-length']||'',contentDisposition:headers['content-disposition']||''});
      }
    });
    page.on('download', async download=>{
      const name=download.suggestedFilename();
      const p=path.join(out,`${t.id}_${name}`);
      await download.saveAs(p).catch(()=>{});
      net.push({kind:'download',url:download.url(),suggestedFilename:name,saved:p});
    });
    try {
      console.log('OPEN',url);
      const res=await page.goto(url,{waitUntil:'domcontentloaded',timeout:120000});
      await page.waitForTimeout(5000);
      try { await page.waitForLoadState('networkidle',{timeout:20000}); } catch {}
      // Try clicking obvious free-view/download buttons.
      for (const text of ['点击免费查看完整报告','免费查看完整报告','查看完整报告','下载PDF','下载报告']) {
        const loc=page.getByText(text,{exact:false}).first();
        if (await loc.count()) {
          try { await loc.click({timeout:5000}); await page.waitForTimeout(5000); } catch {}
        }
      }
      // Scroll to trigger lazy loading.
      await page.evaluate(async()=>{
        const delay=ms=>new Promise(r=>setTimeout(r,ms));
        let last=0;
        for(let i=0;i<60;i++){
          const h=document.documentElement.scrollHeight;
          window.scrollTo(0,Math.min(h, i*1200));
          await delay(250);
          if(h===last && window.scrollY+window.innerHeight>=h-10) break;
          last=h;
        }
      });
      await page.waitForTimeout(5000);
      const data=await page.evaluate(()=>{
        const attrs=(selector,attr)=>[...document.querySelectorAll(selector)].map(e=>e.getAttribute(attr)).filter(Boolean);
        const allText=(document.body?.innerText||'').replace(/\s+/g,' ').slice(0,20000);
        const scripts=[...document.scripts].map(s=>({src:s.src||'',text:(s.textContent||'').slice(0,50000)}));
        const anchors=[...document.querySelectorAll('a')].map(a=>({text:(a.innerText||a.textContent||'').replace(/\s+/g,' ').trim(),href:a.href||'',download:a.getAttribute('download')||'',onclick:a.getAttribute('onclick')||''}));
        const embeds=[...document.querySelectorAll('iframe,embed,object')].map(e=>({tag:e.tagName,src:e.getAttribute('src')||'',data:e.getAttribute('data')||'',type:e.getAttribute('type')||''}));
        const images=[...document.images].map(i=>({src:i.currentSrc||i.src||'',alt:i.alt||'',w:i.naturalWidth,h:i.naturalHeight}));
        const storage={local:{},session:{}};
        for(let i=0;i<localStorage.length;i++){const k=localStorage.key(i);storage.local[k]=localStorage.getItem(k)}
        for(let i=0;i<sessionStorage.length;i++){const k=sessionStorage.key(i);storage.session[k]=sessionStorage.getItem(k)}
        const globals={};
        for(const key of ['__NEXT_DATA__','__NUXT__','__INITIAL_STATE__','__APOLLO_STATE__']){
          try { if(window[key]) globals[key]=window[key]; } catch {}
        }
        return {title:document.title,url:location.href,allText,anchors,embeds,images,scripts,storage,globals,html:document.documentElement.outerHTML.slice(0,1000000)};
      });
      rec.pages.push({requestedUrl:url,status:res?.status()||null,data,net,consoleLogs});
      await fs.writeFile(path.join(out,`${t.id}_${url.includes('/view')?'view':'detail'}.html`),data.html,'utf8');
      await page.screenshot({path:path.join(out,`${t.id}_${url.includes('/view')?'view':'detail'}.png`),fullPage:true}).catch(()=>{});
      console.log('DONE',t.id,url,'current',data.url,'net',net.length,'images',data.images.length);
      for(const n of net){ if(n.kind==='response' && (/pdf/i.test(n.contentType)||/\.pdf/i.test(n.url))) console.log('PDFRESP',JSON.stringify(n)); }
      for(const a of data.anchors){ if(/pdf|download|view|report|完整/i.test(`${a.text} ${a.href} ${a.onclick}`)) console.log('ANCHOR',t.id,JSON.stringify(a)); }
      for(const e of data.embeds){ console.log('EMBED',t.id,JSON.stringify(e)); }
    } catch(e) {
      rec.pages.push({requestedUrl:url,error:String(e),net,consoleLogs});
      console.error('ERR',url,String(e));
    } finally {
      await page.close();
    }
  }
  await fs.writeFile(path.join(out,`${t.id}.json`),JSON.stringify(rec,null,2),'utf8');
}

await browser.close();
console.log('INSPECTION_READY',out);
