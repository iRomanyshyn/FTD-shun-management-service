"""Deterministic public application-source identity, generated at build time."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from . import __version__


def source_build(root: Path) -> dict:
    """Hash an explicit public input set, never Git, environment or deploy secrets."""
    files = [root / 'pyproject.toml']
    for directory, suffixes in (('src', {'.py'}), ('templates', {'.html'}), ('static', {'.css', '.js', '.svg', '.png', '.ico'})):
        if not (root / directory).is_dir() or (root / directory).is_symlink():
            raise ValueError('Build input directories must exist and must not be symlinks.')
        if any(path.is_symlink() for path in (root / directory).rglob('*')):
            raise ValueError('Build inputs must not contain symlinks.')
        files.extend(path for path in (root / directory).rglob('*')
                     if path.suffix in suffixes and path.is_file() and '__pycache__' not in path.parts)
    digest = hashlib.sha256(b'ftd-shun-manager:application-source:v1\n')
    for path in sorted(files):
        if path.is_symlink():
            raise ValueError('Build inputs must not be symlinks.')
        name, content = path.relative_to(root).as_posix().encode(), path.read_bytes()
        for value in (name, content):
            digest.update(len(value).to_bytes(8, 'big'))
            digest.update(value)
    value = digest.hexdigest()
    return {'version': __version__, 'source_id': value[:12], 'source_sha256': value}


def load_build(root: Path) -> dict | None:
    """Read once at application import; never inspect source/Git per request."""
    path = root / 'build-info.json'
    if not path.exists():
        return None  # A source checkout is honestly unlabelled, not a made-up build.
    value = json.loads(path.read_text())
    if (type(value) is not dict or set(value) != {'version', 'source_id', 'source_sha256'}
            or value['version'] != __version__ or type(value['source_sha256']) is not str
            or re.fullmatch('[0-9a-f]{64}', value['source_sha256']) is None
            or value['source_id'] != value['source_sha256'][:12]):
        raise ValueError('Build identity is invalid or belongs to another product version.')
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    value = source_build(args.root.resolve())
    (args.root / 'build-info.json').write_text(json.dumps(value, sort_keys=True) + '\n')
    print(json.dumps(value, sort_keys=True))


if __name__ == '__main__':
    main()
