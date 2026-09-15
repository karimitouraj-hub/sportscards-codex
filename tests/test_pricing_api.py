"""Synthetic API tests. Production records are never used by this file."""
import csv
import datetime as dt
import io

import pytest

from server.app import create_app
from server.analysis import signature
from server.pricing_engine import simulate


@pytest.fixture
def pricing(tmp_path):
    app = create_app(tmp_path)
    card = dict(id='pricing-test-card', revision=1, player='Test Player', year='2026',
                set='Test Set', variant='Blue /99', number='12', grade='Raw',
                condition='Unchanged since purchase', serial_number='1/99')
    with app.store.connect() as db:
        app.store.put('card', card, db)
        app.store.put('allocation', dict(id='pricing-test-allocation', card_id=card['id'],
                                        purchase_id='test-purchase', cost_cents=8000), db)
    client = app.test_client()
    client.environ_base['HTTP_X_SPORTSCARDS_TOKEN'] = client.get('/api/state').json['token']
    return app, client, card


def listing(card, **changes):
    return dict(revision=card['revision'], match_reviewed=True, ask_cents=5000,
                shipping_cents=500, shipping_known=True, currency='USD', status='active',
                observed_at=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(minutes=1)).isoformat(),
                source_url='https://www.ebay.com/itm/123456789012', source_title='Test card Blue /99',
                seller='Test seller', physical_copy_key='blue-2-of-99', buying_format='fixed_price',
                evidence_state='browser_observed', notes='Synthetic fixture.', **changes)


def test_listing_append_idempotence_latest_and_identity_invalidation(pricing):
    app, client, card = pricing
    path = '/api/cards/'+card['id']+'/listings'
    data = listing(card)
    first = client.post(path, json=data)
    assert first.status_code == 201, first.json
    assert first.json['identity_signature'] == signature(card)
    assert client.post(path, json=data).status_code == 200
    assert len(client.get(path).json['listings']) == 1
    newer = {**data, 'ask_cents': 6000, 'observed_at': dt.datetime.now(dt.timezone.utc).isoformat()}
    second = client.post(path, json=newer)
    assert second.status_code == 201
    assert second.json['first_observed_at'] == first.json['first_observed_at']
    assert client.get(path).json['listings'][1]['ask_cents'] == 5000
    report = client.get('/api/pricing-engine')
    assert report.status_code == 200, report.json
    row = report.json['rows'][0]
    assert row['active_sample_count'] == 1
    assert row['active_ask_cents'] == 6500
    assert row['listing_scenario_cents'] == 5200
    assert row['sold_value_cents'] is None
    assert row['price_source'] == 'active_listing'
    changed = client.patch('/api/cards/'+card['id'], json={'revision': 1, 'variant': 'Gold /10'})
    assert changed.status_code == 200
    assert client.post(path, json=data).status_code == 409
    stale = client.get('/api/pricing-engine').json['rows'][0]
    assert stale['active_sample_count'] == 0
    assert stale['price_source'] == 'unknown'


@pytest.mark.parametrize('changes', [
    {'ask_cents': True}, {'ask_cents': 0}, {'ask_cents': float('nan')},
    {'shipping_cents': -1}, {'shipping_known': 'true'}, {'match_reviewed': False},
    {'match_reviewed': 1}, {'currency': 'XXX'}, {'status': 'available'},
    {'source_url': 'javascript:alert(1)'}, {'source_url': 'https://user:pass@example.com/x'},
    {'observed_at': '2026-09-14'}, {'observed_at': '2099-01-01T00:00:00+00:00'},
    {'buying_format': 'unknown'}, {'evidence_state': 'verified'}, {'seller': 'x'*251},
])
def test_listing_rejects_invalid_input_without_mutation(pricing, changes):
    app, client, card = pricing
    response = client.post('/api/cards/'+card['id']+'/listings', json={**listing(card), **changes})
    assert response.status_code == 400, response.json
    assert app.store.all('listing') == []


def test_research_and_settings_persist_and_export(pricing):
    app, client, card = pricing
    research = dict(revision=1, query='Exact card Blue /99', url='https://www.ebay.com/sch/i.html?_nkw=test',
                    limitations='No exact fixed-price listing was found.',
                    reviewed_at=dt.datetime.now(dt.timezone.utc).isoformat())
    endpoint = '/api/cards/'+card['id']+'/listing-research'
    saved = client.put(endpoint, json=research)
    assert saved.status_code == 200, saved.json
    assert client.put(endpoint, json=research).json['id'] == saved.json['id']
    assert client.get('/api/pricing-engine').json['rows'][0]['listing_research']['query'] == research['query']
    assert client.patch('/api/pricing-settings', json={'listing_factor': .65}).status_code == 200
    assert client.patch('/api/pricing-settings', json={'p30': .2}).json['listing_factor'] == .65
    for payload in ({'p30': True}, {'p30': -1}, {'listing_factor': 2.1}, {'card_sigma': float('inf')}, {'unknown': 1}):
        assert client.patch('/api/pricing-settings', json=payload).status_code == 400
    exported = client.get('/api/export/json').json
    assert exported['schema_version'] == 2
    assert len(exported['listing_research']) == 1
    assert next(r for r in exported['settings'] if r['id'] == 'pricing-settings')['settings']['listing_factor'] == .65
    reloaded = create_app(app.store.root).test_client()
    assert reloaded.get('/api/pricing-engine').json['settings']['listing_factor'] == .65


def test_sold_evidence_keeps_priority_over_asking_scenarios(pricing):
    app, client, card = pricing
    with app.store.connect() as db:
        app.store.put('comparable', dict(id='pricing-test-sale', card_id=card['id'],
                      identity_signature=signature(card), match_reviewed=True, status='sold', price_status='known',
                      currency='USD', shipping_known=True, price_cents=9000, shipping_cents=500,
                      sold_date=dt.date.today().isoformat(), source_url='https://www.ebay.com/itm/987654321098'), db)
    client.post('/api/cards/'+card['id']+'/listings', json=listing(card))
    row = client.get('/api/pricing-engine').json['rows'][0]
    assert row['price_source'] == 'sold'
    assert row['scenario_price_cents'] == row['sold_value_cents'] == 9500
    assert row['listing_scenario_cents'] == 4400
    exported = list(csv.DictReader(io.StringIO(client.get('/api/export/pricing-csv').text)))[0]
    assert exported['sold_source_urls'] == 'https://www.ebay.com/itm/987654321098'
    assert exported['listing_source_urls'] == 'https://www.ebay.com/itm/123456789012'


def test_saved_simulation_replays_original_inputs_and_exports(pricing):
    app, client, card = pricing
    client.post('/api/cards/'+card['id']+'/listings', json=listing(card))
    options = {'seed': 17, 'trials': 20, 'horizon_days': 90, 'strategy': 'individual'}
    response = client.post('/api/pricing-engine/simulate', json=options)
    assert response.status_code == 201, response.json
    saved = response.json
    assert saved['seed'] == 17
    assert len(saved['inputs_digest']) == len(saved['data_fingerprint']) == 64
    assert simulate(saved['input_report'], saved['options']) == saved['result']
    client.patch('/api/pricing-settings', json={'listing_factor': .5})
    assert client.get('/api/pricing-engine/runs/'+saved['id']).json == saved
    history = client.get('/api/pricing-engine/runs').json
    assert history['total'] == 1
    assert 'input_report' not in history['runs'][0]
    assert history['runs'][0]['id'] == saved['id']
    artifact = client.get('/api/export/simulation/'+saved['id'])
    assert artifact.json['run'] == saved
    assert 'attachment' in artifact.headers['Content-Disposition']
    assert len(client.get('/api/export/json').json['simulation_runs']) == 1
    assert client.get('/api/pricing-engine/runs?limit=1000000').status_code == 400
    for bad in ({'trials': 10001}, {'seed': True}, {'horizon_days': 0}, {'card_ids': ['missing']}):
        assert client.post('/api/pricing-engine/simulate', json=bad).status_code == 400
    assert len(app.store.all('simulation_run')) == 1


def test_release_and_csv_keep_estimates_separate(pricing):
    app, client, card = pricing
    with app.store.connect() as db:
        app.store.put('card', {**card, 'player': '=HYPERLINK("https://example.com")'}, db)
    updated = app.store.get('card', card['id'])
    client.post('/api/cards/'+card['id']+'/listings', json=listing(updated))
    response = client.get('/api/export/pricing-csv')
    assert response.status_code == 200, response.text
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert len(rows) == 1
    assert rows[0]['player'].startswith("'=")
    assert rows[0]['sold_value_cents'] == ''
    assert rows[0]['listing_scenario_cents'] == '4400'
    assert int(rows[0]['scenario_profit_cents']) < 0
    assert rows[0]['listing_source_urls'] == 'https://www.ebay.com/itm/123456789012'
    release = client.post('/api/pricing-engine/releases', json={
        'name': 'Synthetic release', 'reference_price_cents': 5000, 'purchase_cost_cents': 6000,
        'trials': 10, 'quantity': 2, 'seed': 8})
    assert release.status_code == 201, release.json
    assert release.json['type'] == 'release'
    assert release.json['result']['status'] == 'unvalidated_release_scenario'
    assert len(release.json['result']['scenarios']) == 3
    assert release.json['seed'] == 8
    assert client.post('/api/pricing-engine/releases', json={'reference_price_cents': -1}).status_code == 400


def test_new_routes_inherit_host_origin_and_token_protection(pricing):
    app, client, card = pricing
    assert app.test_client().post('/api/pricing-settings', json={}).status_code in (403, 405)
    assert app.test_client().patch('/api/pricing-settings', json={}).status_code == 403
    assert client.post('/api/cards/'+card['id']+'/listings', json=listing(card),
                       headers={'Origin': 'https://example.com'}).status_code == 403
    assert client.get('/api/pricing-engine', headers={'Host': 'example.com'}).status_code == 403
    assert client.get('/api/pricing-engine').headers['Cache-Control'] == 'no-store'
