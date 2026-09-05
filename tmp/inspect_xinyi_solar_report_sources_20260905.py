from __future__ import annotations

import asyncio
import hashlib
import html
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from pypdf import PdfReader
from playwright.async_api import async_playwright

OUT = Path("out_xinyi_solar_report_inspection")
OUT.mkdir(exist_ok=True)
PDFS = OUT / "pdfs"
PDFS.mkdir(exist_ok=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36"

session = requests.Session()
session.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})

TARGETS = [
    ("2025_huachuang", "https://www.fxbaogao.com/detail/4751513"),
    ("2025_huachuang_view", "https://www.fxbaogao.com/view?id=4751513"),
    ("2025_sgpjbg", "https://www.sgpjbg.com/bgdown/622483.html"),
    ("2025_sgpjbg_main", "https://www.sgpjbg.com/baogao/622483.html"),
    ("2025_vzkoo", "https://www.vzkoo.com/read/2025033140156a90946ec4ab421372b6.html"),
    ("2023_guosen", "https://www.fxbaogao.com/detail/3766045"),
    ("2023_guosen_view", "https://www.fxbaogao.com/view?id=3766045"),
    ("2023_futu", "https://news.futunn.com/hk/post/28255017/xinyi-solar-energy-00968-hk-deepening-the-photovoltaic-glass-industry"),
    ("2019_sohu", "https://www.sohu.com/a/301415039_313170"),
    ("2026_hangyan", "https://www.hangyan.co/reports/3843608737805763979"),
]

KEYWORDS = [
    "信义光能", "信義光能", "Xinyi Solar", "00968", "0968.HK",
    "全球光伏玻璃龙头", "深耕光伏玻璃行业", "严冬过尽绽春蕾",
]


def is_target_text(text: str) -> bool:
    lowered = text.lower()
    return any(k.lower() in lowered for k in KEYWORDS)


def save_pdf_bytes(data: bytes, source_url: str, label: str) -> dict | None:
    if len(data) < 50_000 or not data.startswith(b"%PDF-"):
        return None
    digest = hashlib.sha256(data).hexdigest()
    path = PDFS / f"{label}_{digest[:12]}.pdf"
    path.write_bytes(data)
    try:
        reader = PdfReader(str(path), strict=False)
        pages = len(reader.pages)
        sample = "\n".join((p.extract_text() or "") for p in reader.pages[: min(15, pages)])
    except Exception as exc:
        print("PDF_PARSE_ERROR", source_url, repr(exc))
        return None
    norm = re.sub(r"\s+", "", sample).lower()
    identity = any(token in norm for token in ["信义光能", "信義光能", "xinyisolar", "00968", "0968hk"])
    meta = {
        "label": label,
        "source_url": source_url,
        "path": str(path),
        "pages": pages,
        "bytes": len(data),
        "sha256": digest,
        "identity_ok": identity,
        "sample": sample[:4000],
    }
    print("VALID_PDF", json.dumps({k: v for k, v in meta.items() if k != "sample"}, ensure_ascii=False))
    return meta


def try_download_pdf(url: str, label: str) -> dict | None:
    try:
        r = session.get(url, timeout=90, headers={"Referer": "https://www.fxbaogao.com/", "Accept": "application/pdf,application/octet-stream,*/*"})
        print("PDF_PROBE", r.status_code, r.headers.get("content-type"), len(r.content), url)
        return save_pdf_bytes(r.content, str(r.url), label)
    except Exception as exc:
        print("PDF_DOWNLOAD_ERROR", url, repr(exc))
        return None


results: dict = {"eastmoney": [], "requests_pages": [], "browser": [], "pdfs": []}
seen_pdf_urls: set[str] = set()

# 1. Eastmoney public report API: exact date windows and code variants.
windows = [
    ("2025-03-20", "2025-04-05"),
    ("2023-06-15", "2023-07-10"),
    ("2019-03-01", "2019-04-15"),
    ("2020-01-01", "2022-12-31"),
]
for begin, end in windows:
    params = {
        "industryCode": "*", "pageSize": "100", "industry": "*", "rating": "*", "ratingChange": "*",
        "beginTime": begin, "endTime": end, "pageNo": "1", "fields": "", "qType": "0",
        "orgCode": "", "code": "", "rcode": "", "p": "1", "pageNum": "1", "pageNumber": "1",
    }
    try:
        first = session.get("https://reportapi.eastmoney.com/report/list", params=params, timeout=60).json()
        pages = int(first.get("TotalPage") or 0)
        print("EASTMONEY_WINDOW", begin, end, "pages", pages, "hits", first.get("hits"))
        for page_no in range(1, pages + 1):
            params.update({"pageNo": page_no, "p": page_no, "pageNum": page_no, "pageNumber": page_no})
            obj = session.get("https://reportapi.eastmoney.com/report/list", params=params, timeout=60).json()
            for row in obj.get("data") or []:
                blob = json.dumps(row, ensure_ascii=False)
                if is_target_text(blob):
                    results["eastmoney"].append(row)
                    print("EASTMONEY_MATCH", json.dumps(row, ensure_ascii=False))
                    info = row.get("infoCode")
                    if info:
                        url = f"https://pdf.dfcfw.com/pdf/H3_{info}_1.pdf"
                        if url not in seen_pdf_urls:
                            seen_pdf_urls.add(url)
                            meta = try_download_pdf(url, f"eastmoney_{info}")
                            if meta:
                                results["pdfs"].append(meta)
            time.sleep(0.08)
    except Exception as exc:
        print("EASTMONEY_ERROR", begin, end, repr(exc))

# 2. Plain HTML inspection and public API probes.
for label, url in TARGETS:
    try:
        r = session.get(url, timeout=60)
        text = r.text
        (OUT / f"{label}.html").write_text(text, encoding="utf-8", errors="ignore")
        item = {"label": label, "url": url, "status": r.status_code, "final_url": str(r.url), "bytes": len(r.content), "content_type": r.headers.get("content-type", "")}
        print("PAGE", json.dumps(item, ensure_ascii=False))
        candidates = set()
        for pattern in [
            r"https?://[^\"'<>\\\s]+\.pdf(?:\?[^\"'<>\\\s]*)?",
            r"https?://cdn\.hangyan\.co/documents/[^\"'<>\\\s]+",
            r"https?://file\.sgpjbg\.com/[^\"'<>\\\s]+",
        ]:
            candidates.update(html.unescape(x).replace("\\/", "/") for x in re.findall(pattern, text, re.I))
        for attr in re.findall(r"(?:href|src|data-src|data-url|data-file)=[\"']([^\"']+)[\"']", text, re.I):
            absolute = urljoin(str(r.url), html.unescape(attr))
            if ".pdf" in absolute.lower() or "documents/" in absolute.lower():
                candidates.add(absolute)
        print("PAGE_PDF_CANDIDATES", label, json.dumps(sorted(candidates), ensure_ascii=False))
        item["pdf_candidates"] = sorted(candidates)
        results["requests_pages"].append(item)
        for idx, candidate in enumerate(sorted(candidates)):
            if candidate in seen_pdf_urls:
                continue
            seen_pdf_urls.add(candidate)
            meta = try_download_pdf(candidate, f"{label}_{idx}")
            if meta:
                results["pdfs"].append(meta)
    except Exception as exc:
        print("PAGE_ERROR", label, repr(exc))

for rid in ["4751513", "3766045"]:
    for method in [
        "getReportPreviewImages", "getReportDetail", "getReportInfo", "getReportById",
        "getReport", "getReportFile", "getReportDownloadUrl", "getDownloadUrl",
    ]:
        url = f"https://api.fxbaogao.com/mofoun/report/report/{method}?reportId={rid}"
        try:
            r = session.get(url, timeout=30)
            preview = r.text[:5000]
            print("FX_API", rid, method, r.status_code, r.headers.get("content-type"), len(r.content), preview[:500])
            (OUT / f"fx_{rid}_{method}.txt").write_text(preview, encoding="utf-8", errors="ignore")
            for candidate in re.findall(r"https?://[^\"'<>\\\s]+\.pdf(?:\?[^\"'<>\\\s]*)?", preview, re.I):
                candidate = html.unescape(candidate).replace("\\/", "/")
                if candidate not in seen_pdf_urls:
                    seen_pdf_urls.add(candidate)
                    meta = try_download_pdf(candidate, f"fxapi_{rid}_{method}")
                    if meta:
                        results["pdfs"].append(meta)
        except Exception as exc:
            print("FX_API_ERROR", rid, method, repr(exc))


async def browser_inspection() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=UA, locale="zh-CN", accept_downloads=True, viewport={"width": 1440, "height": 1100})

        # First search Hangyan dynamically for all Xinyi Solar reports.
        search_page = await context.new_page()
        hangyan_events: list[dict] = []
        report_urls: set[str] = set()

        async def record_response(resp):
            u = resp.url
            ct = (await resp.all_headers()).get("content-type", "")
            if any(k in u.lower() for k in ["algolia", "search", "report", "document"]):
                row = {"status": resp.status, "url": u, "content_type": ct}
                if "json" in ct or "text" in ct:
                    try:
                        row["preview"] = (await resp.text())[:20000]
                    except Exception:
                        pass
                hangyan_events.append(row)

        search_page.on("response", record_response)
        try:
            await search_page.goto("https://www.hangyan.co/reports", wait_until="domcontentloaded", timeout=90000)
            await search_page.wait_for_timeout(5000)
            inputs = search_page.locator("input[type=search], .aa-Input, input[placeholder*='搜索'], input[placeholder*='报告']")
            count = await inputs.count()
            print("HANGYAN_INPUTS", count)
            for i in range(count):
                loc = inputs.nth(i)
                try:
                    await loc.fill("信义光能", timeout=5000)
                    await search_page.wait_for_timeout(5000)
                    anchors = await search_page.locator("a").evaluate_all("els => els.map(a => ({text:(a.innerText||'').trim(), href:a.href})).filter(x => x.href)")
                    for a in anchors:
                        if "/reports/" in a["href"] and ("信义光能" in a["text"] or "信義光能" in a["text"]):
                            report_urls.add(a["href"])
                    await loc.press("Enter")
                    await search_page.wait_for_timeout(5000)
                except Exception as exc:
                    print("HANGYAN_INPUT_ERROR", i, repr(exc))
            body = await search_page.locator("body").inner_text()
            (OUT / "hangyan_search.txt").write_text(body, encoding="utf-8")
            (OUT / "hangyan_search.html").write_text(await search_page.content(), encoding="utf-8")
            await search_page.screenshot(path=str(OUT / "hangyan_search.png"), full_page=True)
            anchors = await search_page.locator("a").evaluate_all("els => els.map(a => ({text:(a.innerText||'').trim(), href:a.href})).filter(x => x.href)")
            for a in anchors:
                if "/reports/" in a["href"] and is_target_text(a["text"] + " " + a["href"]):
                    report_urls.add(a["href"])
        except Exception as exc:
            print("HANGYAN_SEARCH_ERROR", repr(exc))
        (OUT / "hangyan_network.json").write_text(json.dumps(hangyan_events, ensure_ascii=False, indent=2), encoding="utf-8")

        # Parse report IDs/URLs from captured JSON bodies too.
        for event in hangyan_events:
            preview = event.get("preview", "")
            if is_target_text(preview):
                for match in re.findall(r"https?://www\.hangyan\.co/reports/\d+|/reports/\d+", preview):
                    report_urls.add(urljoin("https://www.hangyan.co", match))
                for rid in re.findall(r'\b(?:id|objectID)[\"\']?\s*[:=]\s*[\"\']?(\d{15,22})', preview):
                    report_urls.add(f"https://www.hangyan.co/reports/{rid}")
        print("HANGYAN_REPORT_URLS", json.dumps(sorted(report_urls), ensure_ascii=False))

        # Add known page.
        report_urls.add("https://www.hangyan.co/reports/3843608737805763979")

        all_targets = TARGETS + [(f"hangyan_{i}", u) for i, u in enumerate(sorted(report_urls))]
        for label, url in all_targets:
            page = await context.new_page()
            events: list[dict] = []
            discovered: set[str] = set()

            async def on_response(resp):
                u = resp.url
                headers = await resp.all_headers()
                ct = headers.get("content-type", "")
                if u.lower().endswith(".pdf") or "application/pdf" in ct or "octet-stream" in ct or "documents/" in u or "report-image" in u:
                    events.append({"status": resp.status, "url": u, "content_type": ct, "content_length": headers.get("content-length", "")})
                    if u.lower().endswith(".pdf") or "application/pdf" in ct or "documents/" in u:
                        discovered.add(u)

            page.on("response", on_response)
            try:
                nav = await page.goto(url, wait_until="domcontentloaded", timeout=90000)
                await page.wait_for_timeout(8000)
                for phrase in ["点击免费查看完整报告", "免费查看完整报告", "查看全文", "阅读全文", "预览"]:
                    loc = page.get_by_text(phrase, exact=False).first
                    if await loc.count():
                        try:
                            await loc.click(timeout=3000)
                            await page.wait_for_timeout(5000)
                        except Exception:
                            pass
                dom = await page.evaluate("""() => ({
                    title: document.title,
                    url: location.href,
                    html: document.documentElement.outerHTML,
                    anchors: [...document.querySelectorAll('a')].map(a => ({text:(a.innerText||'').trim(),href:a.href})),
                    images: [...document.images].map(i => ({src:i.src,currentSrc:i.currentSrc,w:i.naturalWidth,h:i.naturalHeight,alt:i.alt})),
                    embeds: [...document.querySelectorAll('iframe,embed,object')].map(e => ({src:e.src||e.data||'',outer:e.outerHTML})),
                })""")
                (OUT / f"browser_{label}.html").write_text(dom["html"], encoding="utf-8", errors="ignore")
                (OUT / f"browser_{label}_dom.json").write_text(json.dumps({k:v for k,v in dom.items() if k != "html"}, ensure_ascii=False, indent=2), encoding="utf-8")
                await page.screenshot(path=str(OUT / f"browser_{label}.png"), full_page=True)
                for a in dom["anchors"]:
                    if ".pdf" in a["href"].lower() or "documents/" in a["href"].lower():
                        discovered.add(a["href"])
                for e in dom["embeds"]:
                    if ".pdf" in e["src"].lower() or "documents/" in e["src"].lower():
                        discovered.add(e["src"])
                for candidate in re.findall(r"https?://[^\"'<>\\\s]+\.pdf(?:\?[^\"'<>\\\s]*)?", dom["html"], re.I):
                    discovered.add(html.unescape(candidate).replace("\\/", "/"))
                meta = {"label": label, "url": url, "nav_status": nav.status if nav else None, "final_url": page.url, "title": dom["title"], "events": events, "pdfs": sorted(discovered)}
                results["browser"].append(meta)
                print("BROWSER", json.dumps({k:v for k,v in meta.items() if k != "events"}, ensure_ascii=False))
            except Exception as exc:
                print("BROWSER_ERROR", label, repr(exc))
            for idx, candidate in enumerate(sorted(discovered)):
                if candidate in seen_pdf_urls:
                    continue
                seen_pdf_urls.add(candidate)
                meta = try_download_pdf(candidate, f"browser_{label}_{idx}")
                if meta:
                    results["pdfs"].append(meta)
            await page.close()
        await browser.close()

asyncio.run(browser_inspection())

# Deduplicate PDF metadata by SHA.
dedup: dict[str, dict] = {}
for item in results["pdfs"]:
    dedup[item["sha256"]] = item
results["pdfs"] = list(dedup.values())
(OUT / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print("INSPECTION_DONE", "pdfs", len(results["pdfs"]))
for item in results["pdfs"]:
    print("PDF_SUMMARY", json.dumps({k:v for k,v in item.items() if k != "sample"}, ensure_ascii=False))
