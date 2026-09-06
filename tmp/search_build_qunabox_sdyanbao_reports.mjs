import { chromium } from 'playwright';
import { PDFDocument } from 'pdf-lib';
import fs from 'fs';
import path from 'path';
import crypto from 'crypto';

const OUT=path.resolve('out_qunabox_sdyanbao');
const PDFDIR=path.join(OUT,'pdfs');
fs.rmSync(OUT,{recursive:true,force:true}); fs.mkdirSync(PDFDIR,{recursive:true});
const browser=await chromium.launch({headless:true});
const context=await browser.newContext({ignoreHTTPSErrors:true,userAgent:'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36',locale:'zh-CN',viewport:{width:1440,height:1200}});
const page=await context.newPage();
const reqs=[]; const resps=[]; const detailIds=new Set([853466]);
page.on('request',req=>{
 const u=req.url(); if(/api\.sdyanbao\.com\/api\/file|search|report/i.test(u)) reqs.push({method:req.method(),url:u,postData:req.postData(),headers:req.headers()});
});
page.on('response',async resp=>{
 const u=resp.url(); if(/api\.sdyanbao\.com\/api\/file|search|report/i.test(u)){
  const h=await resp.allHeaders().catch(()=>({})); const ct=h['content-type']||'';
  const row={url:u,status:resp.status(),ct,body:''};
  if(/json|text/i.test(ct)) row.body=(await resp.text().catch(()=>'' )).slice(0,2000000);
  resps.push(row);
  const blob=row.body;
  for(const m of blob.matchAll(/"id"\s*:\s*(\d+)[\s\S]{0,500}?"name"\s*:\s*"([^"]*趣致[^"]*)"/gi)) detailIds.add(Number(m[1]));
 }
});

for(const u of ['https://www.sdyanbao.com/report','https://www.sdyanbao.com/report?keyword=%E8%B6%A3%E8%87%B4%E9%9B%86%E5%9B%A2','https://www.sdyanbao.com/search?keyword=%E8%B6%A3%E8%87%B4%E9%9B%86%E5%9B%A2']){
 console.log('OPEN',u); await page.goto(u,{waitUntil:'domcontentloaded',timeout:60000}).catch(e=>console.log('GOTO_ERR',String(e))); await page.waitForTimeout(4000);
 const links=await page.locator('a').evaluateAll(as=>as.map(a=>({text:(a.textContent||'').trim(),href:a.href||''}))).catch(()=>[]);
 for(const a of links){const m=a.href.match(/sdyanbao\.com\/detail\/(\d+)/); if(m && /趣致集团|趣致集團|Qunabox|00917/i.test(a.text)) detailIds.add(Number(m[1]));}
}

const inputs=page.locator('input'); const n=await inputs.count(); console.log('INPUTS',n);
for(let i=0;i<n;i++){
 const input=inputs.nth(i); if(!(await input.isVisible().catch(()=>false)))continue;
 const ph=await input.getAttribute('placeholder').catch(()=>null); console.log('INPUT',i,ph);
 if(!/搜索|报告|研报|关键词|search/i.test(ph||''))continue;
 try{await input.fill('趣致集团');await page.waitForTimeout(2500);await input.press('Enter');await page.waitForTimeout(5000);
  const links=await page.locator('a').evaluateAll(as=>as.map(a=>({text:(a.textContent||'').trim(),href:a.href||''}))).catch(()=>[]);
  for(const a of links){const m=a.href.match(/sdyanbao\.com\/detail\/(\d+)/);if(m&&/趣致集团|趣致集團|Qunabox|00917/i.test(`${a.text} ${await page.locator('body').innerText().catch(()=> '')}`))detailIds.add(Number(m[1]));}
 }catch(e){console.log('INPUT_ERR',i,String(e));}
}
await page.waitForTimeout(2000);
fs.writeFileSync(path.join(OUT,'requests.json'),JSON.stringify(reqs,null,2));
fs.writeFileSync(path.join(OUT,'responses.json'),JSON.stringify(resps,null,2));
fs.writeFileSync(path.join(OUT,'search.html'),await page.content().catch(()=>''));

// Try observed/common search endpoints directly with multiple GET/POST shapes.
const endpoints=['https://api.sdyanbao.com/api/file/search','https://api.sdyanbao.com/api/file/list','https://api.sdyanbao.com/api/file/searchlist','https://api.sdyanbao.com/api/file/homelist'];
for(const endpoint of endpoints){
 for(const method of ['GET','POST']){
  for(const body of [{keyword:'趣致集团',page:1,pageSize:100},{key:'趣致集团',page:1,pageSize:100},{name:'趣致集团',page:1,pageSize:100},{search:'趣致集团',page:1,pageSize:100}]){
   try{
    const r=method==='GET'?await context.request.get(endpoint,{params:body,timeout:30000}):await context.request.post(endpoint,{data:body,timeout:30000});
    const text=await r.text(); console.log('API_PROBE',method,endpoint,r.status(),text.length,text.slice(0,300));
    for(const m of text.matchAll(/"id"\s*:\s*(\d+)[\s\S]{0,800}?"name"\s*:\s*"([^"]*趣致[^"]*)"/gi)) detailIds.add(Number(m[1]));
   }catch(e){console.log('API_ERR',method,endpoint,String(e));}
  }
 }
}
console.log('DETAIL_IDS',JSON.stringify([...detailIds]));

async function getDetail(id){
 const endpoint='https://api.sdyanbao.com/api/file/detail';
 for(const [method,opts] of [['GET',{params:{id}}],['POST',{data:{id}}],['POST',{form:{id}}]]){
  try{const r=method==='GET'?await context.request.get(endpoint,{...opts,timeout:30000}):await context.request.post(endpoint,{...opts,timeout:30000});const t=await r.text();
   if(r.status()===200 && /"status"\s*:\s*1/.test(t) && /趣致集团|趣致集團|Qunabox|00917/i.test(t)){console.log('DETAIL_OK',id,method,t.length);return JSON.parse(t).data;}
  }catch(e){}
 }
 return null;
}

async function buildFromImages(detail){
 const pageCount=Number(detail.page_count||0); const base=detail.page_url; if(!base||pageCount<2)return null;
 const images=[];
 for(let i=0;i<pageCount;i++){
  let got=null;
  for(const ext of ['png','jpg','jpeg']){
   const u=`${base}/${i}.${ext}`;
   try{const r=await context.request.get(u,{timeout:45000,headers:{Referer:`https://www.sdyanbao.com/detail/${detail.id}`}});const b=await r.body();const ct=r.headers()['content-type']||'';
    console.log('IMAGE',detail.id,i,ext,r.status(),ct,b.length);
    if(r.status()===200&&b.length>5000&&(b.slice(0,8).toString('hex').startsWith('89504e47')||b.slice(0,3).toString('hex')==='ffd8ff')){got={u,b,ext};break;}
   }catch(e){console.log('IMAGE_ERR',detail.id,i,ext,String(e));}
  }
  if(!got){console.log('MISSING_PAGE',detail.id,i);break;} images.push(got);
 }
 if(images.length!==pageCount){return {complete:false,downloaded:images.length,pageCount};}
 const pdf=await PDFDocument.create();
 for(const img of images){
  const embedded=img.ext==='png'?await pdf.embedPng(img.b):await pdf.embedJpg(img.b);
  const page=pdf.addPage([embedded.width,embedded.height]); page.drawImage(embedded,{x:0,y:0,width:embedded.width,height:embedded.height});
 }
 const bytes=await pdf.save({useObjectStreams:true}); const sha=crypto.createHash('sha256').update(bytes).digest('hex');
 const fn=`sdyanbao_${detail.id}_${sha.slice(0,12)}.pdf`; fs.writeFileSync(path.join(PDFDIR,fn),bytes);
 return {complete:true,downloaded:images.length,pageCount,fileName:fn,bytes:bytes.length,sha256:sha};
}

const manifest=[];
for(const id of [...detailIds]){
 const detail=await getDetail(id); if(!detail)continue;
 console.log('DETAIL',id,detail.name,detail.organization?.name,detail.page_count,detail.page_url);
 const built=await buildFromImages(detail);
 manifest.push({id,name:detail.name,organization:detail.organization?.name||'',date:detail.time_text||'',pageCount:detail.page_count,pageUrl:detail.page_url,fileSize:detail.file_size,built});
}
fs.writeFileSync(path.join(OUT,'detail_ids.json'),JSON.stringify([...detailIds],null,2));
fs.writeFileSync(path.join(OUT,'manifest.json'),JSON.stringify(manifest,null,2));
console.log('DONE',JSON.stringify(manifest));
await browser.close();
