"""Assemble a clean Windows ZIP and corresponding source, never reading user data."""
import hashlib
import importlib.metadata
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSION = 'v1.0.0'
NAME = f'MediaArchive-{VERSION}-Windows-x64'
OUT = ROOT / 'release'
STAGE = OUT / NAME
ZIP = OUT / f'{NAME}.zip'
BUILD = ROOT / 'work' / 'package-dist' / 'MediaArchive'
GALLERY_SOURCE = ROOT / 'work' / 'source-download' / 'gallery_dl-1.32.19.tar.gz'
SOURCE_FILES = ('.gitignore', '.gitattributes', 'README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md',
                'requirements.txt', 'requirements-dev.txt', 'requirements-lock.txt', 'build.cmd',
                'install.cmd', 'Start App.cmd', 'Start App.vbs', 'main.py', 'package_release.py')
SOURCE_DIRS = ('app', 'assets', 'docs', 'tests')


def source_paths():
    for name in SOURCE_FILES:
        path = ROOT / name
        if path.is_file():
            yield path
    for directory in SOURCE_DIRS:
        for path in sorted((ROOT / directory).rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix not in {'.pyc', '.pyo', '.sqlite', '.sqlite3', '.dpapi', '.log'}:
                yield path


def license_files(target):
    target.mkdir()
    manifest = []
    for dist in sorted(importlib.metadata.distributions(), key=lambda d: d.metadata.get('Name', '').lower()):
        name = dist.metadata.get('Name')
        if not name:
            continue
        entry = {'name':name, 'version':dist.version,
                 'license':dist.metadata.get('License-Expression') or dist.metadata.get('License') or ''}
        if '\n' in entry['license']:
            entry['license'] = 'See bundled license text'
        manifest.append(entry)
        for file in dist.files or []:
            parts = Path(str(file)).parts
            if not any('.dist-info' in part for part in parts):
                continue
            if not (Path(str(file)).name.upper().startswith(('LICENSE', 'COPYING', 'NOTICE')) or 'licenses' in parts):
                continue
            source = Path(dist.locate_file(file))
            if not source.is_file():
                continue
            rel = next((Path(*parts[i+1:]) for i, part in enumerate(parts) if '.dist-info' in part), Path(source.name))
            dest = target / f'{name}-{dist.version}' / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
    (target / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')


def main():
    if not (BUILD / 'MediaArchive.exe').is_file() or not GALLERY_SOURCE.is_file():
        raise SystemExit('Build the executable and download gallery-dl 1.32.19 source first.')
    if STAGE.exists() or ZIP.exists():
        raise SystemExit('Release output already exists. Choose a new version or move the existing release aside.')
    OUT.mkdir(exist_ok=True)
    shutil.copytree(BUILD, STAGE, ignore=shutil.ignore_patterns('data', 'downloads', '*.dpapi', '*.sqlite*', '*.log', '*.part'))
    for name in ('LICENSE', 'README.md', 'THIRD_PARTY_NOTICES.md'):
        shutil.copy2(ROOT / name, STAGE / name)
    shutil.copytree(ROOT / 'docs', STAGE / 'docs')
    license_files(STAGE / 'third-party-licenses')
    (STAGE / 'third-party-source').mkdir()
    shutil.copy2(GALLERY_SOURCE, STAGE / 'third-party-source' / GALLERY_SOURCE.name)
    with zipfile.ZipFile(STAGE / 'MediaArchive-source.zip', 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in source_paths():
            archive.write(path, path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(ZIP, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(STAGE.rglob('*')):
            if path.is_file():
                archive.write(path, path.relative_to(OUT).as_posix())
    digest = hashlib.sha256(ZIP.read_bytes()).hexdigest()
    (OUT / f'{ZIP.name}.sha256').write_text(f'{digest}  {ZIP.name}\n', encoding='ascii')
    print(f'Created {ZIP} ({ZIP.stat().st_size / 1024 / 1024:.1f} MiB); SHA256 {digest}')


if __name__ == '__main__':
    main()
