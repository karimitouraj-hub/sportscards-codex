"""Install SportsCards, configure its Codex workspace, and test the MCP connection."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
BEGIN = '# BEGIN SportsCards managed MCP\n'
END = '# END SportsCards managed MCP\n'


def server_config(root, data_dir=None):
    root = Path(root).resolve()
    python = root / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    args = ['-m', 'server.mcp']
    if data_dir is not None:
        args += ['--data', Path(data_dir).expanduser().resolve().as_posix()]
    return dict(command=python.as_posix(), args=args, cwd=root.as_posix(),
                startup_timeout_sec=30, tool_timeout_sec=120)


def configured_data(selected):
    args = (selected or {}).get('args', [])
    return args[3] if len(args) == 4 and args[:3] == ['-m', 'server.mcp', '--data'] else None


def configure(root, data_dir=None):
    """Preserve unrelated TOML and refuse to replace an unmanaged SportsCards server."""
    path = Path(root) / '.codex' / 'config.toml'
    original = path.read_text(encoding='utf-8') if path.exists() else ''
    parsed = tomllib.loads(original)
    existing = parsed.get('mcp_servers', {}).get('sportscards')
    expected = server_config(root, data_dir if data_dir is not None else configured_data(existing))
    if existing == expected:
        return path
    if original.count(BEGIN) != original.count(END) or original.count(BEGIN) > 1:
        raise ValueError('The managed configuration markers are invalid. Review .codex/config.toml.')
    if BEGIN in original:
        before, rest = original.split(BEGIN)
        _, after = rest.split(END)
        # Do not remove any unrelated setting inside an edited managed section.
        managed = rest.split(END)[0]
        managed_data = tomllib.loads(managed)
        if set(managed_data) != {'mcp_servers'} or set(managed_data['mcp_servers']) != {'sportscards'}:
            raise ValueError('The managed block contains other settings. Review .codex/config.toml.')
        remaining = before + after
    elif existing is not None:
        raise ValueError('An existing SportsCards configuration needs manual review. See docs/INSTALL.md.')
    else:
        remaining = original
    block = BEGIN + '[mcp_servers.sportscards]\n'
    block += ''.join(f'{key} = {json.dumps(value, ensure_ascii=False)}\n' for key, value in expected.items())
    updated = remaining.rstrip() + ('\n\n' if remaining.strip() else '') + block + END
    if tomllib.loads(updated).get('mcp_servers', {}).get('sportscards') != expected:
        raise ValueError('The generated configuration did not pass validation.')
    path.parent.mkdir(parents=True, exist_ok=True)
    if original:
        with tempfile.NamedTemporaryFile(prefix='config-', suffix='.toml.bak', dir=path.parent, delete=False) as backup:
            backup.write(original.encode('utf-8'))
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temporary.write(updated.encode('utf-8'))
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, path)
    return path


async def probe(root):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    import anyio

    config = tomllib.loads((Path(root) / '.codex/config.toml').read_text(encoding='utf-8'))
    selected = config['mcp_servers']['sportscards']
    if selected != server_config(root, configured_data(selected)):
        raise ValueError('The project MCP settings differ from this checkout. Run setup or use the manual guide.')
    if not (Path(root) / 'dist/index.html').is_file():
        raise ValueError('The dashboard is not built. Run python scripts/setup.py.')
    # Validate the configured command against temporary data, never the real collection.
    with tempfile.TemporaryDirectory(prefix='sportscards-setup-') as data:
        params = StdioServerParameters(command=selected['command'],
            args=['-m', 'server.mcp', '--data', data], cwd=selected['cwd'])
        with anyio.fail_after(45):
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    initialized = await session.initialize()
                    listed = await session.list_tools()
                    result = await session.call_tool('status', {})
                    if initialized.serverInfo.name != 'SportsCards' or result.isError:
                        raise ValueError('The SportsCards MCP connection failed.')
                    state = result.structuredContent
                    if not state or state.get('counts') or state.get('ebay_connected') is not False:
                        raise ValueError('The temporary collection status was unexpected.')
                    print(f'Verified: MCP initialization, {len(listed.tools)} tools, and empty collection status.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-install', action='store_true', help='Configure and verify installed dependencies.')
    parser.add_argument('--check', action='store_true', help='Verify the existing setup without changing configuration.')
    parser.add_argument('--data-dir', type=Path, help='Set the MCP collection directory. Repeat setup preserves this selection.')
    parser.add_argument('--probe', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.probe:
        asyncio.run(probe(ROOT))
        return
    if not args.check:
        if not args.skip_install:
            subprocess.run([sys.executable, str(ROOT / 'scripts/start.py'), '--setup-only'], cwd=ROOT, check=True)
        path = configure(ROOT, args.data_dir)
        print(f'Configured: {path}', flush=True)
    python = server_config(ROOT)['command']
    if not Path(python).is_file():
        parser.error('Dependencies are missing. Run python scripts/setup.py.')
    subprocess.run([python, str(Path(__file__).resolve()), '--probe'], cwd=ROOT, check=True)
    print('Open this repository in Codex. Trust it only after reviewing its contents.')
    print('Start a new conversation and ask: Use $sportscards and check status.')
    print('Start the dashboard with: python scripts/start.py')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        raise SystemExit(f'Setup failed: {error}') from None
