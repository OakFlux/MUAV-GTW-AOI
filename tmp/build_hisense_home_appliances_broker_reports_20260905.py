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

OUT = Path("out_hisense_home_appliances_broker_reports_20260905")
RAW = OUT / "raw"
REPORTS = OUT / "reports"
RENDERS = OUT / "renders"
FINAL_ZIP = OUT / "Hisense_Home_Appliances_000921_Broker_Deep_Research_Reports.zip"

shutil.rmtree(OUT, ignore_errors=True)
RAW.mkdir(parents=True, exist_ok=True)
REPORTS.mkdir(parents=True, exist_ok=True)
RENDERS.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
        "Referer": "https://data.eastmoney.com/report/stock.jshtml",
        "Accept": "application/json,text/plain,*/*",
    }
)

LIST_URL = "https://reportapi.eastmoney.com/report/list"
PARAMS = {
    "industryCode": "*",
    "pageSize": "5000",
    "industry": "*",
    "rating": "*",
    "ratingChange": "*",
    "beginTime": "2020-01-01",
    "endTime": "2026-09-05",
    "pageNo": "1",
    "fields": "",
    "qType": "0",
    "orgCode": "",
    "code": "000921",
    "rcode": "",
    "p": "1",
    "pageNum": "1",
    "pageNumber": "1",
}


def request_json() -> dict:
    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            response = SESSION.get(LIST_URL, params=PARAMS, timeout=90)
            response.raise_for_status()
            obj = response.json()
            if not isinstance(obj, dict):
                raise RuntimeError("Eastmoney returned a non-object JSON payload")
            return obj
        except Exception as exc:
            last_error = exc
            print("LIST_RETRY", attempt, repr(exc))
            time.sleep(attempt * 2)
    raise RuntimeError(f"Unable to query Eastmoney report list: {last_error}")


def pages_of(row: dict) -> int:
    try:
        return int(float(row.get("attachPages") or 0))
    except Exception:
        return 0


def date_of(row: dict) -> str:
    value = str(row.get("publishDate") or "")
    return value[:10]


def score(row: dict) -> float:
    title = str(row.get("title") or "")
    pages = pages_of(row)
    date = date_of(row)
    year = int(date[:4]) if re.match(r"20\d{2}", date) else 0
    result = pages * 2.0

    deep_terms = {
        "深度": 42,
        "首次覆盖": 38,
        "首次覆盖报告": 40,
        "公司深度": 45,
        "价值重估": 25,
        "成长逻辑": 22,
        "全球化": 12,
        "全景": 20,
        "专题": 18,
        "龙头": 10,
        "再出发": 14,
        "新征程": 14,
        "系列报告": 14,
    }
    for term, bonus in deep_terms.items():
        if term in title:
            result += bonus

    short_update_terms = [
        "点评", "季报", "年报", "中报", "业绩快报", "业绩预告", "事件点评",
        "跟踪报告", "信息更新", "简评", "三季报", "一季报",
    ]
    if any(term in title for term in short_update_terms):
        result -= 30
    if pages < 8:
        result -= 50
    if pages >= 15:
        result += 20
    if pages >= 25:
        result += 30
    if year >= 2023:
        result += 15
    elif year >= 2021:
        result += 7
    return result


def download_pdf(info_code: str, destination: Path) -> str:
    urls = [
        f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf",
        f"https://pdf.dfcfw.com/pdf/H3_{info_code}.pdf",
    ]
    last_error: Exception | None = None
    for url in urls:
        for attempt in range(1, 4):
            try:
                response = SESSION.get(
                    url,
                    timeout=120,
                    headers={
                        "User-Agent": SESSION.headers["User-Agent"],
                        "Referer": "https://data.eastmoney.com/report/stock.jshtml",
                        "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.5",
                    },
                )
                print(
                    "PDF_PROBE",
                    response.status_code,
                    response.headers.get("content-type"),
                    len(response.content),
                    url,
                )
                if response.status_code != 200:
                    raise RuntimeError(f"HTTP {response.status_code}")
                if len(response.content) < 80_000 or not response.content.startswith(b"%PDF-"):
                    raise RuntimeError("Response is not a usable PDF")
                destination.write_bytes(response.content)
                return url
            except Exception as exc:
                last_error = exc
                destination.unlink(missing_ok=True)
                print("PDF_RETRY", attempt, info_code, repr(exc))
                time.sleep(attempt * 2)
    raise RuntimeError(f"Unable to download {info_code}: {last_error}")


def inspect_pdf(path: Path, expected_pages: int) -> dict:
    reader = PdfReader(str(path), strict=False)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:
            raise RuntimeError(f"Encrypted PDF cannot be read: {path.name}: {exc}")

    actual_pages = len(reader.pages)
    if actual_pages < 6:
        raise RuntimeError(f"Report has too few pages: {path.name}: {actual_pages}")
    if expected_pages and abs(actual_pages - expected_pages) > 2:
        print("PAGE_COUNT_WARNING", path.name, expected_pages, actual_pages)

    sample_indices = list(range(min(12, actual_pages)))
    if actual_pages > 15:
        sample_indices.extend([actual_pages // 2, actual_pages - 1])
    parts: list[str] = []
    for index in sorted(set(sample_indices)):
        try:
            parts.append(reader.pages[index].extract_text() or "")
        except Exception:
            pass
    sample = "\n".join(parts)
    normalized = re.sub(r"\s+", "", sample).lower()
    identity_tokens = ["海信家电", "海信家電", "hisensehomeappliances", "000921", "00921"]
    if not any(token.lower() in normalized for token in identity_tokens):
        raise RuntimeError(f"Hisense Home Appliances identity was not verified in {path.name}")

    full_text_path = OUT / f"{path.stem}.txt"
    subprocess.run(
        ["pdftotext", "-layout", str(path), str(full_text_path)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    full_text = full_text_path.read_text(encoding="utf-8", errors="ignore")
    if len(full_text.strip()) < 3_000:
        raise RuntimeError(f"Extracted report text is unexpectedly short: {path.name}")

    render_prefix = RENDERS / path.stem
    subprocess.run(
        [
            "pdftoppm",
            "-f",
            "1",
            "-l",
            "1",
            "-png",
            "-singlefile",
            "-r",
            "100",
            str(path),
            str(render_prefix),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    render_path = Path(str(render_prefix) + ".png")
    if not render_path.exists() or render_path.stat().st_size < 10_000:
        raise RuntimeError(f"First-page rendering failed: {path.name}")

    return {
        "actual_pages": actual_pages,
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "searchable_text_chars": len(full_text),
        "first_page_render_bytes": render_path.stat().st_size,
    }


payload = request_json()
rows = payload.get("data") or []
if not isinstance(rows, list):
    raise RuntimeError("Eastmoney response does not contain a data list")

exact_rows: list[dict] = []
for row in rows:
    if not isinstance(row, dict):
        continue
    stock_code = str(row.get("stockCode") or "").zfill(6)
    stock_name = str(row.get("stockName") or "")
    if stock_code != "000921" or "海信家电" not in stock_name:
        continue
    if not row.get("infoCode"):
        continue
    exact_rows.append(row)

if not exact_rows:
    raise RuntimeError("No exact 海信家电(000921) report rows were returned")

ranked = sorted(exact_rows, key=lambda row: (score(row), date_of(row)), reverse=True)
print("EXACT_ROWS", len(exact_rows))
for row in sorted(exact_rows, key=lambda item: (pages_of(item), date_of(item)), reverse=True)[:50]:
    print(
        "CANDIDATE",
        date_of(row),
        row.get("orgSName"),
        pages_of(row),
        round(score(row), 1),
        row.get("title"),
        row.get("infoCode"),
    )

# Build a diverse candidate queue: depth-keyword reports first, then the longest reports.
deep_pattern = re.compile(r"深度|首次覆盖|价值重估|全景|专题|成长逻辑|再出发|新征程|系列报告")
primary = [row for row in ranked if deep_pattern.search(str(row.get("title") or "")) and pages_of(row) >= 8]
secondary = [row for row in ranked if pages_of(row) >= 12]
tertiary = [row for row in ranked if pages_of(row) >= 8]
queue: list[dict] = []
seen_info: set[str] = set()
for collection in (primary, secondary, tertiary):
    for row in collection:
        info = str(row.get("infoCode"))
        if info not in seen_info:
            seen_info.add(info)
            queue.append(row)

valid: list[dict] = []
seen_hashes: set[str] = set()
used_brokers: set[str] = set()

# First pass prefers different brokers.
for diversity_pass in (True, False):
    for row in queue:
        if len(valid) >= 3:
            break
        broker = str(row.get("orgSName") or row.get("orgName") or "未知券商")
        info_code = str(row.get("infoCode"))
        if info_code in {item["infoCode"] for item in valid}:
            continue
        if diversity_pass and broker in used_brokers:
            continue

        raw_path = RAW / f"{info_code}.pdf"
        try:
            source_url = download_pdf(info_code, raw_path)
            meta = inspect_pdf(raw_path, pages_of(row))
            if meta["sha256"] in seen_hashes:
                raw_path.unlink(missing_ok=True)
                continue
            seen_hashes.add(meta["sha256"])
            item = {
                "infoCode": info_code,
                "title": str(row.get("title") or "").strip(),
                "broker": broker,
                "date": date_of(row),
                "rating": str(row.get("emRatingName") or row.get("sRatingName") or ""),
                "reported_pages": pages_of(row),
                "score": score(row),
                "source_url": source_url,
                "source_page": f"https://data.eastmoney.com/report/info/{info_code}.html",
                "raw_path": str(raw_path),
                **meta,
            }
            valid.append(item)
            used_brokers.add(broker)
            print("VALID", json.dumps({k: v for k, v in item.items() if k != "raw_path"}, ensure_ascii=False))
        except Exception as exc:
            print("REJECT", info_code, broker, row.get("title"), repr(exc))
            raw_path.unlink(missing_ok=True)
    if len(valid) >= 3:
        break

if len(valid) < 2:
    raise RuntimeError(f"Only {len(valid)} valid reports were obtained")

# Order by report date, newest first, but retain deep-report selection.
valid = sorted(valid[:3], key=lambda item: item["date"], reverse=True)
manifest: list[dict] = []


def safe_filename(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]", "_", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:90]


for index, item in enumerate(valid, start=1):
    filename = f"{index:02d}_{safe_filename(item['broker'])}_{item['date']}_{safe_filename(item['title'])}.pdf"
    destination = REPORTS / filename
    shutil.copy2(Path(item["raw_path"]), destination)
    manifest.append(
        {
            "序号": index,
            "券商": item["broker"],
            "发布日期": item["date"],
            "报告标题": item["title"],
            "评级": item["rating"],
            "实际页数": item["actual_pages"],
            "文件名": filename,
            "文件大小_字节": item["bytes"],
            "SHA256": item["sha256"],
            "来源页面": item["source_page"],
            "原始PDF": item["source_url"],
            "信息代码": item["infoCode"],
        }
    )

readme_lines = [
    "海信家电（000921.SZ／00921.HK）券商深度研究报告合集",
    "",
    f"本压缩包收录 {len(manifest)} 份完整券商PDF，优先选择页数较长、首次覆盖或公司深度类报告。",
    "全部文件均为实际PDF，不含网页跳转文件或仅有封面的预览文件。",
    "",
    "报告清单：",
]
for item in manifest:
    readme_lines.append(
        f"{item['序号']}. {item['券商']}｜{item['发布日期']}｜{item['实际页数']}页｜{item['报告标题']}"
    )
readme_lines.extend(
    [
        "",
        "校验项目：PDF文件签名、海信家电公司名称/证券代码、实际页数、全文可提取性、首页渲染、SHA-256及ZIP完整性。",
        "资料仅供个人研究使用，版权归原发布机构所有。",
    ]
)
(REPORTS / "README_报告说明.txt").write_text("\n".join(readme_lines), encoding="utf-8")
(REPORTS / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
with (REPORTS / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(manifest[0].keys()))
    writer.writeheader()
    writer.writerows(manifest)

with ZipFile(FINAL_ZIP, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
    for path in sorted(REPORTS.iterdir(), key=lambda member: member.name):
        archive.write(path, arcname=path.name)

with ZipFile(FINAL_ZIP) as archive:
    bad = archive.testzip()
    if bad is not None:
        raise RuntimeError(f"ZIP integrity failure: {bad}")
    pdf_names = [name for name in archive.namelist() if name.lower().endswith(".pdf")]
    if len(pdf_names) != len(manifest):
        raise RuntimeError(f"ZIP PDF count mismatch: {len(pdf_names)} != {len(manifest)}")

print("PACKAGE_READY", FINAL_ZIP, FINAL_ZIP.stat().st_size)
print(json.dumps(manifest, ensure_ascii=False, indent=2))
