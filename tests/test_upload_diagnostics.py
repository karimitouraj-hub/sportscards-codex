"""Failed-upload diagnostics use synthetic bytes and isolated test storage only."""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess

import pytest

from server.app import create_app


@pytest.fixture
def diagnostic_client(tmp_path):
    assert not str(tmp_path).startswith('/data/sportscards/')
    app = create_app(tmp_path)
    client = app.test_client()
    client.environ_base['HTTP_X_SPORTSCARDS_TOKEN'] = client.get('/api/state').json['token']
    return app, client


def reject(client, content, filename='synthetic-failure.heif'):
    response = client.post('/api/photos', data=content, headers={
        'X-Filename': filename, 'Content-Type': 'application/octet-stream'})
    assert response.status_code == 422, response.json
    return response


def assert_no_inventory(app, client):
    state = client.get('/api/state').json
    for kind in ('cards', 'photos', 'observations', 'jobs'):
        assert state[kind] == []
    with app.store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM hashes').fetchone()[0] == 0
    for name in ('staging', 'previews', 'originals'):
        assert list((app.store.root / name).iterdir()) == []


def test_default_does_not_retain_failed_original(diagnostic_client, monkeypatch):
    monkeypatch.delenv('SPORTSCARDS_UPLOAD_DIAGNOSTICS', raising=False)
    app, client = diagnostic_client
    response = reject(client, b'synthetic invalid HEIF content; default diagnostics disabled')
    assert response.json == {'error': 'The decoder could not read this photo.'}
    assert not (app.store.root / 'failed-uploads').exists()
    assert_no_inventory(app, client)


def test_opt_in_preserves_three_unique_originals_and_deduplicates(diagnostic_client, monkeypatch):
    monkeypatch.setenv('SPORTSCARDS_UPLOAD_DIAGNOSTICS', '1')
    app, client = diagnostic_client
    samples = [f'SYNTHETIC invalid image sample {index}'.encode() for index in range(4)]
    first_response = reject(client, samples[0])
    first_digest = hashlib.sha256(samples[0]).hexdigest()
    assert f'Diagnostic ID: {first_digest[:12]}.' in first_response.json['error']
    reject(client, samples[0], 'same-bytes-renamed.heif')
    reject(client, samples[1])
    reject(client, samples[2])
    reject(client, samples[3])
    reject(client, samples[0])

    directory = app.store.root / 'failed-uploads'
    expected = {hashlib.sha256(sample).hexdigest(): sample for sample in samples[:3]}
    assert {file.stem for file in directory.glob('*.bin')} == set(expected)
    assert {file.stem for file in directory.glob('*.json')} == set(expected)
    assert len(list(directory.iterdir())) == 6
    for digest, original_bytes in expected.items():
        original, sidecar = directory / (digest + '.bin'), directory / (digest + '.json')
        assert original.read_bytes() == original_bytes
        assert hashlib.sha256(original.read_bytes()).hexdigest() == digest
        report = json.loads(sidecar.read_text())
        assert report['sha256'] == digest
        assert report['id'] == digest[:12]
        assert report['bytes'] == len(original_bytes)
        assert report['returncode'] == 1
        assert isinstance(report['stderr'], str)
        decoder_error = json.loads(report['stdout'])
        assert decoder_error['error_type'] == 'UnidentifiedImageError'
        assert decoder_error['detail']
        if os.name == 'posix':
            assert stat.S_IMODE(original.stat().st_mode) == 0o600
            assert stat.S_IMODE(sidecar.stat().st_mode) == 0o600
    if os.name == 'posix':
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert_no_inventory(app, client)


def test_diagnostic_output_is_bounded_and_not_exposed(diagnostic_client, monkeypatch):
    monkeypatch.setenv('SPORTSCARDS_UPLOAD_DIAGNOSTICS', '1')
    app, client = diagnostic_client
    monkeypatch.setattr('server.app.subprocess.run', lambda *args, **kwargs:
                        subprocess.CompletedProcess(args[0], 17, 'private-stdout-' * 1000, 'private-stderr-' * 1000))
    response = reject(client, b'synthetic failed subprocess output')
    report = json.loads(next((app.store.root / 'failed-uploads').glob('*.json')).read_text())
    assert report['returncode'] == 17
    assert len(report['stdout']) == 8000
    assert len(report['stderr']) == 8000
    assert 'private-stdout' not in response.get_data(as_text=True)
    assert 'private-stderr' not in response.get_data(as_text=True)
    assert_no_inventory(app, client)


def test_timeout_retains_original_without_inventory_or_partial_preview(diagnostic_client, monkeypatch):
    monkeypatch.setenv('SPORTSCARDS_UPLOAD_DIAGNOSTICS', '1')
    app, client = diagnostic_client
    content = b'synthetic timeout input'

    def timeout(args, **kwargs):
        Path(args[4]).write_bytes(b'synthetic partial preview')
        raise subprocess.TimeoutExpired(args, 35)

    monkeypatch.setattr('server.app.subprocess.run', timeout)
    response = reject(client, content)
    assert 'timed out' in response.json['error']
    digest = hashlib.sha256(content).hexdigest()
    directory = app.store.root / 'failed-uploads'
    assert (directory / (digest + '.bin')).read_bytes() == content
    report = json.loads((directory / (digest + '.json')).read_text())
    assert report['error_type'] == 'TimeoutExpired'
    assert report['timeout_seconds'] == 35
    assert_no_inventory(app, client)
