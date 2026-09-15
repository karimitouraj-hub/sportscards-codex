"""Install and start a local SportsCards instance. Requires Python and Node.js."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--setup', action='store_true', help='Install dependencies and rebuild the dashboard.')
    parser.add_argument('--setup-only', action='store_true', help='Install and build, then exit.')
    parser.add_argument('--data-dir', type=Path, help='Private storage directory. Default: ~/.sportscards')
    parser.add_argument('--port', type=int, default=8097, help='Local dashboard port. Default: 8097')
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        parser.error('Use Python 3.11 or later.')
    if not 1 <= args.port <= 65535:
        parser.error('Use a port from 1 through 65535.')
    environment = ROOT / '.venv'
    python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    install = args.setup or args.setup_only or not python.exists()
    if not python.exists():
        venv.EnvBuilder(with_pip=True).create(environment)
    if install:
        subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(ROOT / 'requirements-mcp.txt')], cwd=ROOT, check=True)
    if install or not (ROOT / 'dist/index.html').exists():
        npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
        if not npm:
            parser.error('Install Node.js with npm, then run this command again.')
        subprocess.run([npm, 'ci'], cwd=ROOT, check=True)
        subprocess.run([npm, 'run', 'build'], cwd=ROOT, check=True)
    if args.setup_only:
        print('Setup complete. Run python scripts/start.py to open the local server.')
        return
    env = os.environ.copy()
    env['SPORTSCARDS_HOST'] = '127.0.0.1'
    env['SPORTSCARDS_PORT'] = str(args.port)
    if args.data_dir:
        env['SPORTSCARDS_DATA'] = str(args.data_dir.expanduser().resolve())
    print(f'SportsCards: http://127.0.0.1:{args.port}', flush=True)
    print('Press Ctrl+C to stop the server.', flush=True)
    try:
        subprocess.run([str(python), '-m', 'server.app'], cwd=ROOT, env=env, check=True)
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
