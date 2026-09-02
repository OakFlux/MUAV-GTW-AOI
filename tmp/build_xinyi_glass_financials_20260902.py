from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

from pypdf import PdfReader

OUT = Path("out_xinyi_glass_financials_20260902")
REPORTS = OUT / "reports"
shutil.rmtree(OUT, ignore_errors=True)
REPORTS.mkdir(parents=True, exist_ok=True)

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36"

# All annual-report URLs below are the official Chinese-language files listed on
# Xinyi Glass's investor-relations financial reports page.
ANNUALS = [
    (2020, 163, "https://www.xinyiglass.com/uploadfiles/2021/04/%E4%BF%A1%E7%BE%A9%E7%8E%BB%E7%92%83%E4%BA%8C%E9%9B%B6%E4%BA%8C%E9%9B%B6%E5%B9%B4%E5%B9%B4%E5%A0%B1.pdf"),
    (2021, 179, "https://www.xinyiglass.com/uploadfiles/2022/05/%E4%BF%A1%E7%BE%A9%E7%8E%BB%E7%92%83%E4%BA%8C%E9%9B%B6%E4%BA%8C%E4%B8%80%E5%B9%B4%E5%B9%B4%E6%8A%A5.pdf"),
    (2022, 179, "https://www.xinyiglass.com/uploadfiles/2023/05/%E4%BF%A1%E4%B9%89%E7%8E%BB%E7%92%83%E4%BA%8C%E9%9B%B6%E4%BA%8C%E4%BA%8C%E5%B9%B4%E5%B9%B4%E6%8A%A5.pdf"),
    (2023, 183, "https://www.xinyiglass.com/uploadfiles/2024/05/%E4%BF%A1%E4%B9%89%E7%8E%BB%E7%92%83%E4%BA%8C%E9%9B%B6%E4%BA%8C%E4%B8%89%E5%B9%B4%E5%B9%B4%E6%8A%A5.pdf"),
    (2024, 187, "https://www.xinyiglass.com/uploadfiles/2025/05/%E4%BF%A1%E4%B9%89%E7%8E%BB%E7%92%832024%E5%B9%B4%E5%B9%B4%E6%8A%A5-%E7%B9%81%E4%BD%93%E4%B8%AD%E6%96%87.pdf"),
    (2025, 189, "https://www.xinyiglass.com/uploadfiles/2026/05/%E4%BF%A1%E4%B9%89%E7%8E%BB%E7%92%832025%E5%B9%B4%E5%B9%B4%E6%8A%A5-%E7%AE%80%E4%BD%93.pdf"),
]

# Latest financial disclosure available as of 2026-09-02. Xinyi Glass is a
# Hong Kong issuer and does not publish A-share-style ordinary quarterly reports.
INTERIM_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0731/2026073101563.pdf"
INTERIM_EXPECTED_PAGES = 48


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


def inspect_pdf(path: Path, expected_pages: int, text_tokens: tuple[str, ...] = ()) -> tuple[int, str]:
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages != expected_pages:
        raise RuntimeError(f"Unexpected page count in {path.name}: {pages} != {expected_pages}")

    # Legacy CJK PDFs may contain a valid but non-standard text layer. Therefore
    # annual reports are validated structurally by their exact official page count.
    # The current HKEX interim announcement has a normal extractable text layer.
    if text_tokens:
        sample = "\n".join((p.extract_text() or "") for p in reader.pages[:8])
        if not any(token.lower() in sample.lower() for token in text_tokens):
            raise RuntimeError(f"Content validation failed for {path.name}")

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return pages, digest


manifest_rows: list[str] = []

for index, (year, expected_pages, url) in enumerate(ANNUALS, start=1):
    dest = REPORTS / f"{index:02d}_信义玻璃_{year}年年度报告.pdf"
    print(f"Downloading annual report {year}: {url}")
    download(url, dest)
    pages, digest = inspect_pdf(dest, expected_pages)
    manifest_rows.append(f"{dest.name}\t{pages}页\t{dest.stat().st_size}字节\tSHA256={digest}\t{url}")
    print(dest.name, pages, dest.stat().st_size, digest)

interim_dest = REPORTS / "07_信义玻璃_2026年中期业绩公告_截至2026年6月30日_英文版.pdf"
print(f"Downloading latest interim disclosure: {INTERIM_URL}")
download(INTERIM_URL, interim_dest)
pages, digest = inspect_pdf(
    interim_dest,
    INTERIM_EXPECTED_PAGES,
    ("XINYI GLASS", "INTERIM RESULTS", "30 JUNE 2026"),
)
manifest_rows.append(f"{interim_dest.name}\t{pages}页\t{interim_dest.stat().st_size}字节\tSHA256={digest}\t{INTERIM_URL}")
print(interim_dest.name, pages, interim_dest.stat().st_size, digest)

readme = """信义玻璃控股有限公司（00868.HK）财务报告合集

内容：
- 2020年至2025年年度报告，共6份，均为信义玻璃官网提供的中文PDF；
- 截至2026年6月30日止六个月的最新中期业绩公告，共1份，为香港交易所披露易英文原版PDF。

说明：
信义玻璃为香港上市公司，通常按年度和半年度披露财务报告，并无A股式普通季度报告。截至2026年9月2日，公司财务报告页面尚未列示2026年正式中期报告；最新可获得的完整财务披露为2026年中期业绩公告，因此本合集将其作为“最新季报/最新定期财务披露”收录。

来源：信义玻璃官方网站及香港交易所披露易。
仅供个人研究使用，文件版权归信义玻璃及原发布机构所有。
"""
(REPORTS / "README_文件说明.txt").write_text(readme, encoding="utf-8")
(REPORTS / "文件清单与校验值.txt").write_text("\n".join(manifest_rows) + "\n", encoding="utf-8")

pdfs = sorted(REPORTS.glob("*.pdf"))
if len(pdfs) != 7:
    raise RuntimeError(f"Expected 7 PDFs, got {len(pdfs)}")
for p in pdfs:
    if p.read_bytes()[:5] != b"%PDF-":
        raise RuntimeError(f"Invalid PDF signature: {p}")

print("READY", len(pdfs), "PDFs", sum(p.stat().st_size for p in pdfs), "bytes")
