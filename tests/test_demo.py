"""The walkthrough must use synthetic data in a new isolated directory."""
import importlib.util
import io
import json
from pathlib import Path
import socket
import zipfile

import pytest
from PIL import Image

from server.app import create_app
from server.pricing_engine import simulate


spec = importlib.util.spec_from_file_location('sportscards_demo', Path(__file__).resolve().parents[1] / 'scripts/demo.py')
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


@pytest.fixture(scope='module')
def generated(tmp_path_factory):
    target = tmp_path_factory.mktemp('synthetic-walkthrough') / 'demo'
    # The generator must not use the network, including for its source links.
    with pytest.MonkeyPatch.context() as patch:
        def no_network(*args, **kwargs):
            raise AssertionError('The synthetic demo must not use the network.')
        patch.setattr(socket, 'create_connection', no_network)
        patch.setattr(socket.socket, 'connect', no_network)
        patch.chdir(target.parent)
        summary = demo.generate(target)
        assert Path.cwd() == target.parent
    return target, summary, create_app(target).test_client()


def test_demo_contains_reviewed_cards_and_separate_evidence(generated):
    target, summary, client = generated
    state = client.get('/api/state').json
    assert summary['synthetic'] is True
    assert len(state['cards']) == 2 and len(state['photos']) == 4
    assert all(photo['review_complete'] for photo in state['photos'])
    assert all(job['state'] == 'done' for job in state['jobs'])
    confirmed = [item for item in state['observations'] if item['status'] == 'confirmed']
    assert len(confirmed) == 4
    assert {item['side'] for item in confirmed} == {'front', 'back'}
    assert len(state['purchases']) == len(state['allocations']) == len(state['listings']) == 1
    assert len(state['comparables']) == 3
    for photo in state['photos']:
        with Image.open(io.BytesIO(client.get('/media/original/' + photo['id']).data)) as image:
            image.load()
            assert image.size == (900, 1200)
    assert all('example.com/synthetic-demo/' in item['source_url']
               for item in state['comparables'] + state['listings'])
    assert 'SYNTHETIC DEMO' in (target / 'SYNTHETIC-DEMO.txt').read_text()
    assert json.loads((target / 'demo-summary.json').read_text()) == summary


def test_unknown_cost_and_value_remain_unknown(generated):
    _, summary, client = generated
    report = client.get('/api/pricing-engine').json
    rows = {row['card_id']: row for row in report['rows']}
    priced = rows[summary['card_ids']['Demo Player One']]
    unknown = rows[summary['card_ids']['Demo Player Two']]
    assert priced['purchase_cost_cents'] == 1600
    assert priced['sold_value_cents'] == priced['scenario_price_cents'] == 3200
    assert priced['active_ask_cents'] == 5000
    assert priced['listing_scenario_cents'] == 4000
    assert priced['price_source'] == 'sold'
    assert unknown['price_source'] == 'unknown'
    assert unknown['purchase_cost_cents'] is None
    assert unknown['scenario_price_cents'] is None and unknown['scenario_profit_cents'] is None
    assert report['summary']['modeled_cards'] == report['summary']['unknown_cards'] == 1


def test_ready_draft_package_and_saved_simulation(generated):
    _, summary, client = generated
    report = client.get('/api/listing-prep').json
    assert report['summary'] == {'drafts': 1, 'ready': 1, 'needs_review': 0}
    draft = report['drafts'][0]
    assert draft['card_id'] == summary['draft_card_id']
    assert draft['ready'] and len(draft['photos']) == 2
    assert 'SYNTHETIC DEMO' in draft['title']
    package = client.get('/api/listing-prep/package')
    assert package.status_code == 200
    with zipfile.ZipFile(io.BytesIO(package.data)) as archive:
        texts = [name for name in archive.namelist() if name.endswith('listing.txt')]
        assert len(texts) == 1
        assert 'Do not publish' in archive.read(texts[0]).decode()
        assert len([name for name in archive.namelist() if name.endswith('.jpg')]) == 2
    runs = client.get('/api/pricing-engine/runs').json['runs']
    assert len(runs) == 1 and runs[0]['id'] == summary['simulation_run_id']
    run = client.get('/api/pricing-engine/runs/' + runs[0]['id']).json
    assert run['options']['trials'] == 10000 and run['seed'] == 42
    assert run['summary']['unknown_cards'] == 1
    assert simulate(run['input_report'], run['options']) == run['result']


def test_existing_destination_is_untouched(tmp_path):
    destination = tmp_path / 'existing'
    destination.mkdir()
    marker = destination / 'keep.txt'
    marker.write_bytes(b'unchanged')
    with pytest.raises(ValueError, match='already exists'):
        demo.generate(destination)
    assert list(destination.iterdir()) == [marker]
    assert marker.read_bytes() == b'unchanged'


def test_refuse_repository_and_real_storage_paths(tmp_path, monkeypatch):
    repo = tmp_path / 'repository'
    home = tmp_path / 'home'
    configured = tmp_path / 'real-collection'
    monkeypatch.setattr(demo, 'ROOT', repo)
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    monkeypatch.setenv('SPORTSCARDS_DATA', str(configured))
    for path in (repo / 'demo', home / '.sportscards', home / '.sportscards/demo', configured / 'demo'):
        with pytest.raises(ValueError, match='outside'):
            demo.validate_destination(path)
        assert not path.exists()
    existing = tmp_path / 'other-collection'
    existing.mkdir()
    (existing / 'collection.sqlite3').touch()
    with pytest.raises(ValueError, match='existing collection'):
        demo.validate_destination(existing / 'demo')


def test_destination_is_required():
    with pytest.raises(ValueError, match='destination'):
        demo.generate(None)
    with pytest.raises(SystemExit) as error:
        demo.main([])
    assert error.value.code == 2
