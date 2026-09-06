from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

import requests
from pypdf import PdfReader

URL = "https://www.kerryprops.com/files/news/cn/c_00683ann_20260824_Q4TgaQtzyM.pdf"
OUT = Path("out_kerry_interim_20260906")
OUT.mkdir(exist_ok=True)
PDF = OUT / "Kerry_Properties_00683_2026_Interim_Results_Announcement.pdf"
PNG_PREFIX = OUT / "cover"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
    "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.5",
    "Referer": "https://www.kerryprops.com/cn/news/announcements/2026",
})
response = session.get(URL, timeout=180, allow_redirects=True)
print("GET", response.status_code, response.headers.get("content-type"), len(response.content), response.url)
response.raise_for_status()
if len(response.content) < 100_000 or not response.content.startswith(b"%PDF-"):
    raise RuntimeError("Downloaded content is not a complete PDF")
PDF.write_bytes(response.content)

reader = PdfReader(str(PDF), strict=False)
pages = len(reader.pages)
if pages < 20:
    raise RuntimeError(f"Unexpectedly short interim results announcement: {pages} pages")
text = "\n".join((page.extract_text() or "") for page in reader.pages[:min(12, pages)])
normalized = re.sub(r"\s+", "", text).lower()
if not any(token in normalized for token in ["嘉里建設", "嘉里建设", "kerryproperties", "00683"]):
    print("WARNING_IDENTITY_TEXT_NOT_EXTRACTABLE")

subprocess.run([
    "pdftoppm", "-f", "1", "-l", "1", "-png", "-singlefile", "-r", "100",
    str(PDF), str(PNG_PREFIX)
], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
cover = Path(str(PNG_PREFIX) + ".png")
if not cover.exists() or cover.stat().st_size < 10_000:
    raise RuntimeError("Cover render failed")

meta = {
    "source_url": URL,
    "final_url": str(response.url),
    "pages": pages,
    "bytes": PDF.stat().st_size,
    "sha256": hashlib.sha256(PDF.read_bytes()).hexdigest(),
    "cover_bytes": cover.stat().st_size,
    "publication_date": "2026-08-24",
    "reporting_period_end": "2026-06-30",
}
(OUT / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
print("READY", json.dumps(meta, ensure_ascii=False))
