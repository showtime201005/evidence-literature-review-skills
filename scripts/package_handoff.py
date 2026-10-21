"""Build a reproducible, credential-free development handoff ZIP (stdlib only)."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

DIRECTORIES = ('skills', 'scripts', 'tests', 'docs', 'examples')
ROOT_FILES = ('README.md', 'INSTALL.md', '.gitignore', '.gitattributes')
EXCLUDED = {'.git', '__pycache__', 'node_modules', '.venv', 'dist'}


def selected_files(root):
    paths = [root / name for name in ROOT_FILES if (root / name).is_file()]
    for name in DIRECTORIES:
        paths.extend(p for p in (root / name).rglob('*') if p.is_file())
    for path in sorted(set(paths)):
        rel = path.relative_to(root)
        if any(part in EXCLUDED for part in rel.parts) or path.suffix == '.pyc':
            continue
        if path.name.startswith('.env') or path.is_symlink():
            raise ValueError('Forbidden package entry: ' + rel.as_posix())
        yield rel.as_posix(), path


def build(root, out):
    entries = []
    for name, path in selected_files(root):
        data = path.read_bytes()
        # Detect credential formats, without printing any matching values.
        for pattern in (rb'sk-or-v1-[A-Za-z0-9]{20,}',
                        rb'gh[pousr]_[A-Za-z0-9]{20,}',
                        rb'github_pat_[A-Za-z0-9_]{30,}',
                        rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'):
            if re.search(pattern, data):
                raise ValueError('Possible credential in package entry: ' + name)
        entries.append((name, data))
    manifest = {
        'schema': 'literature-review-handoff-package/1',
        'snapshot': '2026-10-21',
        'status': 'development_handoff_not_acceptance_release',
        'model': 'qwen/qwen3.8-27b',
        'hundred_paper_90_minute_acceptance_passed': False,
        'selection': {'directories': list(DIRECTORIES), 'root_files': list(ROOT_FILES)},
        'excluded': ['git metadata', 'environment files', 'venvs', 'Python caches',
                     'unselected historical reports', 'raw external run directories'],
        'files': [{'path': name, 'bytes': len(data),
                   'sha256': hashlib.sha256(data).hexdigest()} for name, data in entries],
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in entries + [('PACKAGE-MANIFEST.json', manifest_bytes)]:
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 21, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    with zipfile.ZipFile(out) as archive:
        if archive.testzip() is not None:
            raise ValueError('Archive CRC check failed')
        for item in manifest['files']:
            if hashlib.sha256(archive.read(item['path'])).hexdigest() != item['sha256']:
                raise ValueError('Archive content hash mismatch: ' + item['path'])
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    checksum = out.with_suffix(out.suffix + '.sha256')
    checksum.write_text(digest + '  ' + out.name + '\n', encoding='ascii')
    out.with_suffix('.manifest.json').write_bytes(manifest_bytes)
    print(json.dumps({'archive': str(out), 'files': len(entries),
                      'bytes': out.stat().st_size, 'sha256': digest}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    build(root, args.out or root / 'dist' / 'evidence-literature-review-handoff-2026-10-21.zip')
