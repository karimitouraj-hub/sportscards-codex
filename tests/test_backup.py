"""A collection backup includes prepared drafts without copying the request token."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys


def test_backup_keeps_listing_manifest_and_excludes_request_token(tmp_path):
    source = tmp_path/'collection'
    source.mkdir()
    with sqlite3.connect(source/'collection.sqlite3') as db:
        db.execute('CREATE TABLE records(kind TEXT, data TEXT)')
    (source/'session-token').write_text('fixture-token-do-not-copy')
    prep = source/'listing-prep'
    prep.mkdir()
    content = b'{"batch_id":"fixture","drafts":[]}'
    (prep/'current.json').write_bytes(content)
    destination = tmp_path/'backup'
    script = Path(__file__).resolve().parents[1]/'scripts'/'backup.py'
    result = subprocess.run([sys.executable, str(script), '--source', str(source), '--destination', str(destination)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (destination/'listing-prep'/'current.json').read_bytes() == content
    manifest = json.loads((destination/'manifest.json').read_text())
    assert manifest['listing_manifest_sha256'] == hashlib.sha256(content).hexdigest()
    assert not (destination/'session-token').exists()
    assert json.loads(result.stdout)['listing_manifest_copied'] is True
