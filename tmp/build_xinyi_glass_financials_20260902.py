from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path
from zipfile import ZipFile

from pypdf import PdfReader

OUT = Path("out_xinyi_glass_financials_20260902")
REPORTS = OUT / "reports"
shutil.rmtree(OUT, ignore_errors=True)
REPORTS.mkdir(parents=True, exist_ok=True)

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36"

ANNUALS = [
    (2020, "https://www.xinyiglass.com/uploadfiles/2021/04/%E4%BF%A1%E7%BE%A9%E7%8E%BB%E7%92%83%E4%BA%8C%E9%9B%B6%E4%BA%8C%E9%9B%B6%E5%B9%B4%E5%B9%B4%E5%A0%B1.pdf"),
    (2021, "https://www.xinyiglass.com/uploadfiles/2022/05/%E4%BF%A1%E7%BE%A9%E7%8E%BB%E7%92%83%E4%BA%8C%E9%9B%B6%E4%BA%8C%E4%B8%80%E5%B9%B4%E5%B9%B4%E6%8A%A5.pdf"),
    (2022, "https://www.xinyiglass.com/uploadfiles/2023/05/%E4%BF%A1%E4%B9%89%E7%8E%BB%E7%92%83%E4%BA%8C%E9%9B%B6%E4%BA%8C%E4%BA%8C%E5%B9%B4%E5%B9%B4%E6%8A%A5.pdf"),
    (2023, "https://www.xinyiglass.com/uploadfiles/2024/05/%E4%BF%A1%E4%B9%89%E7%8E%BB%E7%92%83%E4%BA%8C%E9%9B%B6%E4%BA%8C%E4%B8%89%E5%B9%B4%E5%B9%B4%E6%8A%A5.pdf"),
    (2024, "https://www.xinyiglass.com/uploadfiles/2025/05/%E4%BF%A1%E4%B9%89%E7%8E%BB%E7%92%832024%E5%B9%B4%E5%B9%B4%E6%8A%A5-%E7%B9%81%E4%BD%93%E4%B8%AD%E6%96%87.pdf"),
    (2025, "https://www.xinyiglass.com/uploadfiles/2026/05/%E4%BF%A1%E4%B9%89%E7%8E%BB%E7%92%832025%E5%B9%B4%E5%B9%B4%E6%8A%A5-%E7%AE%80%E4%BD%93.pdf"),
]

INTERIM_CANDIDATES = [
    "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0731/2026073101562.pdf",
    "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0731/2026073101563.pdf",
]


def download(url: str, dest: Path) -> None:
    cmd = [
        "curl", "--fail", "--location", "--silent", "--show-error",
        "--retry", "5", "--retry-all-errors", "--connect-timeout", "30",
        "--max-time", "420", "--user-agent", UA,
        "--header", "Accept: application/pdf,*/*;q=0.8",
        "--output", str(dest), url,
    ]
    subprocess.run(cmd, check=True)
    if not dest.exists() or dest.stat().st_size < 100_000:
        raise RuntimeError(f"Downloaded file is unexpectedly small: {dest}")
    if dest.read_bytes()[:5] != b"%PDF-":
        raise RuntimeError(f"Not a PDF: {dest}")


def inspect_pdf(path: Path, min_pages: int, expected_tokens: tuple[str, ...]) -> tuple[int, str]:
    reader = PdfReader(str(path))
    pages = len(reader.pages)
    if pages < min_pages:
        raise RuntimeError(f"Too few pages in {path.name}: {pages} < {min_pages}")
    sample = "\n".join((p.extract_text() or "") for p in reader.pages[:8])
    if not any(token.lower() in sample.lower() for token in expected_tokens):
        raise RuntimeError(f"Company/year validation failed for {path.name}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return pages, digest


manifest_rows: list[str] = []

for index, (year, url) in enumerate(ANNUALS, start=1):
    dest = REPORTS / f"{index:02d}_信义玻璃_{year}年年度报告.pdf"
    print(f"Downloading annual report {year}: {url}")
    download(url, dest)
    pages, digest = inspect_pdf(dest, 150, ("信義玻璃", "信义玻璃", "XINYI GLASS", str(year)))
    manifest_rows.append(f"{dest.name}\t{pages}页\tSHA256={digest}\t{url}")
    print(dest.name, pages, dest.stat().st_size, digest)

interim_dest = REPORTS / "07_信义玻璃_2026年中期业绩公告_截至2026年6月30日.pdf"
last_error: Exception | None = None
selected_interim_url = ""
for url in INTERIM_CANDIDATES:
    try:
        temp = REPORTS / "_interim_candidate.pdf"
        temp.unlink(missing_ok=True)
        print(f"Trying interim disclosure: {url}")
        download(url, temp)
        pages, digest = inspect_pdf(temp, 20, ("信義玻璃", "XINYI GLASS", "30 June 2026", "二零二六"))
        temp.replace(interim_dest)
        selected_interim_url = url
        manifest_rows.append(f"{interim_dest.name}\t{pages}页\tSHA256={digest}\t{url}")
        print(interim_dest.name, pages, interim_dest.stat().st_size, digest)
        break
    except Exception as exc:
        last_error = exc
        print(f"Candidate failed: {url}: {exc}")
else:
    raise RuntimeError(f"No valid 2026 interim disclosure could be downloaded: {last_error}")

readme = """信义玻璃控股有限公司（00868.HK）财务报告合集

内容：
- 2020年至2025年年度报告，共6份；
- 截至2026年6月30日止六个月的最新中期业绩公告，共1份。

说明：
信义玻璃为香港上市公司，通常按年度和半年度披露财务报告，并无A股式普通季度报告。截至2026年9月2日，最新可获得的财务披露为2026年中期业绩公告；2026年正式中期报告尚未在公司财务报告页面列示，因此本合集以该公告作为“最新季报/最新定期财务披露”。

来源：信义玻璃官方网站及香港交易所披露易。
仅供个人研究使用，文件版权归信义玻璃及原发布机构所有。
"""
(REPORTS / "README_文件说明.txt").write_text(readme, encoding="utf-8")
(REPORTS / "文件清单与校验值.txt").write_text("\n".join(manifest_rows) + "\n", encoding="utf-8")

# Final package integrity check. GitHub Actions will upload REPORTS directly,
# so the downloaded artifact itself is the ZIP requested by the user.
pdfs = sorted(REPORTS.glob("*.pdf"))
if len(pdfs) != 7:
    raise RuntimeError(f"Expected 7 PDFs, got {len(pdfs)}")
for p in pdfs:
    if p.read_bytes()[:5] != b"%PDF-":
        raise RuntimeError(f"Invalid PDF signature: {p}")

print("READY", len(pdfs), "PDFs", sum(p.stat().st_size for p in pdfs), "bytes")
