from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import requests
from pypdf import PdfReader

OUT = Path("out_china_tower_targeted_20260905")
RAW = OUT / "raw"
REPORTS = OUT / "reports"
RENDERS = OUT / "renders"
FINAL = OUT / "China_Tower_00788_Broker_Research_Reports.zip"
shutil.rmtree(OUT, ignore_errors=True)
RAW.mkdir(parents=True, exist_ok=True)
REPORTS.mkdir(parents=True, exist_ok=True)
RENDERS.mkdir(parents=True, exist_ok=True)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36"
LIST = "https://reportapi.eastmoney.com/report/list"
S = requests.Session()
S.headers.update({"User-Agent": UA, "Referer": "https://data.eastmoney.com/report/stock.jshtml"})

# Windows centred on independently confirmed publication dates.
WINDOWS = [
    ("2025-11-01", "2025-11-30"),  # China Galaxy initial coverage / deep report
    ("2024-10-15", "2024-10-31"),  # Debon Securities company research
    ("2023-12-01", "2023-12-15"),  # CICC reverse-roadshow report
    ("2024-03-15", "2024-03-22"),  # CICC FY23 results research
    ("2025-03-15", "2025-03-22"),  # CMBI/CICC FY24 results research
    ("2026-03-16", "2026-03-31"),  # recent annual-results research
]
TOKENS = ["中国铁塔", "中國鐵塔", "china tower", "00788", "0788.hk", "0788hk"]
EXCLUDES = ["东方铁塔", "中国铁建", "中國鐵建", "中国中铁", "中國中鐵"]


def matches(row: dict) -> bool:
    blob = json.dumps(row, ensure_ascii=False).lower()
    if any(x.lower() in blob for x in EXCLUDES):
        return False
    return any(x.lower() in blob for x in TOKENS)


def fetch_window(begin: str, end: str) -> list[dict]:
    base = {
        "industryCode": "*", "pageSize": "100", "industry": "*", "rating": "*",
        "ratingChange": "*", "beginTime": begin, "endTime": end, "fields": "",
        "qType": "0", "orgCode": "", "code": "", "rcode": "",
    }
    rows = []
    first = None
    for attempt in range(1, 4):
        try:
            p = dict(base, pageNo="1", p="1", pageNum="1", pageNumber="1")
            r = S.get(LIST, params=p, timeout=60)
            r.raise_for_status()
            first = r.json()
            break
        except Exception as exc:
            print("FIRST_RETRY", begin, attempt, repr(exc))
            time.sleep(attempt)
    if not isinstance(first, dict):
        return rows
    total = int(first.get("TotalPage") or 0)
    print("WINDOW", begin, end, "pages", total, "hits", first.get("hits"))
    for page in range(1, total + 1):
        obj = first if page == 1 else None
        if obj is None:
            for attempt in range(1, 4):
                try:
                    p = dict(base, pageNo=str(page), p=str(page), pageNum=str(page), pageNumber=str(page))
                    r = S.get(LIST, params=p, timeout=60)
                    r.raise_for_status()
                    obj = r.json()
                    break
                except Exception as exc:
                    print("PAGE_RETRY", begin, page, attempt, repr(exc))
                    time.sleep(attempt)
        for row in (obj or {}).get("data") or []:
            if isinstance(row, dict) and matches(row):
                print("MATCH", json.dumps(row, ensure_ascii=False))
                rows.append(row)
        time.sleep(0.05)
    return rows


def download(info: str, path: Path) -> str | None:
    for url in [f"https://pdf.dfcfw.com/pdf/H3_{info}_1.pdf", f"https://pdf.dfcfw.com/pdf/H3_{info}.pdf"]:
        try:
            r = S.get(url, timeout=120, headers={"Accept": "application/pdf,*/*", "User-Agent": UA})
            print("PDF", r.status_code, r.headers.get("content-type"), len(r.content), url)
            if r.status_code == 200 and r.content.startswith(b"%PDF-") and len(r.content) > 50000:
                path.write_bytes(r.content)
                return url
        except Exception as exc:
            print("PDF_ERROR", url, repr(exc))
    return None


def inspect(path: Path) -> dict:
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    sample = []
    indexes = list(range(min(15, pages)))
    if pages > 20:
        indexes.extend([pages // 2, pages - 1])
    for i in sorted(set(indexes)):
        try:
            sample.append(reader.pages[i].extract_text() or "")
        except Exception:
            pass
    text = "\n".join(sample)
    norm = re.sub(r"\s+", "", text).lower()
    identity = any(t.lower().replace(" ", "") in norm for t in TOKENS)
    return {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "identity": identity,
        "sample": text[:4000],
    }


def render(path: Path) -> int:
    prefix = RENDERS / path.stem
    subprocess.run(
        ["pdftoppm", "-f", "1", "-l", "1", "-png", "-singlefile", "-r", "100", str(path), str(prefix)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    image = Path(str(prefix) + ".png")
    if not image.exists() or image.stat().st_size < 8000:
        raise RuntimeError("render failed")
    return image.stat().st_size


rows = []
for begin, end in WINDOWS:
    rows.extend(fetch_window(begin, end))

unique = {}
for row in rows:
    info = str(row.get("infoCode") or "").strip()
    if info:
        unique[info] = row
print("UNIQUE", len(unique))
(OUT / "matching_metadata.json").write_text(json.dumps(list(unique.values()), ensure_ascii=False, indent=2), encoding="utf-8")

valid = []
for idx, (info, row) in enumerate(unique.items(), 1):
    path = RAW / f"{idx:03d}_{info}.pdf"
    url = download(info, path)
    if not url:
        continue
    try:
        meta = inspect(path)
        if meta["pages"] < 3 or not meta["identity"]:
            print("REJECT", info, meta["pages"], meta["identity"])
            path.unlink(missing_ok=True)
            continue
        render_bytes = render(path)
        title = str(row.get("title") or "").strip()
        broker = str(row.get("orgSName") or row.get("orgName") or "").strip()
        pubdate = str(row.get("publishDate") or "")[:10]
        score = meta["pages"]
        if "深度" in title or "首次覆盖" in title or "首次覆蓋" in title:
            score += 200
        elif "公司研究" in title or "覆盖" in title:
            score += 100
        if broker in {"中国银河", "中国银河证券"}:
            score += 50
        valid.append({
            "infoCode": info, "title": title, "broker": broker, "date": pubdate,
            "pages": meta["pages"], "bytes": meta["bytes"], "sha256": meta["sha256"],
            "source_url": url, "score": score, "raw_path": str(path), "render_bytes": render_bytes,
        })
        print("VALID", json.dumps(valid[-1], ensure_ascii=False))
    except Exception as exc:
        print("INSPECT_ERROR", info, repr(exc))
        path.unlink(missing_ok=True)

if len(valid) < 2:
    raise RuntimeError(f"Only {len(valid)} valid China Tower reports found")

# Prefer deep/initial-coverage and then longer reports, avoiding duplicate titles.
valid.sort(key=lambda x: (x["score"], x["pages"], x["date"]), reverse=True)
selected = []
seen = set()
for item in valid:
    key = re.sub(r"\W+", "", item["title"].lower())
    if key in seen:
        continue
    # The package should not be filled with one-page or two-page flashes.
    if item["pages"] >= 5:
        selected.append(item)
        seen.add(key)
    if len(selected) == 3:
        break
if len(selected) < 2:
    for item in valid:
        key = re.sub(r"\W+", "", item["title"].lower())
        if key not in seen:
            selected.append(item)
            seen.add(key)
        if len(selected) == min(3, len(valid)):
            break
if len(selected) < 2:
    raise RuntimeError("Fewer than two suitable reports after selection")

manifest = []
for i, item in enumerate(selected, 1):
    broker = re.sub(r'[\\/:*?"<>|]', '_', item["broker"] or "券商")
    title = re.sub(r'[\\/:*?"<>|]', '_', item["title"])[:85]
    filename = f"{i:02d}_{broker}_{item['date']}_{title}.pdf"
    shutil.copy2(Path(item["raw_path"]), REPORTS / filename)
    manifest.append({
        "index": i, "broker": item["broker"], "date": item["date"], "title": item["title"],
        "pages": item["pages"], "filename": filename, "bytes": item["bytes"],
        "sha256": item["sha256"], "source_url": item["source_url"], "infoCode": item["infoCode"],
    })

lines = [
    "中国铁塔（00788.HK）券商深度/公司研究报告合集", "",
    "优先收录首次覆盖、公司深度和页数较完整的公司研究报告；排除财报、公告、行业周报及东方铁塔等同名结果。", "",
]
for item in manifest:
    lines.append(f"{item['index']}. {item['broker']}｜{item['date']}｜{item['pages']}页｜{item['title']}")
lines += ["", "已校验PDF签名、公司身份、实际页数、首页渲染、SHA-256及ZIP完整性。"]
(REPORTS / "README_报告说明.txt").write_text("\n".join(lines), encoding="utf-8")
(REPORTS / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
with (REPORTS / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(manifest[0].keys()))
    writer.writeheader(); writer.writerows(manifest)

with ZipFile(FINAL, "w", ZIP_DEFLATED, compresslevel=9) as zf:
    for path in sorted(REPORTS.iterdir(), key=lambda p: p.name):
        zf.write(path, path.name)
with ZipFile(FINAL) as zf:
    if zf.testzip() is not None:
        raise RuntimeError("ZIP integrity failed")
    if len([n for n in zf.namelist() if n.lower().endswith(".pdf")]) != len(manifest):
        raise RuntimeError("PDF count mismatch")

print("PACKAGE_READY", FINAL, FINAL.stat().st_size)
print(json.dumps(manifest, ensure_ascii=False, indent=2))
