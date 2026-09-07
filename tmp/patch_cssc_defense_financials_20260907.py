from pathlib import Path

path = Path('tmp/build_cssc_defense_financials_20260907.py')
text = path.read_text(encoding='utf-8')
old = '''    if re.search(
        r"業績|业绩|results|summary|摘要|環境|环境|ESG|sustainab|corporate governance|企業管治|企业管治",
        combined,
        re.I,
    ):
        return -10_000
'''
new = '''    if re.search(
        r"業績|业绩|results|summary|摘要|環境|环境|ESG|sustainab|corporate governance|企業管治|企业管治",
        title,
        re.I,
    ):
        return -10_000
'''
if old not in text:
    raise SystemExit('Expected annual-report exclusion block was not found')
path.write_text(text.replace(old, new, 1), encoding='utf-8')
print('PATCHED_ANNUAL_FILTER')
