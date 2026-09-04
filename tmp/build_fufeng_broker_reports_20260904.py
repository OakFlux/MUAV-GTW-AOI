from __future__ import annotations

import concurrent.futures
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse
from zipfile import ZIP_DEFLATED, ZipFile

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader

OUT = Path("out_fufeng_broker_reports_20260904")
PDF_DIR = OUT / "pdfs"
RENDER_DIR = OUT / "renders"
FINAL_ZIP = OUT / "Fufeng_Group_00546_Broker_Deep_Research_Reports.zip"
shutil.rmtree(OUT, ignore_errors=True)
PDF_DIR.mkdir(parents=True, exist_ok=True)
RENDER_DIR.mkdir(parents=True, exist_ok=True)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/pdf,application/json,*/*;q=0.8",
}
client = httpx.Client(
    headers=HEADERS,
    follow_redirects=True,
    http2=True,
    timeout=httpx.Timeout(90.0, connect=25.0),
)

SEARCH_QUERIES = [
    '"阜丰集团" "深度报告"',
    '"阜丰集团" "首次覆盖"',
    '"阜丰集团" "公司深度"',
    '"阜丰集团" "研究报告" pdf',
    '"00546.HK" "首次覆盖"',
    '"00546.HK" "深度" 研报',
    '"00546" "阜丰集团" 券商 研报',
    '"Fufeng Group" "initiation" report pdf',
    '"Fufeng Group" "company report" pdf',
    'site:pdf.dfcfw.com/pdf "阜丰集团"',
    'site:pdf.dfcfw.com "00546" "Fufeng"',
    'site:reportify.cc "阜丰集团"',
    'site:sdyanbao.com "阜丰集团"',
    'site:stock.finance.sina.com.cn "阜丰集团" 研报',
    'site:yanbao.stockstar.com "阜丰集团"',
]

DEEP_WORDS = re.compile(
    r"深度|首次覆盖|初次覆盖|公司研究|公司报告|价值分析|投资价值|龙头|成长|专题|"
    r"initiat(?:e|ion)|initiating coverage|company report|in-depth|deep dive|equity research",
    re.I,
)
UPDATE_WORDS = re.compile(
    r"点评|简评|快报|业绩公告|中报点评|年报点评|业绩点评|盈利预告|调研简报|晨报|日报|周报|"
    r"results review|earnings review|flash note|quick take|briefing",
    re.I,
)
EXCLUDE_WORDS = re.compile(
    r"年报|年度报告|annual report|中期报告|中期业绩|interim results|招股|prospectus|"
    r"环境.*报告|可持续|esg|股东大会|通函|公告|announcement",
    re.I,
)
IDENTITY_WORDS = re.compile(r"阜丰集团|阜豐集團|Fufeng\s+Group|00546(?:\.HK)?|546\s*HK", re.I)
BROKER_PATTERNS = [
    "国泰君安", "国金证券", "海通证券", "海通国际", "中信证券", "中金公司", "华泰证券",
    "招商证券", "兴业证券", "天风证券", "安信证券", "民生证券", "广发证券", "光大证券",
    "申万宏源", "东方证券", "国元证券", "西南证券", "浙商证券", "德邦证券", "中泰证券",
    "东吴证券", "长江证券", "银河证券", "平安证券", "东北证券", "开源证券", "东兴证券",
    "中银国际", "交银国际", "招银国际", "建银国际", "国泰君安国际", "第一上海",
    "DBS", "Citi", "Citigroup", "HSBC", "UBS", "Morgan Stanley", "Goldman Sachs", "Jefferies",
    "BOCI", "CICC", "CLSA", "Daiwa", "Macquarie", "Nomura", "Credit Suisse",
]


@dataclass
class LinkCandidate:
    url: str
    title: str = ""
    snippet: str = ""
    source_page: str = ""
    source_kind: str = "search"


@dataclass
class ValidReport:
    path: str
    url: str
    title_hint: str
    snippet: str
    source_page: str
    pages: int
    bytes: int
    sha256: str
    extracted_title: str
    broker: str
    year: int | None
    score: float


def clean_url(url: str) -> str:
    url = html.unescape(url.strip())
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    # Decode common Bing redirect target.
    try:
        parsed = urlparse(url)
        if parsed.netloc.endswith("bing.com") and parsed.path.startswith("/ck/a"):
            qs = parse_qs(parsed.query)
            for key in ("u", "url", "r"):
                if key in qs:
                    value = qs[key][0]
                    if value.startswith("a1"):
                        import base64
                        try:
                            value = base64.urlsafe_b64decode(value[2:] + "===").decode("utf-8")
                        except Exception:
                            pass
                    if value.startswith("http"):
                        return value
    except Exception:
        pass
    return url


def add_candidate(store: dict[str, LinkCandidate], candidate: LinkCandidate) -> None:
    url = clean_url(candidate.url)
    if not url.startswith(("http://", "https://")):
        return
    if any(host in url.lower() for host in ("baidu.com/link?", "bing.com/ck/a")):
        return
    # Strip fragments and common tracking params without destroying download tokens.
    parsed = urlparse(url)
    if parsed.fragment:
        url = parsed._replace(fragment="").geturl()
    key = url.lower()
    current = store.get(key)
    if current is None:
        candidate.url = url
        store[key] = candidate
    else:
        if len(candidate.title) > len(current.title):
            current.title = candidate.title
        if len(candidate.snippet) > len(current.snippet):
            current.snippet = candidate.snippet
        if candidate.source_page and not current.source_page:
            current.source_page = candidate.source_page


def search_ddgs(store: dict[str, LinkCandidate]) -> None:
    try:
        from ddgs import DDGS
    except Exception as exc:
        print("DDGS import failed", exc)
        return
    for query in SEARCH_QUERIES:
        try:
            print("DDGS", query)
            with DDGS(timeout=20) as ddgs:
                results = list(ddgs.text(query, region="wt-wt", safesearch="off", max_results=40))
            for item in results:
                href = str(item.get("href") or item.get("url") or "")
                title = str(item.get("title") or "")
                body = str(item.get("body") or item.get("snippet") or "")
                if IDENTITY_WORDS.search(f"{title} {body} {href}"):
                    add_candidate(store, LinkCandidate(href, title, body, source_kind="ddgs"))
        except Exception as exc:
            print("DDGS query failed", query, repr(exc))
        time.sleep(0.5)


def search_bing_html(store: dict[str, LinkCandidate]) -> None:
    for query in SEARCH_QUERIES:
        url = "https://www.bing.com/search?q=" + quote(query) + "&count=50&setlang=zh-hans"
        try:
            response = client.get(url, timeout=40)
            print("BING", response.status_code, len(response.content), query)
            soup = BeautifulSoup(response.text, "html.parser")
            for result in soup.select("li.b_algo"):
                a = result.select_one("h2 a")
                if not a:
                    continue
                href = str(a.get("href") or "")
                title = a.get_text(" ", strip=True)
                snippet_el = result.select_one(".b_caption p")
                snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""
                if IDENTITY_WORDS.search(f"{title} {snippet} {href}"):
                    add_candidate(store, LinkCandidate(href, title, snippet, source_kind="bing"))
        except Exception as exc:
            print("Bing query failed", query, repr(exc))
        time.sleep(0.3)


def collect_eastmoney_api(store: dict[str, LinkCandidate]) -> None:
    base = "https://reportapi.eastmoney.com/report/list"
    code_variants = ["00546", "00546.HK", "HK00546", "546"]
    for code in code_variants:
        params = {
            "pageSize": "100",
            "industryCode": "*",
            "industry": "*",
            "rating": "*",
            "ratingChange": "*",
            "beginTime": "2007-01-01",
            "endTime": "2026-09-04",
            "pageNo": "1",
            "fields": "",
            "qType": "0",
            "orgCode": "",
            "code": code,
            "rcode": "",
            "p": "1",
            "pageNum": "1",
            "pageNumber": "1",
        }
        try:
            response = client.get(base, params=params, headers={**HEADERS, "Referer": "https://data.eastmoney.com/"})
            print("EASTMONEY", code, response.status_code, len(response.content), response.text[:80])
            text = response.text.strip()
            if text.startswith("{") or text.startswith("["):
                payload = response.json()
            else:
                match = re.search(r"\((\{.*\}|\[.*\])\)\s*;?\s*$", text, re.S)
                payload = json.loads(match.group(1)) if match else {}
            data = payload.get("data") if isinstance(payload, dict) else payload
            if not isinstance(data, list):
                continue
            for item in data:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or item.get("TITLE") or "")
                org = str(item.get("orgSName") or item.get("orgName") or "")
                researcher = str(item.get("researcher") or "")
                info_code = str(item.get("infoCode") or item.get("INFOCODE") or item.get("infocode") or "")
                if not IDENTITY_WORDS.search(f"{title} {item}"):
                    continue
                if info_code:
                    for pdf_url in (
                        f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf",
                        f"https://pdf.dfcfw.com/pdf/H2_{info_code}_1.pdf",
                        f"https://pdf.dfcfw.com/pdf/H3_{info_code}.pdf",
                    ):
                        add_candidate(store, LinkCandidate(pdf_url, title, f"{org} {researcher}", source_page=f"https://data.eastmoney.com/report/zw_stock.jshtml?infocode={info_code}", source_kind="eastmoney_api"))
                for key in ("attachPath", "pdfUrl", "url", "fileUrl"):
                    value = item.get(key)
                    if isinstance(value, str) and value:
                        add_candidate(store, LinkCandidate(urljoin(base, value), title, f"{org} {researcher}", source_kind="eastmoney_api"))
        except Exception as exc:
            print("Eastmoney API failed", code, repr(exc))


def extract_from_page(candidate: LinkCandidate, store: dict[str, LinkCandidate]) -> None:
    url = candidate.url
    try:
        response = client.get(url, timeout=45)
    except Exception as exc:
        print("PAGE GET failed", url, repr(exc))
        return
    content_type = response.headers.get("content-type", "").lower()
    if response.content[:5] == b"%PDF-" or "application/pdf" in content_type:
        return
    if response.status_code >= 400 or len(response.content) > 8_000_000:
        return
    text = response.text
    base = str(response.url)
    # Direct PDF URLs and encoded URLs in scripts/JSON.
    patterns = [
        r"https?://[^\s\"'<>\\]+\.pdf(?:\?[^\s\"'<>\\]*)?",
        r"(?:https?:)?//[^\s\"'<>\\]+\.pdf(?:\?[^\s\"'<>\\]*)?",
        r"(?:\.\.?/|/)[^\s\"'<>\\]+\.pdf(?:\?[^\s\"'<>\\]*)?",
    ]
    found: set[str] = set()
    for pattern in patterns:
        for match in re.findall(pattern, text, re.I):
            found.add(urljoin(base, html.unescape(match).replace("\\/", "/")))
    # Eastmoney AP IDs embedded in pages.
    for info_code in set(re.findall(r"AP\d{12,24}", text, re.I)):
        for pdf_url in (
            f"https://pdf.dfcfw.com/pdf/H3_{info_code.upper()}_1.pdf",
            f"https://pdf.dfcfw.com/pdf/H2_{info_code.upper()}_1.pdf",
        ):
            found.add(pdf_url)
    # Look at href/src/data attributes.
    soup = BeautifulSoup(text, "html.parser")
    for tag in soup.find_all(["a", "iframe", "embed", "object", "source"]):
        for attr in ("href", "src", "data", "data-url", "data-href", "download-url"):
            value = tag.get(attr)
            if isinstance(value, str) and (".pdf" in value.lower() or "download" in value.lower()):
                found.add(urljoin(base, html.unescape(value)))
    for pdf_url in found:
        add_candidate(store, LinkCandidate(pdf_url, candidate.title, candidate.snippet, source_page=url, source_kind="page_extract"))


def expand_candidate_pages(store: dict[str, LinkCandidate]) -> None:
    initial = list(store.values())
    page_candidates = []
    for candidate in initial:
        lower = candidate.url.lower()
        if lower.split("?", 1)[0].endswith(".pdf"):
            continue
        if any(host in lower for host in (
            "eastmoney.com", "dfcfw.com", "reportify.cc", "sdyanbao.com", "stockstar.com",
            "sina.com", "sina.cn", "xueqiu.com", "hexun.com", "roadshowing.com", "researchinchina.com",
            "dbs.com", "pdf", "research", "report", "yanbao",
        )):
            page_candidates.append(candidate)
    print("EXPANDING PAGES", len(page_candidates))
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(extract_from_page, candidate, store) for candidate in page_candidates[:160]]
        for future in concurrent.futures.as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                print("page expansion worker failed", repr(exc))


def download_candidate(candidate: LinkCandidate, index: int) -> tuple[LinkCandidate, Path] | None:
    url = candidate.url
    lower = url.lower()
    if not lower.split("?", 1)[0].endswith(".pdf") and "pdf" not in lower and "download" not in lower:
        return None
    destination = OUT / "candidates" / f"candidate_{index:04d}.pdf"
    destination.parent.mkdir(parents=True, exist_ok=True)
    headers = {
        **HEADERS,
        "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.5",
        "Referer": candidate.source_page or "https://www.google.com/",
    }
    try:
        with client.stream("GET", url, headers=headers, timeout=120) as response:
            if response.status_code >= 400:
                return None
            total = 0
            with destination.open("wb") as handle:
                for chunk in response.iter_bytes(1024 * 1024):
                    total += len(chunk)
                    if total > 80_000_000:
                        raise RuntimeError("PDF too large")
                    handle.write(chunk)
        if destination.stat().st_size < 80_000:
            destination.unlink(missing_ok=True)
            return None
        with destination.open("rb") as handle:
            if handle.read(5) != b"%PDF-":
                destination.unlink(missing_ok=True)
                return None
        return candidate, destination
    except Exception:
        destination.unlink(missing_ok=True)
        return None


def infer_broker(text: str) -> str:
    for broker in BROKER_PATTERNS:
        if re.search(re.escape(broker), text, re.I):
            return broker
    # Common report-cover style: first non-empty line ending in securities/international.
    for line in text.splitlines()[:80]:
        line = re.sub(r"\s+", " ", line).strip()
        if re.search(r"证券|證券|国际|國際|research|securities", line, re.I) and 2 <= len(line) <= 40:
            return line[:40]
    return "未识别机构"


def infer_title(text: str, hint: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if 6 <= len(line) <= 100]
    for line in lines[:120]:
        if IDENTITY_WORDS.search(line) and not EXCLUDE_WORDS.search(line):
            return line
    return re.sub(r"\s+", " ", hint).strip()[:160] or "阜丰集团公司研究报告"


def inspect_candidate(pair: tuple[LinkCandidate, Path]) -> ValidReport | None:
    candidate, path = pair
    try:
        reader = PdfReader(str(path), strict=False)
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                return None
        pages = len(reader.pages)
        if pages < 8:
            return None
        text_parts = []
        for page in reader.pages[: min(35, pages)]:
            try:
                text_parts.append(page.extract_text() or "")
            except Exception:
                pass
        text = "\n".join(text_parts)
        combined = f"{candidate.title}\n{candidate.snippet}\n{text}"
        if not IDENTITY_WORDS.search(combined):
            return None
        if EXCLUDE_WORDS.search(candidate.title) and not DEEP_WORDS.search(candidate.title):
            return None
        # Exclude corporate filings and presentations even if search noise points to them.
        head = combined[:12000]
        if re.search(r"ANNUAL REPORT|年度报告|年報|INTERIM REPORT|中期報告|招股章程", head, re.I) and not re.search(r"证券研究报告|證券研究報告|equity research|research report", head, re.I):
            return None
        broker = infer_broker(combined)
        extracted_title = infer_title(text, candidate.title)
        year_matches = [int(x) for x in re.findall(r"\b(20(?:0\d|1\d|2[0-6]))\b", f"{candidate.title} {text[:5000]}")]
        year = max(year_matches) if year_matches else None
        score = 0.0
        score += min(pages, 60) * 1.2
        if pages >= 15:
            score += 35
        if pages >= 25:
            score += 20
        if DEEP_WORDS.search(combined[:12000]):
            score += 50
        if UPDATE_WORDS.search(candidate.title):
            score -= 40
        if candidate.source_kind == "eastmoney_api":
            score += 20
        if broker != "未识别机构":
            score += 20
        if year:
            score += max(0, year - 2010) * 0.8
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return ValidReport(
            path=str(path), url=candidate.url, title_hint=candidate.title, snippet=candidate.snippet,
            source_page=candidate.source_page, pages=pages, bytes=path.stat().st_size,
            sha256=digest, extracted_title=extracted_title, broker=broker, year=year, score=score,
        )
    except Exception as exc:
        print("PDF inspect failed", path, repr(exc))
        return None


def select_reports(reports: list[ValidReport]) -> list[ValidReport]:
    # Deduplicate exact files and highly similar title/page combinations.
    by_hash: dict[str, ValidReport] = {}
    for report in reports:
        current = by_hash.get(report.sha256)
        if current is None or report.score > current.score:
            by_hash[report.sha256] = report
    reports = sorted(by_hash.values(), key=lambda r: r.score, reverse=True)
    selected: list[ValidReport] = []
    used_brokers: set[str] = set()
    title_keys: set[str] = set()
    # First pass: genuine long-form pieces, with broker diversity.
    for report in reports:
        key = re.sub(r"[^\w\u4e00-\u9fff]", "", report.extracted_title.lower())[:45]
        if report.pages < 12:
            continue
        if report.broker in used_brokers and report.broker != "未识别机构":
            continue
        if key and any(key[:20] in existing or existing[:20] in key for existing in title_keys):
            continue
        selected.append(report)
        used_brokers.add(report.broker)
        title_keys.add(key)
        if len(selected) == 3:
            break
    # Second pass allows same broker if necessary.
    if len(selected) < 2:
        selected_hashes = {r.sha256 for r in selected}
        for report in reports:
            if report.sha256 in selected_hashes or report.pages < 10:
                continue
            selected.append(report)
            selected_hashes.add(report.sha256)
            if len(selected) == 3:
                break
    if len(selected) < 2:
        raise RuntimeError(f"Only {len(selected)} suitable full reports found; valid candidate count={len(reports)}")
    return selected[:3]


def safe_name(text: str, max_len: int = 50) -> str:
    text = re.sub(r"[\\/:*?\"<>|\r\n]+", "_", text).strip(" ._")
    text = re.sub(r"\s+", " ", text)
    return text[:max_len] or "阜丰集团研究报告"


def render_cover(pdf_path: Path, index: int) -> Path:
    prefix = RENDER_DIR / f"report_{index:02d}"
    subprocess.run(
        ["pdftoppm", "-f", "1", "-l", "1", "-png", "-singlefile", "-r", "100", str(pdf_path), str(prefix)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    png = Path(str(prefix) + ".png")
    if not png.exists() or png.stat().st_size < 10_000:
        raise RuntimeError(f"Cover render failed for {pdf_path}")
    return png


candidates: dict[str, LinkCandidate] = {}
collect_eastmoney_api(candidates)
search_ddgs(candidates)
search_bing_html(candidates)
expand_candidate_pages(candidates)

# Add any newly found direct PDF links from Eastmoney AP IDs embedded in all metadata.
all_candidates = list(candidates.values())
print("TOTAL LINK CANDIDATES", len(all_candidates))
(OUT / "all_link_candidates.json").write_text(json.dumps([asdict(x) for x in all_candidates], ensure_ascii=False, indent=2), encoding="utf-8")

pdf_like = [c for c in all_candidates if c.url.lower().split("?", 1)[0].endswith(".pdf") or "download" in c.url.lower()]
# Prefer candidates whose metadata already looks relevant; retain broad fallback pool.
pdf_like.sort(key=lambda c: (
    1 if IDENTITY_WORDS.search(f"{c.title} {c.snippet} {c.url}") else 0,
    1 if DEEP_WORDS.search(f"{c.title} {c.snippet}") else 0,
    1 if "dfcfw.com" in c.url.lower() else 0,
), reverse=True)
print("PDF-LIKE CANDIDATES", len(pdf_like))

pairs: list[tuple[LinkCandidate, Path]] = []
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
    future_map = {executor.submit(download_candidate, candidate, idx): candidate for idx, candidate in enumerate(pdf_like[:240], 1)}
    for future in concurrent.futures.as_completed(future_map):
        result = future.result()
        if result:
            pairs.append(result)
print("DOWNLOADED PDF CANDIDATES", len(pairs))

valid_reports: list[ValidReport] = []
for pair in pairs:
    report = inspect_candidate(pair)
    if report:
        valid_reports.append(report)
print("VALID REPORTS", len(valid_reports))
for report in sorted(valid_reports, key=lambda r: r.score, reverse=True):
    print("VALID", json.dumps(asdict(report), ensure_ascii=False))
(OUT / "valid_reports.json").write_text(json.dumps([asdict(r) for r in valid_reports], ensure_ascii=False, indent=2), encoding="utf-8")

selected = select_reports(valid_reports)
manifest = []
for idx, report in enumerate(selected, 1):
    source = Path(report.path)
    broker = safe_name(report.broker, 25)
    title = safe_name(report.extracted_title, 55)
    year = str(report.year) if report.year else "年份未识别"
    filename = f"{idx:02d}_{broker}_{year}_{title}.pdf"
    destination = PDF_DIR / filename
    shutil.copy2(source, destination)
    render = render_cover(destination, idx)
    manifest.append({
        "index": idx,
        "broker": report.broker,
        "year": report.year,
        "title": report.extracted_title,
        "pages": report.pages,
        "bytes": report.bytes,
        "filename": filename,
        "source_url": report.url,
        "source_page": report.source_page,
        "sha256": report.sha256,
        "cover_render_bytes": render.stat().st_size,
    })

readme_lines = [
    "阜丰集团（00546.HK）券商深度研究报告合集",
    "",
    "本压缩包仅收录公开可获取、能够完整下载并通过PDF校验的公司研究报告。",
    "筛选优先级：首次覆盖/公司深度/长篇公司研究；排除年报、中期报告、公告和短篇业绩点评。",
    "",
    "报告清单：",
]
for item in manifest:
    readme_lines.append(f"{item['index']}. {item['broker']}｜{item['year'] or '年份未识别'}｜{item['pages']}页｜{item['title']}")
readme_lines += [
    "",
    "校验：已检查PDF文件签名、实际页数、阜丰集团/00546身份信息，并渲染首页核对可读性；ZIP完整性已测试。",
    "来源：各券商公开研究文件或公开研报分发页面。仅供个人研究使用，版权归原发布机构所有。",
]
(PDF_DIR / "README_报告清单与说明.txt").write_text("\n".join(readme_lines), encoding="utf-8")
(PDF_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

with ZipFile(FINAL_ZIP, "w", ZIP_DEFLATED, compresslevel=9) as archive:
    for path in sorted(PDF_DIR.iterdir(), key=lambda p: p.name):
        archive.write(path, arcname=path.name)
with ZipFile(FINAL_ZIP) as archive:
    bad = archive.testzip()
    if bad is not None:
        raise RuntimeError(f"ZIP integrity failure: {bad}")
    pdf_names = [name for name in archive.namelist() if name.lower().endswith(".pdf")]
    if len(pdf_names) != len(manifest) or len(pdf_names) < 2:
        raise RuntimeError(f"Unexpected PDF count in ZIP: {len(pdf_names)}")

print("PACKAGE_READY", FINAL_ZIP, FINAL_ZIP.stat().st_size)
print("SELECTED_MANIFEST", json.dumps(manifest, ensure_ascii=False, indent=2))
client.close()
