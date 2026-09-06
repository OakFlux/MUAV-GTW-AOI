from __future__ import annotations

import hashlib
import html
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

OUT = Path("out_ascletis_hangyan")
PDFS = OUT / "pdfs"
OUT.mkdir(exist_ok=True)
PDFS.mkdir(exist_ok=True)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36"
S = requests.Session()
S.headers.update({
    "User-Agent": UA,
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.hangyan.co/",
})

INDEX_PAGES = [
    "https://www.hangyan.co/charts/3601111842144912396",  # Dongwu 19-chart deep report
    "https://www.hangyan.co/charts/3368457946139723748",  # carries 2026-04-01 related report links
    "https://www.hangyan.co/charts/3641608452108715914",  # carries 2026-04-06 related report links
    "https://www.hangyan.co/reports/3448696034581022433",  # Guoyuan known report
]

KEYWORDS = (
    "歌礼制药", "歌禮製藥", "Ascletis", "01672", "1672.HK",
    "ASC30注册临床", "代谢管线全面推进", "全新GLP-1减重不减肌",
)


def get(url: str, *, attempts: int = 4) -> requests.Response:
    last = None
    for i in range(1, attempts + 1):
        try:
            r = S.get(url, timeout=60)
            print("GET", r.status_code, r.headers.get("content-type"), len(r.content), r.url)
            r.raise_for_status()
            return r
        except Exception as exc:
            last = exc
            print("GET_RETRY", i, url, repr(exc))
            time.sleep(i * 2)
    raise RuntimeError(f"GET failed: {url}: {last}")


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def relevant(text: str) -> bool:
    low = text.lower()
    return any(k.lower() in low for k in KEYWORDS)


def collect_urls(text: str, base: str) -> list[str]:
    urls = set()
    for raw in re.findall(r"https?://[^\"'<>\\\s]+", text):
        urls.add(html.unescape(raw).replace("\\/", "/").replace("\\u0026", "&"))
    for raw in re.findall(r"(?:href|src|data-url|data-file|fileUrl|pdfUrl|downloadUrl)[\"'\s:=]+([^\"'<>\s]+)", text, re.I):
        urls.add(urljoin(base, html.unescape(raw).replace("\\/", "/").replace("\\u0026", "&")))
    return sorted(urls)


report_pages: dict[str, dict] = {}
index_diagnostics = []

for idx, url in enumerate(INDEX_PAGES):
    try:
        r = get(url)
    except Exception as exc:
        index_diagnostics.append({"url": url, "error": repr(exc)})
        continue
    text = r.text
    (OUT / f"index_{idx}.html").write_text(text, encoding="utf-8")
    soup = BeautifulSoup(text, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = urljoin(str(r.url), a.get("href"))
        label = clean_text(a.get_text(" ", strip=True))
        if "/reports/" in href:
            links.append({"href": href, "label": label})
            if relevant(label) or url.endswith("3448696034581022433"):
                report_pages[href] = {"discovered_from": url, "anchor_text": label}
                print("REPORT_LINK", label, href)
    # Regex fallback catches JS-rendered route strings.
    for rid in set(re.findall(r"(?:/reports/|reportId[\"'\s:=]+)(\d{12,})", text, re.I)):
        href = f"https://www.hangyan.co/reports/{rid}"
        context_index = text.find(rid)
        context = clean_text(text[max(0, context_index - 500):context_index + 700])
        if relevant(context):
            report_pages[href] = {"discovered_from": url, "anchor_text": context[:500]}
            print("REPORT_REGEX", href, context[:250])
    index_diagnostics.append({"url": url, "status": r.status_code, "links": links})

# Always keep the known Guoyuan report.
report_pages.setdefault(
    "https://www.hangyan.co/reports/3448696034581022433",
    {"discovered_from": "known", "anchor_text": "歌礼制药-B：创新药研发推进顺利，BD合作空间广阔"},
)

found = []
seen_hashes = set()

for n, (report_url, discovery) in enumerate(report_pages.items()):
    try:
        r = get(report_url)
    except Exception as exc:
        found.append({"report_url": report_url, "error": repr(exc), **discovery})
        continue
    text = r.text
    (OUT / f"report_{n}.html").write_text(text, encoding="utf-8")
    page_text = clean_text(BeautifulSoup(text, "html.parser").get_text(" "))
    title_match = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    title = clean_text(title_match.group(1)) if title_match else discovery.get("anchor_text", "")
    urls = collect_urls(text, str(r.url))
    pdf_candidates = [
        u.rstrip("\\\"'),;]") for u in urls
        if ".pdf" in u.lower() or "documents" in u.lower() or "download" in u.lower()
    ]
    print("REPORT", report_url, title, "PDF_CANDIDATES", pdf_candidates[:30])
    row = {
        "report_url": report_url,
        "title": title,
        "page_text_preview": page_text[:3000],
        "pdf_candidates": pdf_candidates,
        **discovery,
    }
    downloaded = []
    for j, pdf_url in enumerate(dict.fromkeys(pdf_candidates)):
        try:
            pr = get(pdf_url, attempts=2)
            data = pr.content
            if len(data) < 50_000 or not data.startswith(b"%PDF-"):
                continue
            digest = hashlib.sha256(data).hexdigest()
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            path = PDFS / f"hangyan_{n:02d}_{j:02d}_{digest[:12]}.pdf"
            path.write_bytes(data)
            reader = PdfReader(str(path), strict=False)
            pages = len(reader.pages)
            extracted = "\n".join((p.extract_text() or "") for p in reader.pages[:min(12, pages)])
            identity = relevant(extracted) or relevant(page_text) or relevant(title)
            meta = {
                "path": str(path),
                "source_url": pdf_url,
                "pages": pages,
                "bytes": len(data),
                "sha256": digest,
                "identity_ok": identity,
                "text_preview": extracted[:4000],
            }
            downloaded.append(meta)
            print("PDF_VALID", json.dumps({k: v for k, v in meta.items() if k != "text_preview"}, ensure_ascii=False))
        except Exception as exc:
            print("PDF_CANDIDATE_ERROR", pdf_url, repr(exc))
    row["downloads"] = downloaded
    found.append(row)

(OUT / "index_diagnostics.json").write_text(json.dumps(index_diagnostics, ensure_ascii=False, indent=2), encoding="utf-8")
(OUT / "report_results.json").write_text(json.dumps(found, ensure_ascii=False, indent=2), encoding="utf-8")
print("DONE", "report_pages", len(report_pages), "unique_pdfs", len(seen_hashes))
