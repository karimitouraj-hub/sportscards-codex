"""Real SDK STDIO sessions use temporary synthetic collections only."""
import asyncio
import datetime as dt
import json
from pathlib import Path
import sys

import anyio
import pytest

pytest.importorskip('mcp', reason='Install requirements-mcp.txt for the MCP transport tests.')
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from server.store import Store


REPO = Path(__file__).resolve().parents[1]
CARD_ID = 'a' * 32
TOOLS = {'status', 'list_cards', 'get_card', 'portfolio_analysis', 'pricing_report',
         'simulation_preview', 'save_simulation', 'list_simulations', 'get_simulation',
         'selling_prep', 'add_purchase', 'record_active_listing'}
MUTATIONS = {'save_simulation', 'add_purchase', 'record_active_listing'}


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
