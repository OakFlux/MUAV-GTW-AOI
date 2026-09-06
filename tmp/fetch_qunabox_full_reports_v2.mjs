import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import crypto from 'crypto';

const OUT = path.resolve('out_qunabox_full_reports_v2');
const RAW = path.join(OUT, 'raw_pdfs');
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(RAW, { recursive: true });

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';
const keywords = ['趣致集团', '趣致集團', 'Qunabox', '00917', '0917.HK', '00917.HK'];
const candidatePages = new Set();
const pdfUrls = new Set();
const saved = [];
const diagnostics = { pages: [], eastmoney: [], sdyanbao: [], searches: [] };

function sha256(buf) { return crypto.createHash('sha256').update(buf).digest('hex'); }
function relevantText(text='') { const s = text.toLowerCase().replace(/\s+/g, ''); return keywords.some(k => s.includes(k.toLowerCase().replace(/\s+/g,''))); }
function safeName(s) { return s.replace(/[^A-Za-z0-9_.-]+/g, '_').slice(0, 100); }

async function savePdfBuffer(buf, url, label, meta={}) {
  if (!buf || buf.length < 50000 || buf.subarray(0,5).toString() !== '%PDF-') return null;
  const hash = sha256(buf);
  if (saved.some(x => x.sha256 === hash)) return saved.find(x => x.sha256 === hash);
  const fileName = `${safeName(label)}_${hash.slice(0,12)}.pdf`;
  const filePath = path.join(RAW, fileName);
  fs.writeFileSync(filePath, buf);
  const row = { fileName, filePath, url, bytes: buf.length, sha256: hash, ...meta };
  saved.push(row);
  console.log('PDF_SAVED', JSON.stringify(row));
  return row;
}

async function fetchPdf(request, url, label, meta={}) {
  try {
    const r = await request.get(url, { headers: { 'User-Agent': UA, 'Accept': 'application/pdf,application/octet-stream;q=0.9,*/*;q=0.5', 'Referer': meta.referer || 'https://www.hangyan.co/' }, timeout: 90000 });
    const ct = r.headers()['content-type'] || '';
    const body = await r.body();
    console.log('PDF_FETCH', r.status(), ct, body.length, url);
    if (r.status() === 200) return await savePdfBuffer(body, url, label, meta);
  } catch (e) { console.log('PDF_FETCH_ERR', url, String(e)); }
  return null;
}

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ userAgent: UA, locale: 'zh-CN', acceptDownloads: true, ignoreHTTPSErrors: true });
const request = context.request;

// Known public official full report: West Bull initiation, Chinese version.
await fetchPdf(request,
  'http://www.westbullsec.com.hk/upload/2e/d2/2ed2f834fdd55836be06d987b4fc46a1.pdf',
  'westbull_2026_08_24_cn',
  { brokerHint: '西牛证券', dateHint: '2026-08-24', titleHint: '存量终端迈入AI变现周期，高毛利业务有望获得重估', referer: 'http://www.westbullsec.com.hk/research' }
);

// Also keep English only as a fallback, but packaging will de-duplicate by report title.
await fetchPdf(request,
  'http://www.westbullsec.com.hk/upload/b1/7e/b17e479fa9fe90cbe6e6138a022c2cfe.pdf',
  'westbull_2026_08_24_en',
  { brokerHint: 'West Bull Securities', dateHint: '2026-08-24', titleHint: 'Legacy Terminal Base Enters AI Monetisation Cycle', referer: 'http://www.westbullsec.com.hk/research' }
);

async function inspectPage(url, label, clickReport=true) {
  const page = await context.newPage();
  const seenResponses = [];
  page.on('response', async resp => {
    const u = resp.url();
    const ct = (await resp.allHeaders().catch(()=>({})))['content-type'] || '';
    if (/application\/pdf|cdn\.hangyan\.co\/documents|\.pdf(?:\?|$)/i.test(`${ct} ${u}`)) {
      seenResponses.push({u, status: resp.status(), ct});
      pdfUrls.add(u);
      try {
        const b = await resp.body();
        await savePdfBuffer(b, u, `${label}_network`, { referer: page.url() });
      } catch (e) { console.log('RESPONSE_PDF_ERR', u, String(e)); }
    }
  });
  try {
    console.log('OPEN', label, url);
    const nav = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 90000 });
    await page.waitForTimeout(7000);
    const html = await page.content();
    const text = await page.locator('body').innerText().catch(()=> '');
    const title = await page.title().catch(()=> '');
    fs.writeFileSync(path.join(OUT, `${safeName(label)}.html`), html);
    fs.writeFileSync(path.join(OUT, `${safeName(label)}.txt`), text);
    const anchors = await page.locator('a').evaluateAll(nodes => nodes.map(a => ({text:(a.innerText||a.textContent||'').trim(), href:a.href}))).catch(()=>[]);
    for (const a of anchors) {
      if (/\/reports\/\d+/.test(a.href)) candidatePages.add(a.href);
      if (/\.pdf(?:\?|$)/i.test(a.href)) pdfUrls.add(a.href);
    }
    for (const m of html.matchAll(/https?:\\?\/\\?\/[^"'<>\s]+\.pdf(?:\?[^"'<>\s]*)?/gi)) pdfUrls.add(m[0].replace(/\\\//g,'/'));
    for (const m of html.matchAll(/https?:\\?\/\\?\/www\.hangyan\.co\/reports\/\d+/gi)) candidatePages.add(m[0].replace(/\\\//g,'/'));
    diagnostics.pages.push({label,url,finalUrl:page.url(),status:nav?.status(),title,textPreview:text.slice(0,1000),anchors:anchors.filter(a=>/reports|pdf|阅读研究报告|完整报告/i.test(`${a.text} ${a.href}`)).slice(0,200),responses:seenResponses});
    console.log('PAGE_META', label, nav?.status(), page.url(), title, 'anchors', anchors.length, 'rel', relevantText(`${title}\n${text}`));

    if (clickReport) {
      const selectors = [
        page.getByText('阅读研究报告', {exact:false}).first(),
        page.getByText('查看研究报告', {exact:false}).first(),
        page.getByText('查看完整报告', {exact:false}).first(),
      ];
      for (const loc of selectors) {
        if (await loc.count().catch(()=>0)) {
          const before = page.url();
          try {
            await loc.click({ timeout: 5000, force: true });
            await page.waitForTimeout(5000);
            console.log('CLICK_REPORT', label, before, '=>', page.url());
            if (/\/reports\/\d+/.test(page.url())) candidatePages.add(page.url());
          } catch (e) { console.log('CLICK_REPORT_ERR', label, String(e)); }
        }
      }
    }
  } catch (e) { console.log('PAGE_ERR', label, url, String(e)); }
  await page.close();
}

// The public Hangyan chart pages belong to the 29-page BOCI initiation report.
await inspectPage('https://www.hangyan.co/charts/3545791843998368928', 'hangyan_boci_chart_1', true);
await inspectPage('https://www.hangyan.co/charts/3545791848435942587', 'hangyan_boci_chart_2', true);

// Direct search surfaces.
for (const [i,url] of [
  'https://www.hangyan.co/reports?q=%E8%B6%A3%E8%87%B4%E9%9B%86%E5%9B%A2',
  'https://www.hangyan.co/search?q=%E8%B6%A3%E8%87%B4%E9%9B%86%E5%9B%A2',
  'https://www.hangyan.co/?q=%E8%B6%A3%E8%87%B4%E9%9B%86%E5%9B%A2',
].entries()) await inspectPage(url, `hangyan_search_${i}`, false);

// Try Hangyan's own search UI to reveal its JSON/API route and report links.
{
  const page = await context.newPage();
  const network = [];
  page.on('response', async resp => {
    const u=resp.url(); const h=await resp.allHeaders().catch(()=>({})); const ct=h['content-type']||'';
    if (/search|report|graphql|api|autocomplete|algolia/i.test(u) && (/json|text/i.test(ct) || !ct)) {
      let preview=''; try { preview=(await resp.text()).slice(0,20000); } catch {}
      network.push({url:u,status:resp.status(),ct,preview});
      for (const m of preview.matchAll(/https?:\\?\/\\?\/www\.hangyan\.co\/reports\/\d+|\/reports\/\d+/gi)) {
        const x=m[0].replace(/\\\//g,'/'); candidatePages.add(x.startsWith('http')?x:`https://www.hangyan.co${x}`);
      }
    }
  });
  try {
    await page.goto('https://www.hangyan.co/reports', {waitUntil:'domcontentloaded',timeout:90000});
    await page.waitForTimeout(5000);
    const inputs=page.locator('input'); const n=await inputs.count();
    for(let i=0;i<n;i++){
      const inp=inputs.nth(i); const ph=await inp.getAttribute('placeholder').catch(()=>null);
      const tp=await inp.getAttribute('type').catch(()=>null);
      if (tp==='hidden') continue;
      try { await inp.fill('趣致集团'); await inp.press('Enter'); await page.waitForTimeout(8000); } catch {}
    }
    const anchors=await page.locator('a').evaluateAll(ns=>ns.map(a=>({text:(a.innerText||'').trim(),href:a.href}))).catch(()=>[]);
    for(const a of anchors) if(/\/reports\/\d+/.test(a.href)) candidatePages.add(a.href);
    diagnostics.searches.push({url:page.url(),inputs:n,anchors:anchors.filter(a=>/趣致|Qunabox|00917|reports/.test(`${a.text} ${a.href}`)).slice(0,300),network});
    fs.writeFileSync(path.join(OUT,'hangyan_ui_search.html'),await page.content());
    fs.writeFileSync(path.join(OUT,'hangyan_ui_search.txt'),await page.locator('body').innerText().catch(()=>''));
  } catch(e){ console.log('HANGYAN_UI_ERR',String(e)); }
  await page.close();
}

// Public Sdyanbao search API. Only use direct PDF URLs if the API explicitly supplies them; do not reconstruct gated pages.
for (const payload of [
  {keyword:'趣致集团',page:1,limit:100},
  {key:'趣致集团',page:1,page_size:100},
  {search:'趣致集团',page:1,limit:100},
]) {
  try {
    const r=await request.post('https://api.sdyanbao.com/api/file/search',{form:payload,headers:{'User-Agent':UA,'Referer':'https://www.sdyanbao.com/'},timeout:60000});
    const text=await r.text(); diagnostics.sdyanbao.push({payload,status:r.status(),preview:text.slice(0,50000)});
    console.log('SDY_SEARCH',r.status(),text.length,JSON.stringify(payload));
    let obj; try{obj=JSON.parse(text);}catch{continue;}
    const files=obj?.data?.files || obj?.data || [];
    if(Array.isArray(files)) for(const f of files){
      if(!relevantText(JSON.stringify(f))) continue;
      console.log('SDY_MATCH',JSON.stringify(f));
      for(const k of ['online_url','file_url','download_url','pdf_url','url']){
        const u=f[k]; if(typeof u==='string' && /\.pdf(?:\?|$)/i.test(u)) pdfUrls.add(u.replace(/\\\//g,'/'));
      }
    }
  } catch(e){console.log('SDY_ERR',String(e));}
}

// Eastmoney report API, including narrow date windows for known initiation/update reports.
async function eastmoneyGet(params,label){
  const qs=new URLSearchParams(params).toString();
  try{
    const r=await request.get(`https://reportapi.eastmoney.com/report/list?${qs}`,{headers:{'User-Agent':UA,'Referer':'https://data.eastmoney.com/report/'},timeout:60000});
    const text=await r.text(); console.log('EM_GET',label,r.status(),text.length);
    let obj; try{obj=JSON.parse(text);}catch{return;}
    diagnostics.eastmoney.push({label,meta:{TotalPage:obj.TotalPage,TotalCount:obj.TotalCount,hits:obj.hits},rows:(obj.data||[]).length});
    for(const row of (obj.data||[])){
      if(!relevantText(JSON.stringify(row))) continue;
      console.log('EM_MATCH',JSON.stringify(row));
      const info=row.infoCode; if(info){ pdfUrls.add(`https://pdf.dfcfw.com/pdf/H3_${info}_1.pdf`); pdfUrls.add(`https://pdf.dfcfw.com/pdf/H3_${info}.pdf`); }
    }
  }catch(e){console.log('EM_GET_ERR',label,String(e));}
}
for(const code of ['00917','0917','917','HK00917','00917.HK','']){
  await eastmoneyGet({code,pageSize:'200',pageNo:'1',beginTime:'2024-01-01',endTime:'2026-09-06',qType:'0',fields:'',industryCode:'*',industry:'*',rating:'*',ratingChange:'*',orgCode:'',rcode:'',p:'1',pageNum:'1',pageNumber:'1'},`code_${code||'blank'}`);
}
for(const [start,end] of [['2025-01-10','2025-01-20'],['2026-03-08','2026-03-18'],['2026-07-20','2026-08-31']]){
  // Page through narrow windows, capped to avoid excessive requests.
  const common={code:'',pageSize:'100',beginTime:start,endTime:end,qType:'0',fields:'',industryCode:'*',industry:'*',rating:'*',ratingChange:'*',orgCode:'',rcode:''};
  for(let p=1;p<=40;p++){
    const before=diagnostics.eastmoney.length;
    await eastmoneyGet({...common,pageNo:String(p),p:String(p),pageNum:String(p),pageNumber:String(p)},`window_${start}_${end}_p${p}`);
    const rec=diagnostics.eastmoney.at(-1);
    if(diagnostics.eastmoney.length===before || !rec || rec.rows<100) break;
  }
}

// Inspect candidate report pages discovered from chart/search links.
console.log('CANDIDATE_REPORT_PAGES',JSON.stringify([...candidatePages]));
for(const [i,u] of [...candidatePages].entries()) await inspectPage(u,`hangyan_report_${i}`,false);

// Explicit FxBaogao candidates discovered previously; metadata may identify Huayuan/West Bull. Do not bypass any access control.
for(const id of ['5630239','5630240']){
  try{
    const r=await request.get(`https://api.fxbaogao.com/mofoun/report/report/getReportPreviewImages?reportId=${id}`,{headers:{'User-Agent':UA,'Referer':`https://www.fxbaogao.com/detail/${id}`}});
    diagnostics.pages.push({label:`fx_${id}_preview_api`,status:r.status(),body:(await r.text()).slice(0,5000)});
  }catch{}
  await inspectPage(`https://www.fxbaogao.com/detail/${id}`,`fx_${id}`,false);
}

// Download every publicly exposed PDF candidate and validate later in Python.
for(const [i,u0] of [...pdfUrls].entries()){
  const u=u0.replace(/&amp;/g,'&').replace(/\\\//g,'/');
  await fetchPdf(request,u,`candidate_${i}`,{referer:'https://www.hangyan.co/'});
}

fs.writeFileSync(path.join(OUT,'fetch_manifest.json'),JSON.stringify(saved,null,2));
fs.writeFileSync(path.join(OUT,'diagnostics.json'),JSON.stringify(diagnostics,null,2));
console.log('FETCH_DONE','saved',saved.length,'reportPages',candidatePages.size,'pdfUrls',pdfUrls.size);
await browser.close();
