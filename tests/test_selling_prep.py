"""Synthetic listing drafts only. No production collection records."""
import io
import hashlib
import json
import zipfile

from flask import Flask
from PIL import Image
import pytest

from server.analysis import signature
from server.selling_prep import register_listing_prep
from server.store import Store

CARD_ID = 'a' * 32
FRONT_ID = 'b' * 32
BACK_ID = 'c' * 32
PHOTO_ID = 'd' * 32
OTHER_ID = 'e' * 32


@pytest.fixture
def prepared(tmp_path):
    store = Store(tmp_path)
    card = dict(id=CARD_ID, player='Synthetic Player', year='2026', set='Synthetic Set', variant='Base', condition='Raw')
    with store.connect() as db:
        store.put('card', card, db)
        store.put('photo', dict(id=PHOTO_ID, review_complete=True), db)
        for observation_id, side, color in ((FRONT_ID, 'front', 'red'), (BACK_ID, 'back', 'blue')):
            Image.new('RGB', (600, 900), color).save(tmp_path / 'crops' / f'{observation_id}.jpg')
            store.put('observation', dict(id=observation_id, card_id=CARD_ID, photo_id=PHOTO_ID,
                                         side=side, status='confirmed', crop=f'crops/{observation_id}.jpg'), db)
    manifest = dict(batch_id='synthetic-batch', created_at='2026-09-14T00:00:00Z', drafts=[dict(
        card_id=CARD_ID, title='Synthetic card title', description='Synthetic public card description.',
        condition='Ungraded. See the front and back photos.', specifics={'Player': 'Synthetic Player'},
        price_cents=1999, shipping_cents=550, minimum_offer_cents=1500,
        pricing_note='PRIVATE PRICE NOTE', review_notes=['PRIVATE REVIEW NOTE'],
        purchase_cost_cents=12345, seller_analysis={'purchase_cost_cents': 12345},
        identity_signature=signature(card), photo_observation_ids=[FRONT_ID, BACK_ID],
        photo_sha256={id: hashlib.sha256((tmp_path / 'crops' / f'{id}.jpg').read_bytes()).hexdigest() for id in (FRONT_ID, BACK_ID)}, status='ready')])
    directory = tmp_path / 'listing-prep'
    directory.mkdir()
    path = directory / 'current.json'
    path.write_text(json.dumps(manifest), encoding='utf-8')
    app = Flask(__name__)
    register_listing_prep(app, store)
    return app.test_client(), store, manifest, path


def save(manifest, path):
    path.write_text(json.dumps(manifest), encoding='utf-8')


def test_ready_draft_and_package_use_linked_photos_and_public_fields(prepared):
    client, store, manifest, path = prepared
    before = path.read_bytes()
    result = client.get('/api/listing-prep')
    assert result.status_code == 200
    assert result.json['summary'] == dict(drafts=1, ready=1, needs_review=0)
    draft = result.json['drafts'][0]
    assert draft['listing_format'] == 'fixed_price' and draft['duration_days'] is None
    assert [photo['side'] for photo in draft['photos']] == ['front', 'back']
    response = client.get('/api/listing-prep/package')
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.data)) as package:
        text = package.read('01-Synthetic-card-title/listing.txt').decode()
        assert '$19.99' in text and '$5.50' in text
        assert 'ITEM PRICE\n$19.99' in text and 'STARTING BID' not in text
        assert 'PRIVATE' not in text and '12345' not in text
        assert 'purchase_cost' not in text and 'seller_analysis' not in text
        assert package.read('01-Synthetic-card-title/front.jpg') == (store.root / 'crops' / f'{FRONT_ID}.jpg').read_bytes()
        assert package.read('01-Synthetic-card-title/back.jpg') == (store.root / 'crops' / f'{BACK_ID}.jpg').read_bytes()
    assert path.read_bytes() == before
    assert client.get(draft['photos'][0]['download_url']).data == (store.root / 'crops' / f'{FRONT_ID}.jpg').read_bytes()


@pytest.mark.parametrize('change', [
    {'title': 'x' * 81}, {'price_cents': -1}, {'shipping_cents': True},
    {'minimum_offer_cents': 3000}, {'photo_observation_ids': [FRONT_ID]},
    {'photo_observation_ids': [BACK_ID, FRONT_ID]}, {'identity_signature': 'stale'},
    {'identity_signature': None}, {'photo_sha256': {}},
    {'blockers': ['Review the serial number.']}, {'status': 'needs_review'}, {'status': 'draft'},
])
def test_incomplete_or_stale_drafts_cannot_enter_the_ready_package(prepared, change):
    client, _, manifest, path = prepared
    manifest['drafts'][0].update(change)
    save(manifest, path)
    report = client.get('/api/listing-prep').json
    assert not report['drafts'][0]['ready']
    assert report['drafts'][0]['blockers']
    assert client.get('/api/listing-prep/package').status_code == 409


def test_relinked_or_missing_card_photo_is_not_exported(prepared):
    client, store, _, _ = prepared
    with store.connect() as db:
        observation = store.get('observation', BACK_ID, db)
        observation['card_id'] = OTHER_ID
        store.put('observation', observation, db)
    assert not client.get('/api/listing-prep').json['drafts'][0]['ready']
    assert client.get(f'/api/listing-prep/photos/{CARD_ID}/{BACK_ID}').status_code == 404
    assert client.get('/api/listing-prep/package').status_code == 409


def test_crop_path_cannot_escape_private_crops(prepared):
    client, store, manifest, path = prepared
    secret = store.root / 'private.jpg'
    secret.write_bytes(b'PRIVATE FILE CONTENT')
    # Manifest paths are ignored. Only validated Store observation paths are used.
    manifest['drafts'][0]['photos'] = [{'path': str(secret)}]
    save(manifest, path)
    assert client.get('/api/listing-prep').json['drafts'][0]['ready']
    with store.connect() as db:
        observation = store.get('observation', FRONT_ID, db)
        observation['crop'] = 'crops/../private.jpg'
        store.put('observation', observation, db)
    assert not client.get('/api/listing-prep').json['drafts'][0]['ready']
    assert client.get(f'/api/listing-prep/photos/{CARD_ID}/{FRONT_ID}').status_code == 404
    assert client.get('/api/listing-prep/package').status_code == 409


def test_unknown_photo_ids_and_missing_manifest_are_safe(prepared):
    client, _, _, path = prepared
    assert client.get(f'/api/listing-prep/photos/{CARD_ID}/{OTHER_ID}').status_code == 404
    path.unlink()
    assert client.get('/api/listing-prep').json['status'] == 'empty'
    assert client.get('/api/listing-prep').json['photo_gallery_url'] is None
    assert client.get('/api/listing-prep/package').status_code == 409


def test_photo_gallery_is_absent_without_a_configured_path(prepared):
    client, _, _, _ = prepared
    assert client.get('/api/listing-prep').json['photo_gallery_url'] is None


@pytest.mark.parametrize('url', ['/psa10-photos.html', '/photos/psa10-batch.html', '/photos/psa10'])
def test_photo_gallery_uses_safe_local_manifest_path(prepared, url):
    client, _, manifest, path = prepared
    manifest['photo_gallery_url'] = url
    save(manifest, path)
    before = path.read_bytes()
    result = client.get('/api/listing-prep')
    assert result.status_code == 200
    assert result.json['photo_gallery_url'] == url
    assert result.json['summary']['ready'] == 1
    assert path.read_bytes() == before


@pytest.mark.parametrize('url', [
    'https://example.com/photos', '//example.com/photos', 'javascript:alert(1)',
    '/\\example.com/photos', '/photos/../private', '/photos/./psa10.html',
    '/%2f%2fexample.com', '/photos%2f..%2fprivate', '/photos.html?next=external',
    '/photos.html#other-batch', '/photos\n.html', 'photos.html', None, True, {},
])
def test_unsafe_photo_gallery_paths_are_omitted(prepared, url):
    client, _, manifest, path = prepared
    manifest['photo_gallery_url'] = url
    save(manifest, path)
    result = client.get('/api/listing-prep')
    assert result.status_code == 200
    assert result.json['photo_gallery_url'] is None
    assert result.json['summary']['ready'] == 1


def test_malformed_manifest_returns_available_error_without_details(prepared):
    client, _, _, path = prepared
    path.write_text('{invalid', encoding='utf-8')
    response = client.get('/api/listing-prep')
    assert response.status_code == 503
    assert 'unavailable' in response.json['error']
    assert str(path) not in response.json['error']


def test_crop_edits_require_a_new_reviewed_hash(prepared):
    client, store, _, _ = prepared
    Image.new('RGB', (600, 900), 'green').save(store.root / 'crops' / f'{FRONT_ID}.jpg')
    report = client.get('/api/listing-prep').json
    assert not report['drafts'][0]['ready']
    assert any('crop changed' in message for message in report['drafts'][0]['blockers'])
    assert client.get('/api/listing-prep/package').status_code == 409


@pytest.mark.parametrize('kind, id, change', [('photo', PHOTO_ID, {'review_complete': False}), ('observation', FRONT_ID, {'status': 'needs_review'})])
def test_unreviewed_photo_cannot_enter_ready_package(prepared, kind, id, change):
    client, store, _, _ = prepared
    with store.connect() as db:
        record = store.get(kind, id, db)
        record.update(change)
        store.put(kind, record, db)
    assert not client.get('/api/listing-prep').json['drafts'][0]['ready']
    assert client.get('/api/listing-prep/package').status_code == 409


def test_package_rechecks_photo_bytes_after_readiness_check(prepared, monkeypatch):
    import server.selling_prep as selling_prep
    client, store, _, _ = prepared
    real_report = selling_prep.prep_report
    def changed_after_report(current_store):
        result = real_report(current_store)
        Image.new('RGB', (600, 900), 'green').save(store.root / 'crops' / f'{FRONT_ID}.jpg')
        return result
    monkeypatch.setattr(selling_prep, 'prep_report', changed_after_report)
    assert client.get('/api/listing-prep/package').status_code == 409


def test_package_names_use_safe_readable_title_slugs(prepared):
    client, _, manifest, path = prepared
    manifest['drafts'][0]['title'] = '../Synthetic / café: title'
    save(manifest, path)
    with zipfile.ZipFile(io.BytesIO(client.get('/api/listing-prep/package').data)) as package:
        assert '01-Synthetic-cafe-title/listing.txt' in package.namelist()
        assert all('..' not in name and not name.startswith('/') for name in package.namelist())


def test_small_reviewed_photo_still_requires_listing_size(prepared):
    client, store, manifest, path = prepared
    crop = store.root / 'crops' / f'{FRONT_ID}.jpg'
    Image.new('RGB', (300, 400), 'red').save(crop)
    manifest['drafts'][0]['photo_sha256'][FRONT_ID] = hashlib.sha256(crop.read_bytes()).hexdigest()
    save(manifest, path)
    draft = client.get('/api/listing-prep').json['drafts'][0]
    assert not draft['ready']
    assert any('500 pixels' in message for message in draft['blockers'])


@pytest.mark.parametrize('duration', [1, 3, 5, 7, 10])
def test_auction_api_and_public_package_describe_the_bid_terms(prepared, duration):
    client, store, manifest, path = prepared
    manifest['drafts'][0].update(
        listing_format='auction', duration_days=duration, price_cents=1731,
        minimum_offer_cents=None, reserve_price_cents=None, buy_it_now_price_cents=None,
        seller_analysis={'purchase_cost_cents': 12345, 'modeled_net_at_starting_bid_cents': 11789,
                         'modeled_profit_at_starting_bid_cents': -556, 'cost_recovery_item_cents': 14987})
    save(manifest, path)
    before = path.read_bytes()
    draft = client.get('/api/listing-prep').json['drafts'][0]
    assert draft['ready']
    assert draft['listing_format'] == 'auction' and draft['duration_days'] == duration
    assert draft['price_cents'] == 1731 and draft['shipping_cents'] == 550
    assert draft['minimum_offer_cents'] is draft['reserve_price_cents'] is draft['buy_it_now_price_cents'] is None
    assert draft['seller_analysis']['modeled_net_at_starting_bid_cents'] == 11789
    assert draft['seller_analysis']['modeled_profit_at_starting_bid_cents'] == -556
    response = client.get('/api/listing-prep/package')
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.data)) as package:
        text = package.read('01-Synthetic-card-title/listing.txt').decode()
        assert 'FORMAT\nAuction\n' in text
        assert f'DURATION\n{duration} ' + ('day\n' if duration == 1 else 'days\n') in text
        assert 'STARTING BID\n$17.31\n' in text and 'NO RESERVE\n' in text
        assert 'BUYER SHIPPING\n$5.50\n' in text
        assert 'ITEM PRICE' not in text and 'Buy It Now' not in text
        assert 'PRIVATE' not in text and 'offer' not in text.lower()
        assert all(value not in text for value in ('123.45', '117.89', '5.56', '149.87', 'seller_analysis'))
        assert package.read('01-Synthetic-card-title/front.jpg') == (store.root / 'crops' / f'{FRONT_ID}.jpg').read_bytes()
        assert package.read('01-Synthetic-card-title/back.jpg') == (store.root / 'crops' / f'{BACK_ID}.jpg').read_bytes()
    assert path.read_bytes() == before


@pytest.mark.parametrize('change', [
    {'listing_format': 'unknown'}, {'listing_format': None},
    {'duration_days': None}, {'duration_days': 2}, {'duration_days': 11},
    {'duration_days': True}, {'duration_days': 7.0}, {'duration_days': '7'},
    {'price_cents': 0},
    {'minimum_offer_cents': 0}, {'minimum_offer_cents': 1500},
    {'reserve_price_cents': 0}, {'reserve_price_cents': 2500}, {'reserve_price_cents': False},
    {'buy_it_now_price_cents': 0}, {'buy_it_now_price_cents': 5000},
])
def test_unsupported_auction_terms_block_export(prepared, change):
    client, _, manifest, path = prepared
    manifest['drafts'][0].update(listing_format='auction', duration_days=7,
                               minimum_offer_cents=None, reserve_price_cents=None, buy_it_now_price_cents=None)
    manifest['drafts'][0].update(change)
    save(manifest, path)
    draft = client.get('/api/listing-prep').json['drafts'][0]
    assert not draft['ready'] and draft['blockers']
    assert client.get('/api/listing-prep/package').status_code == 409
