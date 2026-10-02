"""Collect the dependency notices shipped by installed distributions."""
from pathlib import Path
import importlib.metadata as metadata
import shutil
import archspec

base = Path(__file__).resolve().parent
release = base / 'dist' / 'SeerGallery'
licenses = release / 'licenses'
licenses.mkdir(exist_ok=True)
# CPU architecture descriptions are runtime data used by the ASTC dependency.
shutil.copytree(Path(archspec.__file__).parent / 'json', release / '_internal' / 'archspec' / 'json', dirs_exist_ok=True)
fmod_data = Path(metadata.distribution('fmod-toolkit').locate_file('fmod_toolkit/libfmod/Windows/x64'))
shutil.copytree(fmod_data, release / '_internal' / 'fmod_toolkit' / 'libfmod' / 'Windows' / 'x64', dirs_exist_ok=True)
# Qt 6.11 imports Windows' ICU API. A Poppler ICU on a developer's PATH can
# be incorrectly picked up by PyInstaller; leave resolution to Windows.
for filename in ('icuuc.dll', 'icudt78.dll'):
    wrong_icu = release / '_internal' / filename
    if wrong_icu.is_file():
        wrong_icu.unlink()
for distribution in metadata.distributions():
    name = distribution.metadata.get('Name', 'unknown')
    for file in distribution.files or []:
        if any(word in file.name.lower() for word in ('license', 'copying', 'notice')) and '.dist-info' in str(file):
            source = Path(distribution.locate_file(file))
            if source.is_file():
                target = licenses / name / file.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
source_dir = release / 'source' / 'app'
source_dir.mkdir(parents=True, exist_ok=True)
for filename in ('main.py', 'core.py', 'other_page.py', 'requirements.txt'):
    shutil.copyfile(base / 'app' / filename, source_dir / filename)
shutil.copytree(base / 'app' / 'assets', source_dir / 'assets', dirs_exist_ok=True)
(licenses / 'README.txt').write_text('Dependency copyright and license texts supplied by their installed Python distributions.\nQt/PySide6 shared libraries remain separate in _internal and can be replaced with compatible builds.\nApplication source is included in source/app. Dependencies: https://pypi.org/\nQt source: https://download.qt.io/official_releases/qt/\nPySide source: https://code.qt.io/cgit/pyside/pyside-setup.git/\n', encoding='utf8')
