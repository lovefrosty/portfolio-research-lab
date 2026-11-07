"""Verify an explicit publication manifest and local document links.

The manifest excludes itself. It is a byte-integrity check, not a certificate
of content safety or redistribution rights. Regenerate only after reviewing
the intended file changes; unexpected files must never be auto-admitted.
"""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = 'release-manifest.json'
LOCAL_DIRECTORIES = {'.git', '.venv', '__pycache__', '.pytest_cache'}


def release_files(root: Path) -> set[str]:
    result = set()
    for path in root.rglob('*'):
        relative = path.relative_to(root)
        if any(part in LOCAL_DIRECTORIES for part in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError(f'symlink_not_allowed: {relative}')
        if path.is_file() and str(relative) != MANIFEST:
            result.add(relative.as_posix())
    return result


def check(root: Path = ROOT) -> dict:
    manifest = json.loads((root / MANIFEST).read_text())
    expected = manifest['files']
    assert set(expected) == release_files(root), 'release_file_set_mismatch'
    for name, expected_hash in expected.items():
        relative = PurePosixPath(name)
        assert not relative.is_absolute() and '..' not in relative.parts, 'unsafe_manifest_path'
        path = root / name
        raw = path.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == expected_hash, f'hash_mismatch: {name}'
        assert path.suffix not in {'.db', '.sqlite', '.parquet', '.pem', '.key', '.pkl', '.csv'}, f'excluded_type: {name}'
        assert not path.name.startswith('.env'), f'environment_file: {name}'
        text = raw.decode('utf-8')
        assert not re.search(r'/(?:Users|home)/[A-Za-z0-9_.-]+', text), f'private_home_path: {name}'
        if path.suffix == '.md':
            for target in re.findall(r'\[[^\]]*\]\(([^\s)]+)\)', text):
                parsed = urlsplit(target)
                if parsed.scheme or not parsed.path:
                    continue
                linked = (path.parent / unquote(parsed.path)).resolve()
                assert linked.is_relative_to(root.resolve()) and linked.exists(), f'broken_local_link: {name}'
    if (root / '.git').is_dir():
        tracked = set(subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')) - {''}
        assert tracked == set(expected) | {MANIFEST}, 'tracked_file_set_mismatch'
    return {'files': len(expected), 'manifest': MANIFEST, 'status': 'pass',
            'scope': 'File selection, byte identity, selected private-path checks and local link targets.'}


if __name__ == '__main__':
    print(json.dumps(check(), indent=2))
