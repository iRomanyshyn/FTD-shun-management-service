import json

import pytest

from ftd_shun_manager import __version__
from ftd_shun_manager.build_info import load_build, source_build


def inputs(tmp_path):
    (tmp_path / 'pyproject.toml').write_text('[project]\nname="fixture"\n')
    for directory, name in [('src', 'fixture.py'), ('templates', 'page.html'), ('static', 'app.css')]:
        (tmp_path / directory).mkdir()
        (tmp_path / directory / name).write_text('public input')
    return tmp_path


def test_build_is_deterministic_and_ignores_private_and_git_inputs(tmp_path):
    root = inputs(tmp_path)
    expected = source_build(root)
    (root / '.env').write_text('private environment')
    (root / '.git').mkdir()
    (root / '.git' / 'HEAD').write_text('private source metadata')
    (root / 'state.db').write_text('private database')
    assert source_build(root) == expected
    assert expected['version'] == __version__ and len(expected['source_id']) == 12
    (root / 'static' / 'app.css').write_text('changed public input')
    assert source_build(root)['source_id'] != expected['source_id']


def test_checkout_is_unlabelled_and_mismatched_metadata_refused(tmp_path):
    assert load_build(tmp_path) is None
    value = {'version': __version__, 'source_sha256': 'a' * 64, 'source_id': 'a' * 12}
    (tmp_path / 'build-info.json').write_text(json.dumps(value))
    assert load_build(tmp_path) == value
    value['version'] = '0.0.0'
    (tmp_path / 'build-info.json').write_text(json.dumps(value))
    with pytest.raises(ValueError): load_build(tmp_path)


@pytest.mark.parametrize('target', ['static', 'src/secret.py'])
def test_build_never_follows_symlinks_to_unrelated_inputs(tmp_path, target):
    root = inputs(tmp_path)
    if target == 'static':
        (root / 'static' / 'app.css').unlink()
        (root / 'static').rmdir()
        (root / 'static').symlink_to(root / 'templates', target_is_directory=True)
    else:
        (root / target).symlink_to(root / '.env')
    with pytest.raises(ValueError): source_build(root)
