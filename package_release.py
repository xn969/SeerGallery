from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

base = Path(__file__).resolve().parent
release = base / 'dist' / 'SeerGallery'
archive = base / 'SeerGallery-0.1.0-Windows-x64.zip'
with ZipFile(archive, 'w', ZIP_DEFLATED, compresslevel=6) as output:
    for file in release.rglob('*'):
        if not file.is_file():
            continue
        relative = file.relative_to(release)
        if relative.parts[0].lower() == 'output' or file.name == 'smoke-error.txt' or file.name.startswith('ui-'):
            continue
        if file.name in ('验证报告.md', '其他图片检查报告.md'):
            continue
        output.write(file, Path('SeerGallery') / relative)
with ZipFile(archive) as packaged:
    bad = packaged.testzip()
    if bad:
        raise RuntimeError('压缩包校验失败：' + bad)
print(str(archive), archive.stat().st_size)
