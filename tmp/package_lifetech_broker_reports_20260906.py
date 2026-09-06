from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from pypdf import PdfReader

OUT = Path("out_lifetech_broker_reports_20260906")
RAW = OUT / "raw_pdfs"
PACKAGE = OUT / "package"
RENDERS = OUT / "renders"
FINAL = OUT / "LifeTech_Scientific_01302_Broker_Research_Reports.zip"

shutil.rmtree(PACKAGE, ignore_errors=True)
shutil.rmtree(RENDERS, ignore_errors=True)
PACKAGE.mkdir(parents=True, exist_ok=True)
RENDERS.mkdir(parents=True, exist_ok=True)

page_records = json.loads((OUT / "page_records.json").read_text(encoding="utf-8"))
pdf_records = json.loads((OUT / "pdf_records.json").read_text(encoding="utf-8"))
pages_by_source = {item.get("sourcePage", ""): item for item in page_records}

KNOWN = {
    "3536997837541737746": {
        "broker": "国金证券",
        "date": "2024-12-31",
        "title": "心血管器械布局丰富，创新引领增长",
        "report_type": "首次覆盖 / 公司深度",
        "base_score": 300,
    },
    "3630222104332339085": {
        "broker": "西南证券",
        "date": "2025-04-30",
        "title": "心血管及外周血管微创介入器械领先者，24年海外收入高增",
        "report_type": "公司研究 / 年报点评",
        "base_score": 140,
    },
    "3872055960256120040": {
        "broker": "西南证券",
        "date": "2026-04-09",
        "title": "2025年年报点评：外周血管介入业务增长稳健，持续拓展海外业务",
        "report_type": "公司研究 / 年报点评",
        "base_score": 110,
    },
}


def normalized(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def parse_pdf(path: Path) -> dict:
    with path.open("rb") as handle:
        if handle.read(5) != b"%PDF-":
            raise RuntimeError(f"Not a PDF: {path.name}")
    reader = PdfReader(str(path), strict=False)
    if reader.is_encrypted:
        reader.decrypt("")
    page_count = len(reader.pages)
    if page_count < 3:
        raise RuntimeError(f"Too few pages: {path.name}: {page_count}")
    indexes = list(range(min(page_count, 12)))
    if page_count > 16:
        indexes.extend([page_count // 2, page_count - 2, page_count - 1])
    samples = []
    for index in sorted(set(i for i in indexes if 0 <= i < page_count)):
        try:
            samples.append(reader.pages[index].extract_text() or "")
        except Exception:
            pass
    sample = "\n".join(samples)
    norm = normalized(sample)
    identity = any(token in norm for token in [
        "先健科技", "先健科技公司", "lifetechscientific", "01302", "1302.hk", "1302hk"
    ])
    if not identity:
        raise RuntimeError(f"LifeTech identity not verified: {path.name}")
    return {
        "pages": page_count,
        "sample": sample,
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def infer_metadata(record: dict, sample: str) -> dict:
    page_id = str(record.get("pageId") or "")
    if page_id in KNOWN:
        return dict(KNOWN[page_id])
    source_meta = pages_by_source.get(record.get("sourcePage", ""), {})
    blob = "\n".join([
        str(record.get("brokerHint", "")),
        str(record.get("dateHint", "")),
        str(record.get("titleHint", "")),
        str(source_meta.get("pageTitle", "")),
        json.dumps(source_meta.get("meta", {}), ensure_ascii=False),
        source_meta.get("bodyPreview", ""),
        sample[:5000],
    ])
    broker = "券商研究"
    for candidate in [
        "华安证券", "国金证券", "西南证券", "东北证券", "广发证券", "安信国际",
        "中泰国际", "交银国际", "国元国际", "中银证券", "申万宏源",
    ]:
        if candidate in blob:
            broker = candidate
            break
    date_match = re.search(r"(20\d{2})[-年/.](\d{1,2})[-月/.](\d{1,2})", blob)
    date = ""
    if date_match:
        y, m, d = map(int, date_match.groups())
        date = f"{y:04d}-{m:02d}-{d:02d}"
    title = str(record.get("titleHint") or source_meta.get("pageTitle") or "先健科技公司研究")
    title = re.sub(r"\s+-\s+行业研究报告.*$", "", title)
    title = re.sub(r"^.*?先健科技[:：-]?", "", title).strip() or "先健科技公司研究"
    report_type = "公司研究"
    if "首次覆盖" in blob or "深度" in blob:
        report_type = "首次覆盖 / 公司深度"
    base_score = int(record.get("priority") or 0)
    return {
        "broker": broker,
        "date": date,
        "title": title,
        "report_type": report_type,
        "base_score": base_score,
    }


def render_check(path: Path, pages: int) -> list[str]:
    targets = sorted(set([1, max(1, (pages + 1) // 2), pages]))
    images = []
    for page_number in targets:
        prefix = RENDERS / f"{path.stem}_p{page_number}"
        subprocess.run([
            "pdftoppm", "-f", str(page_number), "-l", str(page_number),
            "-png", "-singlefile", "-r", "80", str(path), str(prefix)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        png = Path(str(prefix) + ".png")
        if not png.exists() or png.stat().st_size < 6000:
            raise RuntimeError(f"Render check failed: {path.name}, page {page_number}")
        images.append(png.name)
    return images


valid = []
seen = set()
for record in pdf_records:
    path = Path(record["filePath"])
    if not path.exists():
        continue
    try:
        parsed = parse_pdf(path)
    except Exception as exc:
        print("REJECT", path, repr(exc))
        continue
    if parsed["sha256"] in seen:
        continue
    seen.add(parsed["sha256"])
    meta = infer_metadata(record, parsed["sample"])
    score = int(meta["base_score"]) + parsed["pages"] * 3
    if parsed["pages"] >= 20:
        score += 180
    if "深度" in meta["report_type"] or "首次覆盖" in meta["report_type"]:
        score += 150
    item = {
        **record,
        **meta,
        **{k: v for k, v in parsed.items() if k != "sample"},
        "score": score,
        "sample_text": parsed["sample"][:6000],
    }
    item["rendered_pages"] = render_check(path, parsed["pages"])
    valid.append(item)
    print("VALID", json.dumps({k: v for k, v in item.items() if k not in {"sample_text"}}, ensure_ascii=False))

if len(valid) < 2:
    raise RuntimeError(f"Only {len(valid)} valid LifeTech reports found")

# Preserve the highest-quality deep report, then diversify brokers where possible.
valid.sort(key=lambda x: (x["score"], x["pages"], x.get("date", "")), reverse=True)
selected = []
used_brokers = set()
for item in valid:
    if len(selected) == 3:
        break
    if not selected:
        selected.append(item)
        used_brokers.add(item["broker"])
        continue
    if item["broker"] not in used_brokers:
        selected.append(item)
        used_brokers.add(item["broker"])
for item in valid:
    if len(selected) == 3:
        break
    if item["sha256"] not in {x["sha256"] for x in selected}:
        selected.append(item)

# Two complete reports satisfy the user's requested 2–3 range.
if len(selected) > 3:
    selected = selected[:3]

manifest = []
for index, item in enumerate(selected, start=1):
    broker_ascii = {
        "国金证券": "Sinolink",
        "华安证券": "Huaan",
        "西南证券": "Southwest",
        "东北证券": "Northeast",
        "广发证券": "GF",
        "安信国际": "Essence_International",
    }.get(item["broker"], "Broker")
    date = item.get("date") or "undated"
    filename = f"{index:02d}_{broker_ascii}_{date}_LifeTech_01302_{item['pages']}p.pdf"
    source = Path(item["filePath"])
    destination = PACKAGE / filename
    shutil.copy2(source, destination)
    manifest.append({
        "index": index,
        "broker": item["broker"],
        "date": item.get("date", ""),
        "title": item["title"],
        "report_type": item["report_type"],
        "pages": item["pages"],
        "filename": filename,
        "bytes": item["bytes"],
        "sha256": item["sha256"],
        "source_page": item.get("sourcePage", ""),
        "source_pdf": item.get("pdfUrl", ""),
    })

readme = [
    "先健科技（01302.HK / LifeTech Scientific）券商研究报告合集",
    "",
    f"本包收录{len(manifest)}份公开可取得并通过完整性核验的实际PDF，不含网页跳转文件或预览图片。",
    "",
    "文件清单：",
]
for item in manifest:
    readme.append(
        f"{item['index']}. {item['broker']}｜{item['date']}｜{item['pages']}页｜{item['report_type']}｜{item['title']}"
    )
readme.extend([
    "",
    "校验项目：PDF文件签名、先健科技/LifeTech/01302公司身份、实际页数、首/中/末页渲染、SHA-256及ZIP完整性。",
    "文件仅供个人研究使用，版权归原券商及发布机构所有。",
])
(PACKAGE / "README_文件说明.txt").write_text("\n".join(readme), encoding="utf-8")
(PACKAGE / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
with (PACKAGE / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(manifest[0].keys()))
    writer.writeheader()
    writer.writerows(manifest)

with ZipFile(FINAL, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
    for file_path in sorted(PACKAGE.iterdir(), key=lambda p: p.name):
        archive.write(file_path, arcname=file_path.name)
with ZipFile(FINAL) as archive:
    damaged = archive.testzip()
    if damaged is not None:
        raise RuntimeError(f"ZIP integrity error: {damaged}")
    pdfs = [name for name in archive.namelist() if name.lower().endswith(".pdf")]
    if len(pdfs) != len(manifest):
        raise RuntimeError("ZIP PDF count mismatch")

print("PACKAGE_READY", FINAL, FINAL.stat().st_size)
print(json.dumps(manifest, ensure_ascii=False, indent=2))
