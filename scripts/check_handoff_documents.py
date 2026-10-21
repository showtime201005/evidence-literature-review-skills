"""Check handoff document encoding and local links without a browser or API."""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

from package_handoff import selected_files


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.links = []
        self.assets = []
        self.language = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.append(attrs['id'])
        if tag == 'html':
            self.language = attrs.get('lang')
        if tag == 'a' and attrs.get('href'):
            self.links.append(attrs['href'])
        if tag in ('script', 'img', 'iframe', 'source') and attrs.get('src'):
            self.assets.append(attrs['src'])
        if tag == 'link' and attrs.get('href'):
            self.assets.append(attrs['href'])


def review(root):
    packaged_paths = {name for name, _ in selected_files(root)}
    names = ['README.md', 'INSTALL.md', 'docs/PACKAGE-README.zh-TW.md',
             'docs/HANDOFF-2026-10-21.zh-TW.md', 'docs/implementation-guide.zh-TW.html']
    errors, files, generated = [], [], []
    for name in names:
        path = root / name
        text = path.read_text(encoding='utf-8')
        if '\ufffd' in text:
            errors.append(name + ': Unicode replacement character')
        page = None
        if path.suffix == '.html':
            page = Page()
            page.feed(text)
            links = page.links
            if not page.language or not page.language.lower().startswith('zh'):
                errors.append(name + ': missing Chinese language declaration')
            duplicates = [key for key, count in Counter(page.ids).items() if count > 1]
            errors.extend(name + ': duplicate id ' + key for key in duplicates)
            for asset in page.assets:
                if urlsplit(asset).scheme in ('http', 'https') or asset.startswith('//'):
                    errors.append(name + ': external asset ' + asset)
            for skill in ('analyze-paper', 'compare-papers', 'write-review',
                          'verify-citations', 'literature-review'):
                if skill not in text:
                    errors.append(name + ': missing skill ' + skill)
        else:
            links = re.findall(r'\[[^\]]+\]\(([^)]+)\)', text)
        for link in links:
            parts = urlsplit(link.strip('<>'))
            if parts.scheme or parts.netloc:
                continue
            if not parts.path:
                if page and parts.fragment and unquote(parts.fragment) not in page.ids:
                    errors.append(name + ': unknown anchor ' + parts.fragment)
                continue
            target = (path.parent / unquote(parts.path)).resolve()
            try:
                relative = target.relative_to(root).as_posix()
            except ValueError:
                errors.append(name + ': file outside package root ' + link)
                continue
            if not target.exists():
                if relative.startswith('dist/evidence-literature-review-handoff-2026-10-21.zip'):
                    generated.append(relative)
                else:
                    errors.append(name + ': missing file ' + link)
            elif relative not in packaged_paths and not relative.startswith('dist/'):
                errors.append(name + ': local file excluded from package ' + link)
        files.append({'path': name, 'bytes': path.stat().st_size,
                      'sha256': sha256(path.read_bytes()).hexdigest(),
                      'links_checked': len(links)})
    return {'schema': 'handoff-document-static-review/1', 'passed': not errors,
            'files': files, 'errors': errors, 'pending_generated_dist_links': sorted(set(generated)),
            'network_calls': 0, 'model_calls': 0,
            'browser_visual_review': 'not_performed_no_available_browser',
            'scope': 'UTF-8, replacement characters, local file links, HTML anchors, duplicate IDs, external asset dependencies, five skill names; not functional or scientific acceptance'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    result = review(args.root.resolve())
    serialized = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(serialized, encoding='utf-8')
    print(serialized)
    raise SystemExit(0 if result['passed'] else 1)
