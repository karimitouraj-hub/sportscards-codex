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


@pytest.mark.parametrize('manual', [
    'enabled = false\n',
    'enabled_tools = ["status"]\n',
    'unknown_future_setting = "preserve-me"\n',
    '[mcp_servers.sportscards.env]\nSPORTSCARDS_DATA = "custom-private-cards"\n',
])
def test_manual_server_fields_are_never_discarded(tmp_path, manual):
    config = setup.configure(tmp_path)
    modified = config.read_text().replace(setup.END, manual + setup.END)
    config.write_bytes(modified.replace('\n', '\r\n').encode('utf-8'))
    original = config.read_bytes()
    with pytest.raises(ValueError, match='manual settings'):
        setup.configure(tmp_path)
    assert config.read_bytes() == original
    assert not list(config.parent.glob('*.bak'))


def test_setting_after_marker_cannot_move_to_another_server(tmp_path):
    config = tmp_path / '.codex/config.toml'
    config.parent.mkdir()
    config.write_text('[mcp_servers.other]\ncommand = "other-command"\n')
    setup.configure(tmp_path)
    config.write_text(config.read_text() + 'enabled = false\n')
    original = config.read_bytes()
    before = tomllib.loads(original.decode())
    assert before['mcp_servers']['sportscards']['enabled'] is False
    assert 'enabled' not in before['mcp_servers']['other']
    with pytest.raises(ValueError):
        setup.configure(tmp_path)
    assert config.read_bytes() == original
    assert tomllib.loads(config.read_text()) == before


def test_supported_setting_outside_marker_requires_review_even_when_values_match(tmp_path):
    config = setup.configure(tmp_path)
    modified = config.read_text().replace('tool_timeout_sec = 120\n', '')
    config.write_text(modified + 'tool_timeout_sec = 120\n')
    original = config.read_bytes()
    assert tomllib.loads(config.read_text())['mcp_servers']['sportscards'] == setup.server_config(tmp_path)
    with pytest.raises(ValueError, match='outside the managed block'):
        setup.configure(tmp_path)
    assert config.read_bytes() == original


@pytest.mark.parametrize('arguments', [
    ['-m', 'server.mcp', '--data=custom-private-cards'],
    ['-m', 'server.mcp', '--data', 'custom-private-cards', '--custom-option'],
    ['server/mcp.py', '--data', 'custom-private-cards'],
])
def test_manual_argument_forms_do_not_reset_the_data_directory(tmp_path, arguments):
    import json
    config = setup.configure(tmp_path)
    config.write_text(config.read_text().replace('args = ["-m", "server.mcp"]', 'args = ' + json.dumps(arguments)))
    original = config.read_bytes()
    with pytest.raises(ValueError, match='arguments contain manual changes'):
        setup.configure(tmp_path)
    assert config.read_bytes() == original


def test_managed_module_repair_preserves_custom_data_and_backup_bytes(tmp_path):
    data = tmp_path / 'private cards'
    config = setup.configure(tmp_path, data)
    modified = config.read_text().replace('server.mcp', 'server.old_mcp')
    original = modified.replace('\n', '\r\n').encode('utf-8')
    config.write_bytes(original)
    setup.configure(tmp_path)
    assert tomllib.loads(config.read_text())['mcp_servers']['sportscards'] == setup.server_config(tmp_path, data)
    assert list(config.parent.glob('*.bak'))[0].read_bytes() == original


def test_dashboard_command_uses_the_preserved_collection(tmp_path):
    data = tmp_path / 'private cards'
    selected = setup.server_config(tmp_path, data)
    command = setup.dashboard_command(selected)
    assert '--data-dir' in command
    assert data.as_posix() in command
    assert setup.dashboard_command(setup.server_config(tmp_path)) == 'python scripts/start.py'
