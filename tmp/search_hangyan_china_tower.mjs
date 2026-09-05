import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const OUT = path.resolve('out_hangyan_china_tower_search');
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36',
  locale: 'zh-CN',
  viewport: { width: 1440, height: 1200 },
  acceptDownloads: true,
});
const page = await context.newPage();
const events = [];
page.on('request', req => {
  const u = req.url();
  const pd = req.postData() || '';
  if (/search|algolia|autocomplete|report|document|pdf|query|suggest|api/i.test(`${u} ${pd}`)) {
    events.push({t:'request',method:req.method(),url:u,resourceType:req.resourceType(),postData:pd});
  }
});
page.on('response', async resp => {
  const u = resp.url();
  const h = await resp.allHeaders().catch(() => ({}));
  const ct = h['content-type'] || '';
  if (!/search|algolia|autocomplete|report|document|pdf|query|suggest|api/i.test(`${u} ${ct}`)) return;
  const item = {t:'response',status:resp.status(),url:u,contentType:ct,headers:h};
  if (/json|text|javascript|html/i.test(ct)) item.preview=(await resp.text().catch(()=>'' )).slice(0,300000);
  events.push(item);
});

console.log('OPEN reports');
await page.goto('https://www.hangyan.co/reports', {waitUntil:'domcontentloaded',timeout:90000});
await page.waitForTimeout(6000);
console.log('URL',page.url(),'title',await page.title());

const inputs = page.locator('input[type="search"]');
console.log('INPUT_COUNT',await inputs.count());
for (let i=0;i<await inputs.count();i++) {
  console.log('INPUT',i,await inputs.nth(i).getAttribute('id'),await inputs.nth(i).getAttribute('placeholder'));
}
const input = inputs.last();
await input.click();
await input.fill('中国铁塔');
await page.waitForTimeout(7000);
console.log('AFTER_TYPE_URL',page.url());

const bodyText = await page.locator('body').innerText();
console.log('BODY_SNIP',bodyText.slice(0,10000));
await page.screenshot({path:path.join(OUT,'after_search.png'),fullPage:true});
fs.writeFileSync(path.join(OUT,'after_search.html'),await page.content());
fs.writeFileSync(path.join(OUT,'after_search.txt'),bodyText);

const dom = await page.evaluate(() => ({
  url: location.href,
  title: document.title,
  anchors:[...document.querySelectorAll('a')].map((a,i)=>({i,text:(a.innerText||a.textContent||'').trim(),href:a.href,outer:a.outerHTML.slice(0,2000)})),
  panels:[...document.querySelectorAll('[role="listbox"],.aa-Panel,.aa-PanelLayout,.aa-Item,.aa-Source')].map((e,i)=>({i,text:(e.innerText||'').slice(0,20000),outer:e.outerHTML.slice(0,30000)})),
  scripts:[...document.scripts].map((s,i)=>({i,src:s.src,text:(s.textContent||'').slice(0,50000)})),
  localStorage:{...localStorage},sessionStorage:{...sessionStorage},
}));
fs.writeFileSync(path.join(OUT,'dom.json'),JSON.stringify(dom,null,2));

// Press Enter as a public search action and capture the result page.
await input.press('Enter').catch(()=>{});
await page.waitForTimeout(8000);
console.log('AFTER_ENTER_URL',page.url());
const resultText=await page.locator('body').innerText().catch(()=> '');
fs.writeFileSync(path.join(OUT,'after_enter.html'),await page.content().catch(()=>''));
fs.writeFileSync(path.join(OUT,'after_enter.txt'),resultText);
await page.screenshot({path:path.join(OUT,'after_enter.png'),fullPage:true}).catch(()=>{});

// Collect all report links now present and visit up to 20 China Tower results.
const links=await page.locator('a').evaluateAll(nodes=>nodes.map(a=>({text:(a.innerText||a.textContent||'').trim(),href:a.href})).filter(x=>x.href.includes('/reports/'))).catch(()=>[]);
const unique=[...new Map(links.map(x=>[x.href,x])).values()];
console.log('REPORT_LINKS',JSON.stringify(unique));
fs.writeFileSync(path.join(OUT,'report_links.json'),JSON.stringify(unique,null,2));

const candidateLinks=unique.filter(x=>/中国铁塔|中國鐵塔|china tower/i.test(`${x.text} ${x.href}`)).slice(0,20);
for (let i=0;i<candidateLinks.length;i++) {
  const item=candidateLinks[i];
  const p=await context.newPage();
  const subevents=[];
  p.on('response',async r=>{
    const u=r.url();const h=await r.allHeaders().catch(()=>({}));const ct=h['content-type']||'';
    if (/pdf|document|report/i.test(`${u} ${ct}`)) subevents.push({status:r.status(),url:u,contentType:ct,headers:h});
  });
  try {
    await p.goto(item.href,{waitUntil:'domcontentloaded',timeout:60000});
    await p.waitForTimeout(4000);
    const t=await p.locator('body').innerText().catch(()=> '');
    const html=await p.content();
    fs.writeFileSync(path.join(OUT,`candidate_${i}.txt`),t);
    fs.writeFileSync(path.join(OUT,`candidate_${i}.html`),html);
    fs.writeFileSync(path.join(OUT,`candidate_${i}_network.json`),JSON.stringify(subevents,null,2));
    console.log('CANDIDATE',i,item.href,(await p.title()),JSON.stringify(subevents));
  } catch(e) {console.log('CANDIDATE_ERR',i,String(e));}
  await p.close();
}

fs.writeFileSync(path.join(OUT,'network.json'),JSON.stringify(events,null,2));
console.log('EVENTS',events.length);
for(const e of events) console.log('EVENT',JSON.stringify(e).slice(0,5000));
await browser.close();
