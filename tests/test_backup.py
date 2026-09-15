"""A collection backup includes prepared drafts without copying the request token."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from PIL import Image
import pytest

from server.store import Store


SCRIPT = Path(__file__).resolve().parents[1]/'scripts'/'backup.py'


def run_backup(*args, env=None):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                          capture_output=True, text=True, env=env)


def tree_hashes(root):
    # SQLite may create WAL coordination files while opening a read-only connection.
    # The database, referenced assets, and other durable source files must not change.
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob('*') if path.is_file()
            and not path.name.endswith(('.sqlite3-wal', '.sqlite3-shm'))}


def synthetic_collection(root):
    store = Store(root)
    for name in ('originals/synthetic.png', 'previews/synthetic.jpg', 'crops/synthetic.jpg'):
        Image.new('RGB', (600, 900), '#145e5a').save(root / name)
    with store.connect() as db:
        store.put('photo', {'id': 'photo-1', 'original': 'originals/synthetic.png',
                           'preview': 'previews/synthetic.jpg', 'review_complete': True}, db)
        store.put('observation', {'id': 'observation-1', 'photo_id': 'photo-1',
                                 'card_id': 'card-1', 'crop': 'crops/synthetic.jpg'}, db)
        store.put('card', {'id': 'card-1', 'player': 'Synthetic Player'}, db)
        store.put('purchase', {'id': 'purchase-1', 'title': 'Synthetic receipt', 'total_cents': 1234}, db)
        store.put('simulation_run', {'id': 'run-1', 'result': {'synthetic': True}}, db)
        store.audit(db, 'synthetic-review', 'card-1', {})
    (root / 'listing-prep').mkdir()
    (root / 'listing-prep/current.json').write_text('{"batch_id":"synthetic","drafts":[]}', encoding='utf-8')
    (root / 'listing-prep/archived.json').write_text('{"drafts":[]}', encoding='utf-8')
    (root / 'originals/unreferenced.txt').write_text('Deliberately outside the backup scope.')
    (root / 'session-token').write_text('synthetic-token-do-not-copy')
    return store


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


def test_backup_restore_round_trip_preserves_records_and_hashes(tmp_path):
    source, destination, restored = (tmp_path / name for name in ('collection', 'backup', 'restored'))
    store = synthetic_collection(source)
    before = tree_hashes(source)
    result = run_backup('--source', source, '--destination', destination)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['verified_files'] == 5
    assert tree_hashes(source) == before
    backup_hashes = tree_hashes(destination)

    result = run_backup('--verify', destination)
    assert result.returncode == 0, result.stderr
    assert tree_hashes(destination) == backup_hashes
    result = run_backup('--restore', destination, '--destination', restored)
    assert result.returncode == 0, result.stderr
    assert tree_hashes(restored) == backup_hashes
    assert tree_hashes(source) == before
    assert not (restored / 'session-token').exists()
    assert not (restored / 'listing-prep/archived.json').exists()
    assert not (restored / 'originals/unreferenced.txt').exists()
    manifest = json.loads((restored / 'manifest.json').read_text())
    for name, evidence in manifest['files'].items():
        assert hashlib.sha256((restored / name).read_bytes()).hexdigest() == evidence['sha256']
    with store.connect() as src, sqlite3.connect(restored / 'collection.sqlite3') as dst:
        for table in ('records', 'audit', 'hashes', 'jobs'):
            assert [tuple(row) for row in src.execute(f'SELECT * FROM {table}')] == dst.execute(f'SELECT * FROM {table}').fetchall()


@pytest.mark.parametrize('source_exists', [False, True])
def test_missing_source_never_creates_database_or_destination(tmp_path, source_exists):
    source, destination = tmp_path / 'missing', tmp_path / 'backup'
    if source_exists:
        source.mkdir()
    result = run_backup('--source', source, '--destination', destination)
    assert result.returncode != 0
    assert not (source / 'collection.sqlite3').exists()
    assert not destination.exists()


def test_backup_uses_configured_private_data_directory(tmp_path):
    source, destination = tmp_path / 'collection', tmp_path / 'backup'
    synthetic_collection(source)
    result = run_backup('--destination', destination, env={**os.environ, 'SPORTSCARDS_DATA': str(source)})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['records_with_files'] == 2


@pytest.mark.parametrize('location', ['source', 'nested', 'existing'])
def test_backup_refuses_unsafe_or_existing_destination(tmp_path, location):
    source = tmp_path / 'collection'
    synthetic_collection(source)
    destination = {'source': source, 'nested': source / 'backup', 'existing': tmp_path / 'existing'}[location]
    if location == 'existing':
        destination.mkdir()
        (destination / 'keep.txt').write_text('Keep this file.')
    before = tree_hashes(tmp_path)
    result = run_backup('--source', source, '--destination', destination)
    assert result.returncode != 0
    assert tree_hashes(tmp_path) == before


@pytest.mark.parametrize('name', ['originals/missing.png', '../outside.png', 'session-token'])
def test_invalid_media_leaves_no_partial_destination(tmp_path, name):
    source, destination = tmp_path / 'collection', tmp_path / 'backup'
    store = synthetic_collection(source)
    with store.connect() as db:
        photo = store.get('photo', 'photo-1', db)
        photo['original'] = name
        store.put('photo', photo, db)
    before = tree_hashes(tmp_path)
    result = run_backup('--source', source, '--destination', destination)
    assert result.returncode != 0
    assert not destination.exists()
    assert not list(tmp_path.glob('.backup-*'))
    assert tree_hashes(tmp_path) == before


def test_damaged_backup_cannot_restore_or_replace_collection(tmp_path):
    source, destination, restored = (tmp_path / name for name in ('collection', 'backup', 'restored'))
    synthetic_collection(source)
    assert run_backup('--source', source, '--destination', destination).returncode == 0
    before = tree_hashes(source)
    crop = destination / 'crops/synthetic.jpg'
    content = crop.read_bytes()
    crop.write_bytes(bytes([content[0] ^ 1]) + content[1:])
    assert run_backup('--verify', destination).returncode != 0
    result = run_backup('--restore', destination, '--destination', restored)
    assert result.returncode != 0
    assert not restored.exists()
    assert tree_hashes(source) == before


def test_restore_refuses_existing_destination_and_legacy_manifest(tmp_path):
    source, destination = tmp_path / 'collection', tmp_path / 'backup'
    synthetic_collection(source)
    assert run_backup('--source', source, '--destination', destination).returncode == 0
    before = tree_hashes(source)
    result = run_backup('--restore', destination, '--destination', source)
    assert result.returncode != 0
    assert tree_hashes(source) == before
    manifest_path = destination / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['schema_version'] = 2
    manifest_path.write_text(json.dumps(manifest))
    result = run_backup('--verify', destination)
    assert result.returncode != 0
    assert 'version 3 backup' in result.stderr


def test_backup_includes_committed_wal_records(tmp_path):
    source, destination = tmp_path / 'collection', tmp_path / 'backup'
    synthetic_collection(source)
    with sqlite3.connect(source / 'collection.sqlite3') as live:
        live.execute('PRAGMA wal_autocheckpoint=0')
        live.execute('INSERT INTO records VALUES (?, ?, ?)',
                     ('purchase', 'wal-purchase', json.dumps({'id': 'wal-purchase', 'total_cents': 678})))
        live.commit()
        assert (source / 'collection.sqlite3-wal').stat().st_size > 0
        result = run_backup('--source', source, '--destination', destination)
        assert result.returncode == 0, result.stderr
        with sqlite3.connect(destination / 'collection.sqlite3') as restored:
            row = restored.execute('SELECT data FROM records WHERE id=?', ('wal-purchase',)).fetchone()
        assert json.loads(row[0])['total_cents'] == 678


def test_backup_rejects_media_symlink_outside_collection(tmp_path):
    source, destination = tmp_path / 'collection', tmp_path / 'backup'
    store = synthetic_collection(source)
    outside = tmp_path / 'outside.png'
    outside.write_bytes(b'Outside the private collection.')
    link = source / 'originals/link.png'
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip('This account cannot create symbolic links.')
    with store.connect() as db:
        photo = store.get('photo', 'photo-1', db)
        photo['original'] = 'originals/link.png'
        store.put('photo', photo, db)
    result = run_backup('--source', source, '--destination', destination)
    assert result.returncode != 0
    assert not destination.exists()
    assert outside.read_bytes() == b'Outside the private collection.'


def test_verify_and_restore_reject_omitted_referenced_media(tmp_path):
    source, destination, restored = (tmp_path / name for name in ('collection', 'backup', 'restored'))
    synthetic_collection(source)
    assert run_backup('--source', source, '--destination', destination).returncode == 0
    manifest_path = destination / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    del manifest['files']['crops/synthetic.jpg']
    manifest_path.write_text(json.dumps(manifest))
    result = run_backup('--verify', destination)
    assert result.returncode != 0
    assert 'database-referenced files' in result.stderr
    assert run_backup('--restore', destination, '--destination', restored).returncode != 0
    assert not restored.exists()


@pytest.mark.parametrize('change', ['missing_entry', 'wrong_hash', 'missing_hash'])
def test_verify_requires_consistent_listing_manifest(tmp_path, change):
    source, destination = tmp_path / 'collection', tmp_path / 'backup'
    synthetic_collection(source)
    assert run_backup('--source', source, '--destination', destination).returncode == 0
    manifest_path = destination / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    if change == 'missing_entry':
        del manifest['files']['listing-prep/current.json']
    elif change == 'wrong_hash':
        manifest['listing_manifest_sha256'] = '0' * 64
    else:
        del manifest['listing_manifest_sha256']
    manifest_path.write_text(json.dumps(manifest))
    assert run_backup('--verify', destination).returncode != 0
