import hashlib
import json
import pytest
from scripts.check_release import check


def fixture(root, text='safe example'):
    (root / 'README.md').write_text(text)
    (root / 'release-manifest.json').write_text(json.dumps({
        'files': {'README.md': hashlib.sha256(text.encode()).hexdigest()}}))


def test_release_rejects_unreviewed_file(tmp_path):
    fixture(tmp_path)
    (tmp_path / 'extra.json').write_text('{}')
    with pytest.raises(AssertionError, match='release_file_set_mismatch'):
        check(tmp_path)


def test_release_rejects_changed_content(tmp_path):
    fixture(tmp_path)
    (tmp_path / 'README.md').write_text('changed')
    with pytest.raises(AssertionError, match='hash_mismatch'):
        check(tmp_path)


def test_release_rejects_missing_link(tmp_path):
    fixture(tmp_path, '[missing](missing.md)')
    with pytest.raises(AssertionError, match='broken_local_link'):
        check(tmp_path)


def test_release_rejects_symlink(tmp_path):
    fixture(tmp_path)
    (tmp_path / 'link.md').symlink_to(tmp_path / 'README.md')
    with pytest.raises(ValueError, match='symlink_not_allowed'):
        check(tmp_path)
