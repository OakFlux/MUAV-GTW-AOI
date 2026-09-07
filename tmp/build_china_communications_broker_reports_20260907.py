from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

import requests
from pypdf import PdfReader

OUT = Path("out_china_communications_reports_20260907")
RAW = OUT / "raw"
PACKAGE = OUT / "package"
RENDERS = OUT / "renders"
FINAL = OUT / "China_Communications_Construction_601800_01800_Broker_Deep_Reports.zip"

shutil.rmtree(OUT, ignore_errors=True)
for directory in (RAW, PACKAGE, RENDERS):
    directory.mkdir(parents=True, exist_ok=True)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
LIST_URL = "https://reportapi.eastmoney.com/report/list"
LIST2_URL = "https://reportapi.eastmoney.com/report/list2"
KNOWN_INFO_CODES = {
    "AP202405271634715420": {
        "title": "公司首次覆盖报告：交通基建央企龙头，海外布局广泛全产业链掘金",
        "orgSName": "开源证券",
        "publishDate": "2024-05-27",
        "researcher": "齐东,胡耀文",
        "stockCode": "601800",
        "stockName": "中国交建",
    }
}


def new_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": UA,
            "Referer": "https://data.eastmoney.com/report/stock.jshtml",
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
    )
    return session


def normalize_date(value: Any) -> str:
    text = str(value or "")
    match = re.search(r"(20\d{2})[-/]?(\d{2})[-/]?(\d{2})", text)
    if not match:
        return text[:10]
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"


def row_key(row: dict[str, Any]) -> str:
    return str(row.get("infoCode") or row.get("INFO_CODE") or "").strip()


def collect_metadata() -> list[dict[str, Any]]:
    session = new_session()
    rows: list[dict[str, Any]] = []

    common = {
        "code": "601800",
        "pageSize": "100",
        "beginTime": "2010-01-01",
        "endTime": "2026-09-07",
        "qType": "0",
        "fields": "",
        "industryCode": "*",
        "industry": "*",
        "rating": "*",
        "ratingChange": "*",
        "orgCode": "",
        "rcode": "",
    }

    # The legacy GET endpoint remains the most complete source for A-share company reports.
    total_pages = 1
    for page in range(1, 30):
        params = dict(common)
        params.update(
            {
                "pageNo": str(page),
                "p": str(page),
                "pageNum": str(page),
                "pageNumber": str(page),
            }
        )
        try:
            response = session.get(LIST_URL, params=params, timeout=60)
            response.raise_for_status()
            obj = response.json()
            data = obj.get("data") or [] if isinstance(obj, dict) else []
            if page == 1:
                try:
                    total_pages = max(1, int(obj.get("TotalPage") or obj.get("totalPage") or 1))
                except Exception:
                    total_pages = 1
            print("LIST_GET", page, len(data), "of", total_pages)
            if not isinstance(data, list) or not data:
                break
            rows.extend(item for item in data if isinstance(item, dict))
            if page >= total_pages:
                break
        except Exception as exc:
            print("LIST_GET_ERROR", page, repr(exc))
            break

    # New POST endpoint fallback/augmentation.
    body = {
        "pageSize": 5000,
        "pageNo": 1,
        "p": 1,
        "pageNum": 1,
        "pageNumber": 1,
        "beginTime": "2010-01-01",
        "endTime": "2026-09-07",
        "code": "601800",
        "industryCode": "*",
        "rating": None,
        "ratingChange": None,
        "orgCode": None,
        "rcode": "",
    }
    try:
        response = session.post(LIST2_URL, json=body, timeout=60)
        response.raise_for_status()
        obj = response.json()
        data = obj.get("data") or [] if isinstance(obj, dict) else []
        print("LIST2_POST", len(data))
        if isinstance(data, list):
            rows.extend(item for item in data if isinstance(item, dict))
    except Exception as exc:
        print("LIST2_POST_ERROR", repr(exc))

    # Guarantee the already independently verified 2024 initial-coverage report is considered.
    for info_code, metadata in KNOWN_INFO_CODES.items():
        rows.append({"infoCode": info_code, **metadata})

    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        info_code = row_key(row)
        if not info_code:
            continue
        blob = json.dumps(row, ensure_ascii=False).lower()
        # The endpoint is code-filtered, but retain a defensive identity filter.
        if not any(token in blob for token in ["601800", "中国交建", "中国交通建设"]):
            continue
        current = deduped.get(info_code)
        if current is None or len(json.dumps(row, ensure_ascii=False)) > len(json.dumps(current, ensure_ascii=False)):
            deduped[info_code] = row

    result = list(deduped.values())
    result.sort(key=lambda row: normalize_date(row.get("publishDate")), reverse=True)
    (OUT / "eastmoney_metadata.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("UNIQUE_METADATA", len(result))
    session.close()
    return result


def candidate_score(row: dict[str, Any]) -> float:
    title = str(row.get("title") or row.get("TITLE") or "")
    org = str(row.get("orgSName") or row.get("orgName") or "")
    score = 0.0
    positive = {
        "首次覆盖": 80,
        "深度": 70,
        "投资价值": 60,
        "公司研究": 35,
        "专题": 25,
        "龙头": 15,
        "全产业链": 15,
        "一带一路": 8,
        "海外": 5,
    }
    negative = {
        "点评": -35,
        "季报": -35,
        "一季报": -35,
        "三季报": -35,
        "年报": -25,
        "中报": -25,
        "业绩": -20,
        "快报": -25,
        "公告": -20,
        "周报": -80,
        "行业": -30,
    }
    for token, weight in positive.items():
        if token in title:
            score += weight
    for token, weight in negative.items():
        if token in title:
            score += weight
    if org:
        score += 2
    date = normalize_date(row.get("publishDate"))
    if date >= "2020-01-01":
        score += 10
    return score


@dataclass
class DownloadedReport:
    row: dict[str, Any]
    path: Path
    pages: int
    sha256: str
    bytes: int
    text: str
    title: str
    broker: str
    date: str
    researchers: str
    deep_score: float
    source_url: str


def inspect_pdf(path: Path, row: dict[str, Any], source_url: str) -> DownloadedReport | None:
    data = path.read_bytes()
    if not data.startswith(b"%PDF-") or len(data) < 50_000:
        return None
    try:
        reader = PdfReader(str(path), strict=False)
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                pass
        pages = len(reader.pages)
        if pages < 2:
            return None
        indices = list(range(min(12, pages)))
        if pages > 15:
            indices.extend([pages // 2, pages - 2, pages - 1])
        text_parts: list[str] = []
        for index in sorted(set(i for i in indices if 0 <= i < pages)):
            try:
                text_parts.append(reader.pages[index].extract_text() or "")
            except Exception:
                pass
        text = "\n".join(text_parts)
    except Exception as exc:
        print("PDF_PARSE_ERROR", path.name, repr(exc))
        return None

    normalized = re.sub(r"\s+", "", text).lower()
    if not any(
        token in normalized
        for token in ["中国交建", "中国交通建设", "601800", "chinacommunicationsconstruction", "1800.hk", "01800"]
    ):
        return None

    title = str(row.get("title") or row.get("TITLE") or "").strip()
    broker = str(row.get("orgSName") or row.get("orgName") or row.get("ORG_SNAME") or "未知券商").strip()
    date = normalize_date(row.get("publishDate") or row.get("PUBLISH_DATE"))
    researchers = str(row.get("researcher") or row.get("researcherName") or "").strip()
    digest = hashlib.sha256(data).hexdigest()
    score = candidate_score(row)
    score += min(pages, 80) * 2.5
    if pages >= 20:
        score += 80
    elif pages >= 12:
        score += 35
    elif pages < 6:
        score -= 60
    if "首次覆盖" in title or "深度" in title:
        score += 50

    return DownloadedReport(
        row=row,
        path=path,
        pages=pages,
        sha256=digest,
        bytes=len(data),
        text=text,
        title=title,
        broker=broker,
        date=date,
        researchers=researchers,
        deep_score=score,
        source_url=source_url,
    )


def download_one(row: dict[str, Any], index: int) -> DownloadedReport | None:
    info_code = row_key(row)
    if not info_code:
        return None
    session = new_session()
    urls = [
        f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf",
        f"https://pdf.dfcfw.com/pdf/H3_{info_code}.pdf",
    ]
    try:
        for suffix_index, url in enumerate(urls, 1):
            destination = RAW / f"{index:03d}_{info_code}_{suffix_index}.pdf"
            for attempt in range(1, 4):
                try:
                    response = session.get(
                        url,
                        timeout=90,
                        headers={
                            "User-Agent": UA,
                            "Referer": "https://data.eastmoney.com/",
                            "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.5",
                        },
                    )
                    if response.status_code != 200:
                        break
                    if not response.content.startswith(b"%PDF-") or len(response.content) < 50_000:
                        break
                    destination.write_bytes(response.content)
                    report = inspect_pdf(destination, row, url)
                    if report is not None:
                        return report
                    destination.unlink(missing_ok=True)
                    break
                except Exception as exc:
                    if attempt == 3:
                        print("DOWNLOAD_ERROR", info_code, repr(exc))
                    time.sleep(attempt)
        return None
    finally:
        session.close()


def render_check(report: DownloadedReport, destination: Path) -> None:
    for page_number in sorted({1, max(1, (report.pages + 1) // 2), report.pages}):
        prefix = RENDERS / f"{destination.stem}_p{page_number}"
        subprocess.run(
            [
                "pdftoppm",
                "-f",
                str(page_number),
                "-l",
                str(page_number),
                "-png",
                "-singlefile",
                "-r",
                "90",
                str(destination),
                str(prefix),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        image = Path(str(prefix) + ".png")
        if not image.exists() or image.stat().st_size < 8_000:
            raise RuntimeError(f"Render validation failed: {destination.name} page {page_number}")


def safe_component(value: str, fallback: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|\r\n]+", "_", value).strip(" ._")
    return value[:45] or fallback


def main() -> None:
    rows = collect_metadata()
    if not rows:
        raise RuntimeError("Eastmoney returned no China Communications Construction report metadata")

    # Download all likely company reports plus a limited number of lower-scored rows,
    # then rank by verified page count and report type.
    ranked_rows = sorted(rows, key=candidate_score, reverse=True)
    likely = [row for row in ranked_rows if candidate_score(row) >= 0]
    download_rows = likely[:90]
    # Ensure the known initial-coverage item is included even if metadata sorting changes.
    known_codes = set(KNOWN_INFO_CODES)
    for row in rows:
        if row_key(row) in known_codes and row not in download_rows:
            download_rows.append(row)

    reports: list[DownloadedReport] = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(download_one, row, index): row
            for index, row in enumerate(download_rows, 1)
        }
        for future in as_completed(futures):
            try:
                report = future.result()
                if report is not None:
                    reports.append(report)
                    print(
                        "VALID_REPORT",
                        report.date,
                        report.broker,
                        report.pages,
                        report.title,
                    )
            except Exception as exc:
                print("FUTURE_ERROR", repr(exc))

    # De-duplicate identical PDFs and persist the full validated inventory.
    unique: dict[str, DownloadedReport] = {}
    for report in reports:
        current = unique.get(report.sha256)
        if current is None or report.deep_score > current.deep_score:
            unique[report.sha256] = report
    reports = list(unique.values())
    inventory = [
        {
            "date": item.date,
            "broker": item.broker,
            "title": item.title,
            "pages": item.pages,
            "bytes": item.bytes,
            "sha256": item.sha256,
            "score": item.deep_score,
            "source_url": item.source_url,
            "infoCode": row_key(item.row),
        }
        for item in sorted(reports, key=lambda item: item.deep_score, reverse=True)
    ]
    (OUT / "validated_inventory.json").write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    strict = [
        item
        for item in reports
        if item.pages >= 15
        or "首次覆盖" in item.title
        or "深度" in item.title
        or "投资价值" in item.title
    ]
    strict.sort(key=lambda item: (item.deep_score, item.pages, item.date), reverse=True)

    selected: list[DownloadedReport] = []
    used_brokers: set[str] = set()
    used_dates_titles: set[tuple[str, str]] = set()

    # First pass: diverse brokers among strict deep candidates.
    for item in strict:
        key = (item.date, item.title)
        if key in used_dates_titles:
            continue
        if item.broker in used_brokers and len(strict) > 2:
            continue
        selected.append(item)
        used_brokers.add(item.broker)
        used_dates_titles.add(key)
        if len(selected) == 3:
            break

    # Second pass: fill to at least two with the longest complete company reports.
    if len(selected) < 2:
        fallback = sorted(
            [item for item in reports if item.pages >= 6],
            key=lambda item: (item.pages, item.deep_score, item.date),
            reverse=True,
        )
        for item in fallback:
            key = (item.date, item.title)
            if item.sha256 in {x.sha256 for x in selected} or key in used_dates_titles:
                continue
            selected.append(item)
            used_dates_titles.add(key)
            if len(selected) == 3 or len(selected) >= 2:
                break

    if len(selected) < 2:
        raise RuntimeError(
            f"Only {len(selected)} complete distinct company reports could be verified; see inventory"
        )

    # Prefer 3 when three genuine distinct reports exist, otherwise deliver 2.
    selected = selected[:3]
    manifest: list[dict[str, Any]] = []
    for index, report in enumerate(selected, 1):
        broker = safe_component(report.broker, "Broker")
        date = report.date or "UnknownDate"
        filename = f"{index:02d}_{broker}_{date}_中国交建_{report.pages}页.pdf"
        destination = PACKAGE / filename
        shutil.copy2(report.path, destination)
        render_check(report, destination)
        strict_deep = report.pages >= 15 or "首次覆盖" in report.title or "深度" in report.title
        manifest.append(
            {
                "序号": index,
                "券商": report.broker,
                "发布日期": report.date,
                "报告标题": report.title,
                "报告性质": "深度/首次覆盖" if strict_deep else "完整公司研究",
                "分析师": report.researchers,
                "实际页数": report.pages,
                "文件名": filename,
                "文件大小_字节": destination.stat().st_size,
                "SHA256": report.sha256,
                "东方财富信息代码": row_key(report.row),
                "原始PDF地址": report.source_url,
            }
        )

    readme = [
        "中国交通建设／中国交建（601800.SH／01800.HK）券商研究报告合集",
        "",
        f"本包收录{len(manifest)}份公开可直接取得、经完整性核验的实际券商PDF。",
        "不含网页跳转文件、目录页、预览图片或公司公告。",
        "",
        "文件清单：",
    ]
    for row in manifest:
        readme.append(
            f"{row['序号']}. {row['券商']}｜{row['发布日期']}｜{row['实际页数']}页｜"
            f"{row['报告性质']}｜{row['报告标题']}"
        )
    readme.extend(
        [
            "",
            "校验项目：PDF文件签名、公司名称/证券代码、实际页数、文件去重、",
            "首中末页渲染、SHA-256及最终ZIP完整性。",
            "文件仅供个人研究使用，版权归原券商及发布机构所有。",
        ]
    )
    (PACKAGE / "README_文件说明.txt").write_text("\n".join(readme), encoding="utf-8")
    (PACKAGE / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (PACKAGE / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(manifest[0].keys()))
        writer.writeheader()
        writer.writerows(manifest)

    FINAL.unlink(missing_ok=True)
    with ZipFile(FINAL, "w", ZIP_DEFLATED, compresslevel=9) as archive:
        for member in sorted(PACKAGE.iterdir(), key=lambda path: path.name):
            archive.write(member, arcname=member.name)
    with ZipFile(FINAL) as archive:
        damaged = archive.testzip()
        if damaged is not None:
            raise RuntimeError(f"ZIP integrity failure: {damaged}")
        pdf_names = [name for name in archive.namelist() if name.lower().endswith(".pdf")]
        if len(pdf_names) != len(manifest):
            raise RuntimeError("ZIP PDF count mismatch")

    print("PACKAGE_READY", FINAL, FINAL.stat().st_size)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
