import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import crypto from 'crypto';

const OUT = path.resolve('out_ascletis_reportify_probe');
const PDFDIR = path.join(OUT, 'pdfs');
fs.rmSync(OUT, {recursive:true, force:true});
fs.mkdirSync(PDFDIR, {recursive:true});
const UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36';
const ids=new Set(['1104529108471255040','1104550200514580480','1028312670044033024']);
const queries=['歌礼制药','歌礼制药 口服小分子率先破局','口服小分子率先破局 紧跟减重前沿'];
const apiItems=[];
function norm(s){return String(s||'').replace(/\\u0026/g,'&').replace(/\\u003[dD]/g,'=').replace(/\\u003[fF]/g,'?').replace(/\\u002F/g,'/').replace(/\\\//g,'/').replace(/&amp;/g,'&').replace(/[\\"'<>),;]+$/g,'');}
function urlsIn(s){return [...new Set((String(s||'').match(/https?:[^"'\\\s<>]+/g)||[]).map(norm))];}
function isPdf(b){return b&&b.length>50000&&b.subarray(0,5).toString()==='%PDF-';}
const hashes=new Set(); const saved=[];
function savePdf(b,label,url){if(!isPdf(b))return;const h=crypto.createHash('sha256').update(b).digest('hex');if(hashes.has(h))return;hashes.add(h);const f=path.join(PDFDIR,`${label.replace(/[^A-Za-z0-9_.-]+/g,'_')}_${h.slice(0,12)}.pdf`);fs.writeFileSync(f,b);saved.push({file:f,label,url,bytes:b.length,sha256:h});console.log('SAVED',f,b.length,url);}

for(const q of queries){
 const u=`https://api.reportify.cn/reports?query=${encodeURIComponent(q)}&page_num=1&page_size=100`;
 const r=await fetch(u,{headers:{'User-Agent':UA,Accept:'application/json',Referer:'https://reportify.cn/'}});const t=await r.text();fs.writeFileSync(path.join(OUT,`search_${crypto.createHash('md5').update(q).digest('hex')}.json`),t);console.log('SEARCH',q,r.status,t.length);
 try{const o=JSON.parse(t);for(const x of (o.items||o.data||[])){const b=JSON.stringify(x);if(/歌礼制药|Ascletis|01672|1672\.HK|口服小分子率先破局/i.test(b)){apiItems.push(x);if(x.report_id)ids.add(String(x.report_id));console.log('ITEM',JSON.stringify(x));}}}catch{}
}
fs.writeFileSync(path.join(OUT,'matched_items.json'),JSON.stringify(apiItems,null,2));

const browser=await chromium.launch({headless:true});
for(const id of ids){
 const context=await browser.newContext({userAgent:UA,locale:'zh-CN',acceptDownloads:true,viewport:{width:1440,height:1200}});
 const page=await context.newPage();const log=[];const candidates=new Set();
 page.on('response',async r=>{const u=norm(r.url());const h=await r.allHeaders().catch(()=>({}));const ct=String(h['content-type']||'').toLowerCase();if(/api\.reportify|\.pdf|download|document|report\/preview/i.test(u)){const e={type:'response',status:r.status(),url:u,contentType:ct};if(ct.includes('json'))e.body=(await r.text().catch(()=>'' )).slice(0,200000);log.push(e);}if(ct.includes('application/pdf')||/\.pdf(?:[?#]|$)/i.test(u)){try{savePdf(await r.body(),`reportify_${id}`,u);}catch{}}});
 page.on('download',async d=>{try{const p=await d.path();if(p&&fs.existsSync(p))savePdf(fs.readFileSync(p),`reportify_${id}_download`,d.url());}catch{}});
 const pageUrl=`https://reportify.cn/reports/${id}`;console.log('OPEN',pageUrl);await page.goto(pageUrl,{waitUntil:'domcontentloaded',timeout:90000}).catch(e=>console.log('GOTO_ERR',String(e)));await page.waitForTimeout(10000);
 for(const pat of [/查看全文/i,/阅读全文/i,/下载/i]){const l=page.getByText(pat).first();if(await l.count().catch(()=>0)){await l.click({timeout:5000,force:true}).catch(()=>{});await page.waitForTimeout(5000);}}
 for(const f of [0.25,0.5,0.75,1]){await page.evaluate(x=>scrollTo(0,document.body.scrollHeight*x),f).catch(()=>{});await page.waitForTimeout(2000);}
 const html=await page.content().catch(()=>'');fs.writeFileSync(path.join(OUT,`report_${id}.html`),html);fs.writeFileSync(path.join(OUT,`report_${id}.txt`),await page.locator('body').innerText().catch(()=>''));await page.screenshot({path:path.join(OUT,`report_${id}.png`),fullPage:true}).catch(()=>{});
 const dom=await page.evaluate(()=>({resources:performance.getEntriesByType('resource').map(x=>x.name),attrs:[...document.querySelectorAll('a,iframe,embed,object,img,source')].flatMap(e=>['href','src','data','data-src','data-url','data-file','currentSrc'].map(k=>e[k]||e.getAttribute?.(k)||'')).filter(Boolean),scripts:[...document.scripts].map(s=>s.src||s.textContent||'')})).catch(()=>({resources:[],attrs:[],scripts:[]}));
 for(const u of urlsIn([html,...dom.resources,...dom.attrs,...dom.scripts,...log.map(x=>x.body||'')].join('\n'))){if(/\.pdf(?:[?#]|$)|s\.reportify\.cn|files\.reportify.*report|download/i.test(u))candidates.add(u);}
 const endpoints=[`https://api.reportify.cn/reports/${id}`,`https://api.reportify.cn/reports/${id}/analysis`,`https://api.reportify.cn/reports/${id}/space`,`https://api.reportify.cn/reports/${id}/download`];
 for(const u of [...endpoints,...candidates]){try{const r=await context.request.get(u,{timeout:45000,headers:{Referer:pageUrl,Accept:'application/pdf,application/json,*/*'}});const b=Buffer.from(await r.body());const ct=String(r.headers()['content-type']||'');const e={type:'probe',status:r.status(),url:u,contentType:ct,bytes:b.length};if(ct.includes('json')||ct.includes('text'))e.body=b.toString('utf8').slice(0,200000);log.push(e);if(isPdf(b))savePdf(b,`reportify_${id}_probe`,u);for(const n of urlsIn(e.body||'')){if(/\.pdf(?:[?#]|$)|s\.reportify\.cn/i.test(n)){const rr=await context.request.get(n,{timeout:45000,headers:{Referer:pageUrl,Accept:'application/pdf,*/*'}}).catch(()=>null);if(rr){const bb=Buffer.from(await rr.body());if(isPdf(bb))savePdf(bb,`reportify_${id}_nested`,n);}}}}catch(e){log.push({type:'probe_error',url:u,error:String(e)});}}
 fs.writeFileSync(path.join(OUT,`report_${id}_events.json`),JSON.stringify(log,null,2));await context.close();
}
fs.writeFileSync(path.join(OUT,'saved.json'),JSON.stringify(saved,null,2));await browser.close();console.log('DONE',saved.length);
