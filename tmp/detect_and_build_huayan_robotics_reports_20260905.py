from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse
from zipfile import ZIP_DEFLATED, ZipFile

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader

REQUESTED = "华沿机器人"
OUT = Path("out_huayan_robotics_reports_20260905")
RAW = OUT / "raw"
REPORTS = OUT / "reports"
RENDERS = OUT / "renders"
FINAL_ZIP = OUT / "Huayan_Robotics_Broker_Deep_Reports.zip"
shutil.rmtree(OUT, ignore_errors=True)
RAW.mkdir(parents=True)
REPORTS.mkdir(parents=True)
RENDERS.mkdir(parents=True)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
client = httpx.Client(
    http2=True,
    follow_redirects=True,
    timeout=httpx.Timeout(90.0, connect=30.0),
    headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7"},
)


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"\s+", "", text).lower()


def fetch_text(url: str, *, referer: str | None = None) -> str:
    headers = {"Referer": referer} if referer else None
    last = None
    for attempt in range(1, 4):
        try:
            r = client.get(url, headers=headers)
            r.raise_for_status()
            return r.text
        except Exception as exc:
            last = exc
            time.sleep(attempt * 1.5)
    raise RuntimeError(f"failed to fetch {url}: {last}")


def bing_rss(query: str) -> list[dict]:
    url = "https://www.bing.com/search?format=rss&q=" + quote(query)
    text = fetch_text(url)
    items = []
    try:
        root = ET.fromstring(text)
        for item in root.findall(".//item"):
            items.append({
                "title": html.unescape(item.findtext("title") or ""),
                "link": html.unescape(item.findtext("link") or ""),
                "description": html.unescape(item.findtext("description") or ""),
            })
    except Exception:
        soup = BeautifulSoup(text, "html.parser")
        for node in soup.select("li.b_algo"):
            a = node.select_one("h2 a")
            p = node.select_one(".b_caption p")
            if a:
                items.append({"title": a.get_text(" ", strip=True), "link": a.get("href") or "", "description": p.get_text(" ", strip=True) if p else ""})
    return items


def baidu_results(query: str) -> list[dict]:
    url = "https://www.baidu.com/s?wd=" + quote(query)
    try:
        text = fetch_text(url)
    except Exception:
        return []
    soup = BeautifulSoup(text, "html.parser")
    out = []
    for node in soup.select("div.result, div.c-container")[:20]:
        a = node.select_one("h3 a")
        if not a:
            continue
        out.append({"title": a.get_text(" ", strip=True), "link": a.get("href") or "", "description": node.get_text(" ", strip=True)})
    return out


queries = [
    '"华沿机器人"',
    '"华沿机器人" 上市 公司 股票代码',
    '"华沿机器人" 券商 研报',
    '"华研机器人" 上市公司',
    '"华研机器人" 券商 研报',
]
search_results: list[dict] = []
for q in queries:
    for source, fn in (("bing", bing_rss), ("baidu", baidu_results)):
        try:
            rows = fn(q)
            for row in rows:
                row = dict(row)
                row.update({"query": q, "source": source})
                search_results.append(row)
            print("SEARCH", source, q, len(rows))
        except Exception as exc:
            print("SEARCH_ERROR", source, q, repr(exc))

(RAW / "search_results.json").write_text(json.dumps(search_results, ensure_ascii=False, indent=2), encoding="utf-8")
search_blob = "\n".join(f"{r['title']} {r['description']} {r['link']}" for r in search_results)
search_norm = norm(search_blob)

# Candidate listed issuers. A candidate is accepted only when exact-name web search
# repeatedly links the ambiguous wording to that issuer or its security code.
CANDIDATES = [
    {
        "entity": "华研精机",
        "code": "301138",
        "market": "A",
        "aliases": ["华研精机", "广州华研精密机械", "301138"],
        "cooccurrence": ["华研机器人", "华沿机器人"],
    },
    {
        "entity": "地平线机器人-W",
        "code": "09660",
        "market": "HK",
        "aliases": ["地平线机器人", "09660", "9660.hk", "horizon robotics"],
        "cooccurrence": ["华沿机器人"],
    },
    {
        "entity": "机器人",
        "code": "300024",
        "market": "A",
        "aliases": ["机器人股份", "新松机器人", "300024"],
        "cooccurrence": ["华沿机器人"],
    },
]

# Score only exact-query rows more strongly; generic variant rows are secondary.
def candidate_score(candidate: dict) -> tuple[int, list[str]]:
    evidence = []
    score = 0
    for row in search_results:
        blob = norm(f"{row['title']} {row['description']} {row['link']}")
        alias_hits = [a for a in candidate["aliases"] if norm(a) in blob]
        if not alias_hits:
            continue
        exact_query = "华沿机器人" in row["query"]
        variant_query = "华研机器人" in row["query"]
        increment = 3 if exact_query else 1 if variant_query else 0
        score += increment
        evidence.append(f"{row['source']}｜{row['query']}｜{row['title']}｜{','.join(alias_hits)}｜+{increment}")
    # Direct co-occurrence in one result is decisive.
    for row in search_results:
        blob = norm(f"{row['title']} {row['description']}")
        if any(norm(x) in blob for x in candidate["cooccurrence"]) and any(norm(a) in blob for a in candidate["aliases"]):
            score += 4
            evidence.append(f"COOCCURRENCE｜{row['title']}｜+4")
    return score, evidence

scored = []
for c in CANDIDATES:
    score, evidence = candidate_score(c)
    scored.append({**c, "score": score, "evidence": evidence})
scored.sort(key=lambda x: x["score"], reverse=True)
(RAW / "candidate_scores.json").write_text(json.dumps(scored, ensure_ascii=False, indent=2), encoding="utf-8")
print("CANDIDATES", json.dumps(scored, ensure_ascii=False))

if not scored or scored[0]["score"] < 7 or (len(scored) > 1 and scored[0]["score"] < scored[1]["score"] + 4):
    raise RuntimeError("AMBIGUOUS_NAME: web evidence does not uniquely identify a listed issuer for 华沿机器人")

chosen = scored[0]
print("DETECTED_ENTITY", chosen["entity"], chosen["code"], chosen["market"], chosen["score"])


def eastmoney_reports(code: str) -> list[dict]:
    url = "https://reportapi.eastmoney.com/report/list"
    params = {
        "code": code,
        "pageSize": "500",
        "pageNo": "1",
        "beginTime": "2018-01-01",
        "endTime": "2026-09-05",
        "qType": "0",
        "fields": "",
        "industryCode": "*",
        "industry": "*",
        "rating": "*",
        "ratingChange": "*",
        "orgCode": "",
        "rcode": "",
        "p": "1",
        "pageNum": "1",
        "pageNumber": "1",
    }
    r = client.get(url, params=params, headers={"Referer": "https://data.eastmoney.com/report/"})
    r.raise_for_status()
    obj = r.json()
    return obj.get("data") or []


def search_direct_pdfs(entity: str, code: str) -> list[dict]:
    rows = []
    qs = [
        f'"{entity}" 券商 深度报告 filetype:pdf',
        f'"{entity}" 首次覆盖 PDF',
        f'"{code}" 研报 PDF',
        f'site:pdf.dfcfw.com "{entity}"',
    ]
    for q in qs:
        for item in bing_rss(q):
            url = item.get("link", "")
            if ".pdf" in url.lower():
                rows.append({"title": item.get("title", ""), "url": url, "source": "bing"})
    return rows


def download_pdf(url: str, destination: Path) -> bool:
    headers = {"User-Agent": UA, "Referer": "https://data.eastmoney.com/"}
    for attempt in range(1, 4):
        try:
            with client.stream("GET", url, headers=headers) as r:
                if r.status_code != 200:
                    return False
                with destination.open("wb") as f:
                    for chunk in r.iter_bytes(1024 * 1024):
                        f.write(chunk)
            if destination.stat().st_size < 80_000:
                destination.unlink(missing_ok=True)
                return False
            with destination.open("rb") as f:
                if f.read(5) != b"%PDF-":
                    destination.unlink(missing_ok=True)
                    return False
            return True
        except Exception:
            destination.unlink(missing_ok=True)
            time.sleep(attempt)
    return False


def inspect_pdf(path: Path, aliases: list[str]) -> dict:
    reader = PdfReader(str(path), strict=False)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            pass
    pages = len(reader.pages)
    if pages < 4:
        raise RuntimeError("too few pages")
    indices = list(range(min(12, pages)))
    if pages > 20:
        indices += [pages // 2, pages - 1]
    parts = []
    for i in sorted(set(indices)):
        try:
            parts.append(reader.pages[i].extract_text() or "")
        except Exception:
            pass
    text = "\n".join(parts)
    ntext = norm(text)
    if not any(norm(alias) in ntext for alias in aliases):
        raise RuntimeError("issuer identity not found")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"pages": pages, "sha256": digest, "sample": text[:5000], "bytes": path.stat().st_size}


def render_cover(path: Path) -> None:
    prefix = RENDERS / path.stem
    subprocess.run(
        ["pdftoppm", "-f", "1", "-l", "1", "-png", "-singlefile", "-r", "90", str(path), str(prefix)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    png = Path(str(prefix) + ".png")
    if not png.exists() or png.stat().st_size < 8_000:
        raise RuntimeError("cover render failed")


candidates: list[dict] = []
if chosen["market"] == "A":
    for r in eastmoney_reports(chosen["code"]):
        info = r.get("infoCode") or ""
        if not info:
            continue
        candidates.append({
            "title": r.get("title") or "",
            "broker": r.get("orgSName") or r.get("orgName") or "",
            "date": (r.get("publishDate") or "")[:10],
            "researcher": r.get("researcher") or "",
            "url": f"https://pdf.dfcfw.com/pdf/H3_{info}_1.pdf",
            "info_code": info,
            "source": "Eastmoney",
        })
else:
    candidates.extend(search_direct_pdfs(chosen["entity"], chosen["code"]))

(RAW / "report_candidates.json").write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")

valid: list[dict] = []
seen_hashes: set[str] = set()
issuer_aliases = chosen["aliases"] + [chosen["entity"], chosen["code"]]
for idx, item in enumerate(candidates, start=1):
    title = item.get("title", "")
    title_n = norm(title)
    # Reject obvious industry-only reports and routine one-page notices.
    if any(k in title_n for k in ["行业周报", "行业日报", "行业月报", "策略周报", "债券"]):
        continue
    temp = RAW / f"candidate_{idx}.pdf"
    if not download_pdf(item["url"], temp):
        continue
    try:
        meta = inspect_pdf(temp, issuer_aliases)
        if meta["sha256"] in seen_hashes:
            temp.unlink(missing_ok=True)
            continue
        seen_hashes.add(meta["sha256"])
        deep_kw = any(k in title for k in ["深度", "首次覆盖", "新股", "专题", "价值", "成长", "龙头", "研究"])
        item.update(meta)
        item["path"] = str(temp)
        item["deep_keyword"] = deep_kw
        valid.append(item)
        print("VALID", item.get("date"), item.get("broker"), meta["pages"], title)
    except Exception as exc:
        print("REJECT", title, repr(exc))
        temp.unlink(missing_ok=True)

# Rank genuine deep/initial-coverage reports first, then page count and recency.
valid.sort(key=lambda x: (1 if x.get("deep_keyword") else 0, x.get("pages", 0), x.get("date", "")), reverse=True)
strict = [x for x in valid if x.get("deep_keyword") and x.get("pages", 0) >= 8]
selected = strict[:3]
if len(selected) < 2:
    selected = [x for x in valid if x.get("pages", 0) >= 8][:3]
if len(selected) < 2:
    raise RuntimeError(f"INSUFFICIENT_REPORTS: only {len(selected)} suitable reports for detected issuer {chosen['entity']}")

manifest = []
for i, item in enumerate(selected, start=1):
    safe_title = re.sub(r"[\\/:*?\"<>|]", "_", item.get("title") or "公司研究")[:80]
    safe_broker = re.sub(r"[\\/:*?\"<>|]", "_", item.get("broker") or "券商")[:30]
    filename = f"{i:02d}_{chosen['entity']}_{item.get('date','')}_{safe_broker}_{safe_title}.pdf"
    dst = REPORTS / filename
    shutil.copy2(Path(item["path"]), dst)
    render_cover(dst)
    manifest.append({
        "index": i,
        "requested_name": REQUESTED,
        "resolved_entity": chosen["entity"],
        "stock_code": chosen["code"],
        "broker": item.get("broker", ""),
        "date": item.get("date", ""),
        "title": item.get("title", ""),
        "pages": item.get("pages", 0),
        "bytes": item.get("bytes", 0),
        "sha256": item.get("sha256", ""),
        "source_url": item.get("url", ""),
        "filename": filename,
    })

readme = [
    f"用户输入名称：{REQUESTED}",
    f"检索解析主体：{chosen['entity']}（{chosen['code']}）",
    "",
    "名称解析说明：输入名称并非标准上市简称；本包仅在公开搜索结果对同音/近似名称与上市主体形成高置信度对应时生成。",
    "如主体与用户原意不符，应以用户提供的证券代码为准重新整理。",
    "",
    "报告清单：",
]
for m in manifest:
    readme.append(f"{m['index']}. {m['broker']}｜{m['date']}｜{m['pages']}页｜{m['title']}")
readme += ["", "校验：PDF签名、发行人名称/代码、页数、首页渲染、SHA-256、ZIP完整性。"]
(REPORTS / "README_名称解析与报告清单.txt").write_text("\n".join(readme), encoding="utf-8")
(REPORTS / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
with (REPORTS / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(manifest[0].keys()))
    writer.writeheader()
    writer.writerows(manifest)

with ZipFile(FINAL_ZIP, "w", ZIP_DEFLATED, compresslevel=9) as zf:
    for p in sorted(REPORTS.iterdir(), key=lambda x: x.name):
        zf.write(p, p.name)
with ZipFile(FINAL_ZIP) as zf:
    if zf.testzip() is not None:
        raise RuntimeError("ZIP integrity failure")
    if len([n for n in zf.namelist() if n.lower().endswith(".pdf")]) != len(manifest):
        raise RuntimeError("PDF count mismatch")

print("PACKAGE_READY", FINAL_ZIP, FINAL_ZIP.stat().st_size)
print(json.dumps({"resolved_entity": chosen, "manifest": manifest}, ensure_ascii=False, indent=2))
client.close()
