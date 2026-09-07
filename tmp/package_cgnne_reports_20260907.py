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

OUT = Path("out_cgnne_reports_20260907")
RAW = OUT / "raw_pdfs"
PACKAGE = OUT / "package"
RENDERS = OUT / "renders"
FINAL = OUT / "CGN_New_Energy_01811_Broker_Research_Reports.zip"
PACKAGE.mkdir(parents=True, exist_ok=True)
RENDERS.mkdir(parents=True, exist_ok=True)

REPORT_DEFS = [
    {
        "key": "2021_guoxin_initiation",
        "date": "2021-07-11",
        "broker": "国信证券",
        "title": "清洁能源新栋梁，直挂云帆济沧海",
        "type": "首次覆盖 / 公司深度",
        "patterns": ["清洁能源新栋梁", "直挂云帆济沧海"],
        "label_patterns": ["20210711", "44868", "679344712485"],
        "min_pages": 35,
        "priority": 100,
        "output": "01_Guoxin_2021-07-11_CGN_New_Energy_Initiation.pdf",
    },
    {
        "key": "2022_guoxin_hk_deep",
        "date": "2022-04-22",
        "broker": "国信证券（香港）",
        "title": "稳步成长的新能源运营商",
        "type": "公司深度研究",
        "patterns": ["稳步成长的新能源运营商"],
        "label_patterns": ["20220422", "70108"],
        "min_pages": 12,
        "priority": 95,
        "output": "02_Guoxin_HK_2022-04-22_CGN_New_Energy_Deep_Report.pdf",
    },
    {
        "key": "2024_guoxin_hk_update",
        "date": "2024-05-23",
        "broker": "国信证券（香港）",
        "title": "稳健增长，估值修复行情持续",
        "type": "港股公司研究",
        "patterns": ["稳健增长", "估值修复行情持续"],
        "label_patterns": ["20240523", "3374738651710752209"],
        "min_pages": 2,
        "priority": 80,
        "output": "03_Guoxin_HK_2024-05-23_CGN_New_Energy_Update.pdf",
    },
    {
        "key": "2025_guoyuan_update",
        "date": "2025-01-15",
        "broker": "国元国际",
        "title": "24年发电量微增长，期待25年估值修复",
        "type": "港股公司研究",
        "patterns": ["24年发电量微增长", "期待25年估值修复"],
        "label_patterns": ["20250115", "3545846060268127552"],
        "min_pages": 2,
        "priority": 75,
        "output": "04_Guoyuan_2025-01-15_CGN_New_Energy_Update.pdf",
    },
]


def inspect(path: Path) -> dict | None:
    data = path.read_bytes()
    if not data.startswith(b"%PDF-") or len(data) < 30_000:
        return None
    digest = hashlib.sha256(data).hexdigest()
    try:
        reader = PdfReader(str(path), strict=False)
        pages = len(reader.pages)
        if pages < 2:
            return None
        indexes = list(range(min(15, pages)))
        if pages > 20:
            indexes.extend([pages // 2, pages - 1])
        parts = []
        for index in sorted(set(indexes)):
            try:
                parts.append(reader.pages[index].extract_text() or "")
            except Exception:
                pass
        text = "\n".join(parts)
    except Exception:
        return None
    normalized = re.sub(r"\s+", "", text).lower()
    identity_tokens = [
        "中广核新能源",
        "中廣核新能源",
        "cgnnewenergy",
        "1811.hk",
        "01811",
    ]
    if not any(token.replace(" ", "").lower() in normalized for token in identity_tokens):
        return None
    return {
        "path": path,
        "pages": pages,
        "bytes": len(data),
        "sha256": digest,
        "text": text,
        "normalized": normalized,
    }


collected_meta = []
collected_json = OUT / "collected.json"
if collected_json.exists():
    try:
        collected_meta = json.loads(collected_json.read_text(encoding="utf-8"))
    except Exception:
        collected_meta = []
label_by_path = {str(Path(row.get("file", ""))): str(row.get("label", "")) for row in collected_meta}
source_by_path = {str(Path(row.get("file", ""))): str(row.get("sourceUrl", "")) for row in collected_meta}

inspected = []
seen_hashes = set()
for path in sorted(RAW.glob("*.pdf")):
    item = inspect(path)
    if item is None or item["sha256"] in seen_hashes:
        continue
    seen_hashes.add(item["sha256"])
    item["label"] = label_by_path.get(str(path), path.name)
    item["source_url"] = source_by_path.get(str(path), "")
    inspected.append(item)
    print("VALID_PDF", path.name, item["pages"], item["label"])

if not inspected:
    raise RuntimeError("No collected PDF passed CGN New Energy identity validation")

matches = []
for definition in REPORT_DEFS:
    candidates = []
    for item in inspected:
        pattern_hits = sum(
            pattern.replace(" ", "").lower() in item["normalized"]
            for pattern in definition["patterns"]
        )
        label_lower = item["label"].lower()
        label_hits = sum(pattern.lower() in label_lower for pattern in definition["label_patterns"])
        score = pattern_hits * 100 + label_hits * 30 + min(item["pages"], 60)
        if pattern_hits or label_hits:
            candidates.append((score, item))
    if not candidates:
        continue
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    item = candidates[0][1]
    if item["pages"] < definition["min_pages"]:
        print("REJECT_SHORT", definition["key"], item["pages"], definition["min_pages"])
        continue
    matches.append((definition, item))
    print("MATCHED_REPORT", definition["key"], item["pages"], item["path"].name)

# Deduplicate report editions by PDF hash and keep the highest-priority definitions.
matches.sort(key=lambda pair: (pair[0]["priority"], pair[1]["pages"]), reverse=True)
selected = []
used_hashes = set()
used_keys = set()
for definition, item in matches:
    if item["sha256"] in used_hashes or definition["key"] in used_keys:
        continue
    selected.append((definition, item))
    used_hashes.add(item["sha256"])
    used_keys.add(definition["key"])
    if len(selected) == 3:
        break

if len(selected) < 2:
    detail = [(d["key"], i["pages"], i["path"].name) for d, i in matches]
    raise RuntimeError(f"Only {len(selected)} distinct usable reports were found: {detail}")

manifest = []
for index, (definition, item) in enumerate(selected, 1):
    output_name = re.sub(r"^\d+_", f"{index:02d}_", definition["output"])
    destination = PACKAGE / output_name
    shutil.copy2(item["path"], destination)

    for page_number in sorted({1, max(1, (item["pages"] + 1) // 2), item["pages"]}):
        prefix = RENDERS / f"{destination.stem}_p{page_number}"
        subprocess.run(
            [
                "pdftoppm", "-f", str(page_number), "-l", str(page_number),
                "-png", "-singlefile", "-r", "90", str(destination), str(prefix),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        image = Path(str(prefix) + ".png")
        if not image.exists() or image.stat().st_size < 8_000:
            raise RuntimeError(f"Render validation failed: {destination.name} page {page_number}")

    manifest.append({
        "序号": index,
        "券商": definition["broker"],
        "发布日期": definition["date"],
        "报告标题": definition["title"],
        "报告性质": definition["type"],
        "实际页数": item["pages"],
        "文件名": output_name,
        "文件大小_字节": item["bytes"],
        "SHA256": item["sha256"],
        "获取来源": item["source_url"],
    })

readme = [
    "中广核新能源（01811.HK）券商研究报告合集",
    "",
    f"本压缩包收录{len(manifest)}份公开可直接取得、经完整性核验的实际券商PDF。",
    "不含网页快捷方式、预览图片或自行编写的摘要。",
    "",
    "文件清单：",
]
for row in manifest:
    readme.append(
        f"{row['序号']}. {row['券商']}｜{row['发布日期']}｜{row['实际页数']}页｜"
        f"{row['报告性质']}｜{row['报告标题']}"
    )
readme.extend([
    "",
    "校验项目：PDF文件签名、公司名称/证券代码、实际页数、SHA-256、首中末页渲染及ZIP完整性。",
    "文件仅供个人研究使用，版权归原券商及发布机构所有。",
])
(PACKAGE / "README_文件说明.txt").write_text("\n".join(readme), encoding="utf-8")
(PACKAGE / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
with (PACKAGE / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(manifest[0].keys()))
    writer.writeheader()
    writer.writerows(manifest)

FINAL.unlink(missing_ok=True)
with ZipFile(FINAL, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
    for member in sorted(PACKAGE.iterdir(), key=lambda p: p.name):
        archive.write(member, arcname=member.name)
with ZipFile(FINAL) as archive:
    bad = archive.testzip()
    if bad is not None:
        raise RuntimeError(f"ZIP integrity failure: {bad}")
    pdf_names = [name for name in archive.namelist() if name.lower().endswith(".pdf")]
    if len(pdf_names) != len(manifest):
        raise RuntimeError(f"ZIP PDF count mismatch: {len(pdf_names)} != {len(manifest)}")

print("PACKAGE_READY", FINAL, FINAL.stat().st_size)
print(json.dumps(manifest, ensure_ascii=False, indent=2))
