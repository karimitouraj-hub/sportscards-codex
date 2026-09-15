"""Real SDK STDIO sessions use temporary synthetic collections only."""
import asyncio
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys

import anyio
import pytest

pytest.importorskip('mcp', reason='Install requirements-mcp.txt for the MCP transport tests.')
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from PIL import Image

from server.store import Store


REPO = Path(__file__).resolve().parents[1]
CARD_ID = 'a' * 32
TOOLS = {'status', 'list_cards', 'get_card', 'portfolio_analysis', 'pricing_report',
         'simulation_preview', 'save_simulation', 'list_simulations', 'get_simulation',
         'selling_prep', 'add_purchase', 'record_active_listing', 'list_observations',
         'create_card', 'update_card', 'link_observation', 'record_sold_comparable', 'save_listing_draft'}
MUTATIONS = {'save_simulation', 'add_purchase', 'record_active_listing', 'create_card',
             'update_card', 'link_observation', 'record_sold_comparable', 'save_listing_draft'}


@pytest.fixture
def collection(tmp_path):
    store = Store(tmp_path)
    card = dict(id=CARD_ID, revision=1, player='Synthetic Player', year='2026',
                set='Test Set', variant='Blue /99', number='12', grade='Raw',
                condition='Unchanged since purchase', serial_number='1/99',
                notes='Synthetic evidence only.', evidence_state='user_confirmed')
    with store.connect() as db:
        store.put('card', card, db)
    (tmp_path / 'session-token').write_text('private-test-session-token')
    return store


def run_session(store, check):
    async def run():
        parameters = StdioServerParameters(command=sys.executable,
            args=['-m', 'server.mcp', '--data', str(store.root)], cwd=str(REPO),
            env={'PYTHONUNBUFFERED': '1', 'SPORTSCARDS_DATA': str(store.root)})
        with anyio.fail_after(45):
            async with stdio_client(parameters) as (read, write):
                async with ClientSession(read, write) as session:
                    initialized = await session.initialize()
                    assert initialized.serverInfo.name == 'SportsCards'
                    await check(session)
    asyncio.run(run())


async def call(session, name, arguments=None):
    response = await session.call_tool(name, arguments or {})
    assert not response.isError, response
    payload = response.structuredContent
    assert isinstance(payload, dict), response
    assert 'private-test-session-token' not in json.dumps(payload)
    return payload


def test_stdio_reads_preview_and_schema(collection):
    async def check(session):
        listed = await session.list_tools()
        assert {tool.name for tool in listed.tools} == TOOLS
        for tool in listed.tools:
            assert tool.annotations.openWorldHint is False
            assert tool.annotations.readOnlyHint is (tool.name not in MUTATIONS)
        purchase_schema = next(tool.inputSchema for tool in listed.tools if tool.name == 'add_purchase')
        assert purchase_schema['$defs']['PurchaseInput']['additionalProperties'] is False
        assert (await call(session, 'status'))['counts']['card'] == 1
        result = await call(session, 'list_cards', {'query': 'synthetic', 'limit': 1})
        assert result['total'] == 1
        assert result['cards'][0]['id'] == CARD_ID
        assert (await call(session, 'list_cards', {'query': 'missing'}))['total'] == 0
        assert (await call(session, 'get_card', {'card_id': CARD_ID}))['card']['revision'] == 1
        await call(session, 'portfolio_analysis')
        report = await call(session, 'pricing_report')
        assert report['rows'][0]['scenario_price_cents'] is None
        preview = await call(session, 'simulation_preview', {'options': {'trials': 10, 'seed': 7}})
        assert preview['saved'] is False
        repeated = await call(session, 'simulation_preview', {'options': {'trials': 10, 'seed': 7}})
        assert repeated == preview
        assert (await call(session, 'list_simulations'))['total'] == 0
        assert (await call(session, 'selling_prep'))['status'] == 'empty'
    run_session(collection, check)
    assert collection.all('simulation_run') == []
    with collection.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM audit').fetchone()[0] == 0


def test_stdio_mutations_validation_and_persistence(collection):
    async def check(session):
        purchase = {'title': 'Synthetic purchase', 'source_ref': 'test-receipt-001',
                    'quantity': 1, 'total_cents': 1000}
        for arguments in ({'purchase': {**purchase, 'total_cents': True}},
                          {'purchase': {**purchase, 'refund_cents': 1001}},
                          {'purchase': {**purchase, 'unknown': 'field'}}):
            assert (await session.call_tool('add_purchase', arguments)).isError
        assert collection.all('purchase') == []
        saved_purchase = await call(session, 'add_purchase', {'purchase': purchase})
        assert saved_purchase['total_cents'] == 1000
        assert (await session.call_tool('add_purchase', {'purchase': purchase})).isError
        listing = dict(revision=1, match_reviewed=True, ask_cents=2500,
                       source_url='https://example.com/synthetic-card',
                       observed_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                       shipping_known=True, shipping_cents=500,
                       notes='Synthetic fixture. No source request occurs.')
        for changes in ({'revision': 2}, {'match_reviewed': False},
                        {'source_url': 'https://user:password@example.com/test'},
                        {'observed_at': '2099-01-01T00:00:00Z'}):
            response = await session.call_tool('record_active_listing',
                        {'card_id': CARD_ID, 'listing': {**listing, **changes}})
            assert response.isError
        assert collection.all('listing') == []
        observed = await call(session, 'record_active_listing', {'card_id': CARD_ID, 'listing': listing})
        repeated = await call(session, 'record_active_listing', {'card_id': CARD_ID, 'listing': listing})
        assert repeated['id'] == observed['id']
        assert observed['evidence_state'] == 'user_entered'
        report = await call(session, 'pricing_report')
        assert report['rows'][0]['sold_value_cents'] is None
        assert report['rows'][0]['price_source'] == 'active_listing'
        options = {'trials': 10, 'seed': 8, 'card_ids': [CARD_ID]}
        preview = await call(session, 'simulation_preview', {'options': options})
        saved = await call(session, 'save_simulation', {'options': options})
        assert saved['result'] == preview['result']
        loaded = await call(session, 'get_simulation', {'run_id': saved['id']})
        assert loaded == saved
        assert (await call(session, 'list_simulations'))['total'] == 1
        for name, arguments in (('get_card', {'card_id': '../api/state'}),
                                ('get_card', {'card_id': 'missing'}),
                                ('list_cards', {'limit': -1}),
                                ('simulation_preview', {'options': {'trials': 10001}}),
                                ('simulation_preview', {'options': {'card_ids': ['missing']}}),
                                ('http_request', {'path': '/api/state'})):
            assert (await session.call_tool(name, arguments)).isError
    run_session(collection, check)
    assert len(collection.all('purchase')) == 1
    assert len(collection.all('listing')) == 1
    assert len(collection.all('simulation_run')) == 1


def observation_fixture(store, observation_id, side, card_id=None, photo_id='d'*32):
    Image.new('RGB', (600, 900), 'blue').save(store.root / 'crops' / f'{observation_id}.jpg')
    with store.connect() as db:
        store.put('photo', {'id': photo_id, 'review_complete': True}, db)
        store.put('observation', dict(id=observation_id, photo_id=photo_id, side=side,
                  card_id=card_id, status='confirmed' if card_id else 'needs_review',
                  crop=f'crops/{observation_id}.jpg', crop_revision=0), db)


CONFIRMATION = dict(identity_confirmed=True, condition_confirmed=True,
                    source_note='The owner confirmed this card identity and current condition.')


def test_stdio_card_creation_updates_links_and_sold_evidence(collection):
    front_id, back_id, wrong_id = 'b'*32, 'c'*32, 'e'*32
    observation_fixture(collection, front_id, 'front')
    observation_fixture(collection, back_id, 'back')
    observation_fixture(collection, wrong_id, 'back', CARD_ID)

    async def check(session):
        observations = await call(session, 'list_observations')
        assert observations['total'] == 2
        card = dict(player='New Synthetic Player', condition='Owner confirmed unchanged condition.',
                    year='2026', set='Synthetic Set', number='12', variant='Blue', grade='Raw')
        args = dict(observation_id=front_id, side='front', crop_revision=0,
                    card=card, confirmation=CONFIRMATION)
        for changes in ({'confirmation': {**CONFIRMATION, 'condition_confirmed': False}},
                        {'card': {**card, 'grade': 'PSA 10'}}, {'crop_revision': 1}):
            assert (await session.call_tool('create_card', {**args, **changes})).isError
        assert len(collection.all('card')) == 1
        created = await call(session, 'create_card', args)
        assert created['condition_source'] == CONFIRMATION['source_note']
        assert (await session.call_tool('create_card', args)).isError
        new_id = created['id']
        update = dict(card_id=new_id, revision=1, changes={'variant': 'Gold'}, confirmation=CONFIRMATION)
        edited = await call(session, 'update_card', update)
        assert edited['revision'] == 2 and edited['variant'] == 'Gold'
        assert edited['player'] == created['player']
        assert (await session.call_tool('update_card', update)).isError
        assert (await session.call_tool('update_card', {**update, 'revision': 2,
                    'changes': {'grade': 'PSA 10'}})).isError
        graded = await call(session, 'update_card', {**update, 'revision': 2,
                    'changes': {'grade': 'PSA 10'},
                    'confirmation': {**CONFIRMATION, 'grade_label_confirmed': True}})
        assert graded['revision'] == 3 and graded['grade'] == 'PSA 10'
        link = dict(card_id=new_id, revision=3, observation_id=back_id, side='back',
                    same_physical_card_confirmed=True, crop_revision=0)
        for changes in ({'observation_id': wrong_id}, {'same_physical_card_confirmed': False},
                        {'revision': 2}, {'crop_revision': 1}):
            assert (await session.call_tool('link_observation', {**link, **changes})).isError
        linked = await call(session, 'link_observation', link)
        assert linked['card_revision'] == 4
        assert linked['observation']['card_id'] == new_id
        comparable = dict(revision=4, match_reviewed=True, transaction_price_confirmed=True,
                          source_url='https://example.com/synthetic-sale', source_title='Synthetic sale',
                          sold_date=dt.date.today().isoformat(), price_cents=3200,
                          shipping_cents=400, shipping_known=True,
                          match_note='The source matches the exact variant and label grade.',
                          condition_evidence='The source identifies the same labeled grade.')
        for changes in ({'revision': 3}, {'transaction_price_confirmed': False}, {'match_reviewed': False},
                        {'sold_date': '2099-01-01'}, {'sold_date': '2026-02-30'},
                        {'source_url': 'https://user:pass@example.com'}, {'price_cents': True}):
            assert (await session.call_tool('record_sold_comparable',
                    {'card_id': new_id, 'comparable': {**comparable, **changes}})).isError
        assert collection.all('comparable') == []
        saved = await call(session, 'record_sold_comparable', {'card_id': new_id, 'comparable': comparable})
        assert saved['status'] == 'sold' and saved['price_status'] == 'known'
        assert saved['card_revision'] == 4 and saved['grade'] == 'PSA 10'
        row = next(row for row in (await call(session, 'pricing_report'))['rows'] if row['card_id'] == new_id)
        assert row['price_source'] == 'sold' and row['sold_value_cents'] == 3600
        changed = await call(session, 'update_card', {'card_id': new_id, 'revision': 4,
            'changes': {'variant': 'Red'}, 'confirmation': {**CONFIRMATION, 'grade_label_confirmed': True}})
        assert changed['revision'] == 5
        row = next(row for row in (await call(session, 'pricing_report'))['rows'] if row['card_id'] == new_id)
        assert row['sold_value_cents'] is None
    run_session(collection, check)
    with collection.connect() as db:
        audit = [json.loads(row[0]) for row in db.execute("SELECT data FROM audit WHERE action='card_corrected'")]
    assert any(row['owner_confirmation']['grade_label_confirmed'] for row in audit)


def draft_input(front_id, back_id, **changes):
    return dict(card_revision=1, title='Synthetic card draft', description='Synthetic public description.',
                condition='Owner confirmed unchanged condition.', condition_confirmed=True,
                condition_source='The owner confirmed the current condition.',
                terms_confirmed=True, photos_reviewed=True, photo_observation_ids=[front_id, back_id],
                specifics={'Player': 'Synthetic Player'}, price_cents=2000, shipping_cents=400,
                **changes)


def test_stdio_draft_create_update_conflicts_and_photo_validation(collection):
    front_id, back_id = 'b'*32, 'c'*32
    observation_fixture(collection, front_id, 'front', CARD_ID)
    observation_fixture(collection, back_id, 'back', CARD_ID)
    path = collection.root / 'listing-prep' / 'current.json'

    async def check(session):
        base = draft_input(front_id, back_id)
        for changes in ({'card_revision': 2}, {'condition_confirmed': False}, {'terms_confirmed': False},
                        {'photos_reviewed': False}, {'photo_observation_ids': [back_id, front_id]},
                        {'photo_observation_ids': [front_id, front_id]}, {'minimum_offer_cents': 2500},
                        {'title': 'bad\ntitle'}, {'listing_format': 'auction', 'duration_days': 2}):
            assert (await session.call_tool('save_listing_draft', {'card_id': CARD_ID,
                        'draft': {**base, **changes}})).isError
        assert not path.exists()
        with collection.connect() as db:
            collection.put('photo', {'id': 'd'*32, 'review_complete': False}, db)
        assert (await session.call_tool('save_listing_draft', {'card_id': CARD_ID, 'draft': base})).isError
        assert not path.exists()
        with collection.connect() as db:
            collection.put('photo', {'id': 'd'*32, 'review_complete': True}, db)
        saved = await call(session, 'save_listing_draft', {'card_id': CARD_ID, 'draft': base})
        assert saved['summary'] == {'drafts': 1, 'ready': 0, 'needs_review': 1}
        digest = saved['manifest_sha256']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
        ready = {**base, 'status': 'ready'}
        assert (await session.call_tool('save_listing_draft', {'card_id': CARD_ID, 'draft': ready})).isError
        current = await call(session, 'selling_prep')
        assert current['manifest_sha256'] == digest
        updated = await call(session, 'save_listing_draft', {'card_id': CARD_ID, 'draft': ready,
                                'expected_manifest_sha256': digest})
        assert updated['summary']['ready'] == 1
        assert updated['manifest_sha256'] != digest
        original = path.read_bytes()
        stale = await session.call_tool('save_listing_draft', {'card_id': CARD_ID, 'draft': ready,
                                        'expected_manifest_sha256': digest})
        assert stale.isError and path.read_bytes() == original
        stored = json.loads(original)['drafts'][0]
        assert stored['condition_source'] == base['condition_source']
        assert stored['photo_sha256'][front_id] == hashlib.sha256(
            (collection.root / 'crops' / f'{front_id}.jpg').read_bytes()).hexdigest()
        # A file replacement invalidates an existing ready draft until photo review repeats.
        Image.new('RGB', (20, 30), 'red').save(collection.root / 'crops' / f'{front_id}.jpg')
        report = await call(session, 'selling_prep')
        assert report['summary']['ready'] == 0
        response = await session.call_tool('save_listing_draft', {'card_id': CARD_ID, 'draft': ready,
                            'expected_manifest_sha256': updated['manifest_sha256']})
        assert response.isError and path.read_bytes() == original
        observation_fixture(collection, front_id, 'front', CARD_ID)
        with collection.connect() as db:
            observation = collection.get('observation', back_id, db)
            observation['crop'] = '../private.jpg'
            collection.put('observation', observation, db)
        assert (await session.call_tool('save_listing_draft', {'card_id': CARD_ID, 'draft': ready,
                    'expected_manifest_sha256': updated['manifest_sha256']})).isError
        assert path.read_bytes() == original
    run_session(collection, check)


def test_stdio_draft_updates_preserve_other_cards(collection):
    other_card = '1'*32
    with collection.connect() as db:
        collection.put('card', {**collection.get('card', CARD_ID, db), 'id': other_card}, db)
    for card_id, front, back in ((CARD_ID, 'b'*32, 'c'*32), (other_card, 'e'*32, 'f'*32)):
        observation_fixture(collection, front, 'front', card_id)
        observation_fixture(collection, back, 'back', card_id)

    async def check(session):
        first_draft = draft_input('b'*32, 'c'*32, status='ready')
        first = await call(session, 'save_listing_draft', {'card_id': CARD_ID, 'draft': first_draft})
        second = await call(session, 'save_listing_draft', {'card_id': other_card,
            'draft': draft_input('e'*32, 'f'*32, status='ready'),
            'expected_manifest_sha256': first['manifest_sha256']})
        before = next(row for row in second['drafts'] if row['card_id'] == other_card)
        updated = await call(session, 'save_listing_draft', {'card_id': CARD_ID,
            'draft': {**first_draft, 'title': 'Updated synthetic title'},
            'expected_manifest_sha256': second['manifest_sha256']})
        assert updated['summary'] == {'drafts': 2, 'ready': 2, 'needs_review': 0}
        assert next(row for row in updated['drafts'] if row['card_id'] == other_card) == before
        assert next(row for row in updated['drafts'] if row['card_id'] == CARD_ID)['title'] == 'Updated synthetic title'
    run_session(collection, check)
