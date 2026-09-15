"""Installer settings must preserve unrelated configuration and reject conflicts."""
import importlib.util
from pathlib import Path
import tomllib

import pytest

spec = importlib.util.spec_from_file_location('sportscards_setup', Path(__file__).resolve().parents[1] / 'scripts/setup.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def test_configuration_preserves_settings_and_is_idempotent(tmp_path):
    root = tmp_path / 'cards with spaces'
    (root / '.codex').mkdir(parents=True)
    config = root / '.codex/config.toml'
    original = '# User setting\nmodel = "test-model"\n[mcp_servers.other]\ncommand = "other-command"\n'
    config.write_text(original)
    setup.configure(root)
    parsed = tomllib.loads(config.read_text())
    assert parsed['model'] == 'test-model'
    assert parsed['mcp_servers']['other']['command'] == 'other-command'
    assert parsed['mcp_servers']['sportscards'] == setup.server_config(root)
    assert list(config.parent.glob('*.bak'))[0].read_text() == original
    first = config.read_bytes()
    setup.configure(root)
    assert config.read_bytes() == first
    assert len(list(config.parent.glob('*.bak'))) == 1


@pytest.mark.parametrize('original', ['[mcp_servers.sportscards]\ncommand="keep-me"\n', 'invalid = [', setup.BEGIN])
def test_configuration_conflict_does_not_change_file(tmp_path, original):
    config = tmp_path / '.codex/config.toml'
    config.parent.mkdir()
    config.write_text(original)
    with pytest.raises(ValueError):
        setup.configure(tmp_path)
    assert config.read_text() == original


def test_configuration_updates_only_managed_block(tmp_path):
    config = setup.configure(tmp_path)
    first = config.read_text().replace('server.mcp', 'server.old_mcp')
    config.write_text(first + '\n[user_section]\nkeep = true\n')
    setup.configure(tmp_path)
    parsed = tomllib.loads(config.read_text())
    assert parsed['user_section']['keep'] is True
    assert parsed['mcp_servers']['sportscards']['args'] == ['-m', 'server.mcp']


def test_repeat_setup_preserves_custom_collection_and_accepts_explicit_change(tmp_path):
    first_data = tmp_path / 'private cards'
    second_data = tmp_path / 'different private cards'
    config = setup.configure(tmp_path, first_data)
    setup.configure(tmp_path)
    selected = tomllib.loads(config.read_text())['mcp_servers']['sportscards']
    assert selected == setup.server_config(tmp_path, first_data)
    assert not first_data.exists()
    setup.configure(tmp_path, second_data)
    selected = tomllib.loads(config.read_text())['mcp_servers']['sportscards']
    assert selected == setup.server_config(tmp_path, second_data)
    assert not second_data.exists()
