import datetime as dt
import math
import itertools

import pytest

from server.analysis import DEFAULT_COSTS, proceeds, signature
from server.pricing_engine import engine_report, simulate, simulate_release, validate_settings

TODAY = dt.date(2026, 9, 14)
CARD = dict(id='one', player='Test Player', year='2025', set='Test Set', number='1', variant='Blue /99',
            grade='Raw', condition='Unchanged', serial_number='01/99')
ZERO_SHOCKS = dict(market_sigma=0, player_sigma=0, product_sigma=0, card_sigma=0)


def listing(card=CARD, **changes):
    return dict(dict(id='listing', card_id=card['id'], source_url='https://www.ebay.com/itm/123456789012',
                     ask_cents=2000, shipping_cents=500, shipping_known=True, currency='USD', status='active',
                     buying_format='fixed_price', match_reviewed=True, identity_signature=signature(card),
                     observed_at='2026-09-14T10:00:00Z', first_observed_at='2026-09-10T10:00:00Z',
                     seller='Seller A', physical_copy_key=''), **changes)


def sale(card=CARD, **changes):
    return dict(dict(id='sale', card_id=card['id'], source_url='https://www.ebay.com/itm/123456789099',
                     price_cents=3000, shipping_cents=500, shipping_known=True, currency='USD',
                     sold_date='2026-09-10', status='sold', price_status='known',
                     match_reviewed=True, identity_signature=signature(card)), **changes)


def report(cards=None, listings=None, sales=None, costs=None, allocations=None):
    return engine_report(cards or [CARD], sales or [], allocations if allocations is not None else [dict(card_id='one', cost_cents=1000)],
                         listings if listings is not None else [listing()], costs=costs, today=TODAY)


def test_asking_reference_and_sold_anchor_remain_separate():
    observed = report(sales=[sale()])['rows'][0]
    assert observed['active_ask_cents'] == 2500
    assert observed['listing_scenario_cents'] == 2000
    assert observed['sold_value_cents'] == observed['scenario_price_cents'] == 3500
    assert observed['price_source'] == 'sold'
    assert observed['active_sample_count'] == observed['active_seller_count'] == 1
    assert observed['active_sources'][0]['source_url'].endswith('123456789012')


def test_latest_observation_suppresses_previous_active_and_relisted_copy():
    records = [listing(id='old', observed_at='2026-09-10T00:00:00Z'),
               listing(id='ended', status='withdrawn'),
               listing(id='copy_old', source_url='https://www.ebay.com/itm/223456789012', physical_copy_key='serial-30',
                       observed_at='2026-09-12T00:00:00Z'),
               listing(id='copy_new', source_url='https://www.ebay.com/itm/323456789012', physical_copy_key='serial-30')]
    result = report(listings=records)['rows'][0]
    assert result['active_included'] == ['copy_new']
    assert len(result['active_excluded']) == 3
    assert any('later observation' in reason for reason in result['active_excluded'][0]['reasons'])


def test_listing_rules_and_freshness_are_visible():
    variants = [dict(observed_at='2026-08-30T00:00:00Z'), dict(observed_at='2026-09-15T00:00:00Z'),
                dict(identity_signature='stale'), dict(currency='AUD'), dict(shipping_known=False),
                dict(buying_format='auction'), dict(match_reviewed=False), dict(ask_cents=float('nan'))]
    records = [listing(id=str(index), source_url=f'https://www.ebay.com/itm/{123456789100+index}', **changes)
               for index, changes in enumerate(variants)]
    result = report(listings=records)['rows'][0]
    assert result['active_ask_cents'] is None
    assert len(result['active_excluded']) == len(variants)
    assert result['price_source'] == 'unknown'
    boundary = report(listings=[listing(observed_at='2026-08-31T00:00:00Z')])['rows'][0]
    assert boundary['active_sample_count'] == 1


def test_equal_observation_dates_use_creation_time_and_stable_ties():
    records = [listing(id='original', created_at='2026-09-14T11:00:00Z', physical_copy_key='incorrect'),
               listing(id='correction', created_at='2026-09-14T12:00:00Z', physical_copy_key=''),
               listing(id='other', source_url='https://www.ebay.com/itm/223456789012',
                       created_at='2026-09-14T11:00:00Z', physical_copy_key='incorrect')]
    expected = report(listings=records)['rows'][0]
    assert set(expected['active_included']) == {'correction', 'other'}
    for permutation in itertools.permutations(records):
        assert report(listings=list(permutation))['rows'][0] == expected
    # An equal creation time or absent creation time must not depend on storage order.
    ties = [listing(id='tie-a'), listing(id='tie-z', ask_cents=3000)]
    assert report(listings=ties)['rows'][0] == report(listings=list(reversed(ties)))['rows'][0]
    assert report(listings=ties)['rows'][0]['active_included'] == ['tie-z']


def test_corrected_snapshot_does_not_refresh_original_evidence_date():
    records = [listing(id='original', observed_at='2026-08-30T00:00:00Z', created_at='2026-08-30T00:00:00Z'),
               listing(id='correction', observed_at='2026-08-30T00:00:00Z', created_at='2026-09-14T00:00:00Z')]
    result = report(listings=records)['rows'][0]
    assert result['active_sample_count'] == 0
    correction = next(row for row in result['active_excluded'] if row['id'] == 'correction')
    assert 'The observation must be within the past 14 days.' in correction['reasons']


def test_seeded_trials_are_repeatable_and_portfolio_quantiles_use_joint_draws():
    other = dict(CARD, id='two', player='Other Player', serial_number='02/99')
    data = report(cards=[CARD, other], listings=[listing(), listing(other, id='other')])
    options = dict(trials=500, seed=83)
    first = simulate(data, options)
    assert first == simulate(data, options)
    assert first['metrics']['net_cash_cents'] != simulate(data, dict(options, seed=84))['metrics']['net_cash_cents']
    assert first['metrics']['net_cash_cents']['p90'] != sum(row['net_cash_cents']['p90'] for row in first['cards'])


def test_no_sale_retains_all_costs_and_unknown_values():
    unknown = dict(CARD, id='unknown')
    data = report(cards=[CARD, unknown], allocations=[dict(card_id='one', cost_cents=1000), dict(card_id='unknown', cost_cents=5000)])
    result = simulate(data, dict(trials=10, p30=0, **ZERO_SHOCKS))
    assert result['metrics']['net_cash_cents']['p50'] == 0
    assert result['metrics']['retained_cost_cents']['p50'] == 6000
    assert result['metrics']['probability_no_sale'] == 1
    assert result['metrics']['probability_realized_loss_given_known_cost_sale'] is None
    assert result['summary']['unknown_cards'] == 1
    assert next(row for row in result['cards'] if row['card_id'] == 'unknown')['price_cents'] is None
    assert result['metrics']['retained_model_value_cents']['p50'] == 2000


def test_certain_sale_applies_costs_once_and_keeps_profit_distinct():
    result = simulate(report(), dict(trials=3, p30=1, **ZERO_SHOCKS))
    expected = proceeds(2000, DEFAULT_COSTS)
    assert result['metrics']['gross_sales_cents']['p50'] == 2000
    assert result['metrics']['net_cash_cents']['p50'] == expected
    assert result['metrics']['realized_profit_cents']['p50'] == expected-1000
    assert result['metrics']['retained_cost_cents']['p50'] == 0
    assert result['metrics']['probability_no_sale'] == 0
    assert result['metrics']['loss_denominator_trials'] == 3


def test_duplicate_variants_share_price_draw_but_not_individual_sale_event():
    other = dict(CARD, id='two', serial_number='02/99')
    data = report(cards=[CARD, other], listings=[listing(), listing(other, id='other')])
    result = simulate(data, dict(trials=1000, seed=12, horizon_days=30, p30=.5))
    assert result['cards'][0]['price_cents'] == result['cards'][1]['price_cents']
    assert 0.2 < result['metrics']['probability_no_sale'] < 0.3
    assert result['cards'][0]['sale_probability'] != result['cards'][1]['sale_probability']


def test_duplicate_asking_reference_cannot_dilute_sold_anchor():
    other = dict(CARD, id='two', serial_number='02/99')
    data = report(cards=[CARD, other], listings=[listing(other, ask_cents=100, shipping_cents=0)], sales=[sale()])
    result = simulate(data, dict(trials=3, p30=1, listing_factor=.6, **ZERO_SHOCKS))
    assert result['metrics']['gross_sales_cents']['p50'] == 7000
    assert {row['effective_price_source'] for row in result['cards']} == {'sold'}


def test_bundle_shares_order_costs_and_preserves_rounding():
    other = dict(CARD, id='two', serial_number='02/99')
    allocations = [dict(card_id='one', cost_cents=1000), dict(card_id='two', cost_cents=1000)]
    data = report(cards=[CARD, other], listings=[listing(), listing(other, id='other')], allocations=allocations)
    result = simulate(data, dict(trials=2, strategy='bundle', bundle_p30=1, bundle_price_factor=1,
                                 bundle_shipping_cents=550, bundle_packaging_cents=75, **ZERO_SHOCKS))
    expected = proceeds(4000, DEFAULT_COSTS)
    assert result['metrics']['net_cash_cents']['p50'] == expected
    assert result['metrics']['realized_profit_cents']['p50'] == expected-2000
    assert sum(row['net_cash_cents']['p50'] for row in result['cards']) == expected
    assert expected > 2*proceeds(2000, DEFAULT_COSTS)


def test_hold_and_markdown_do_not_invent_sale_speed():
    held = simulate(report(), dict(trials=5, strategy='hold', p30=1, **ZERO_SHOCKS))
    assert held['metrics']['sold_count']['p50'] == 0
    assert held['metrics']['retained_cost_cents']['p50'] == 1000
    marked = simulate(report(), dict(trials=5, strategy='markdown', p30=0, markdown_p30=1,
                                     markdown_after_days=30, horizon_days=60, markdown_price_factor=.5, **ZERO_SHOCKS))
    assert marked['metrics']['gross_sales_cents']['p50'] == 1000
    before = simulate(report(), dict(trials=5, strategy='markdown', p30=0, markdown_p30=1,
                                     markdown_after_days=30, horizon_days=20, markdown_price_factor=.5, **ZERO_SHOCKS))
    assert before['metrics']['gross_sales_cents']['p50'] == 0
    assert before['cards'][0]['price_cents']['p50'] == 2000


def test_unknown_purchase_cost_does_not_become_profit():
    result = simulate(report(allocations=[]), dict(trials=3, p30=1, **ZERO_SHOCKS))
    assert result['metrics']['realized_profit_cents'] is None
    assert result['cards'][0]['realized_profit_cents'] is None
    assert result['metrics']['probability_realized_loss_given_known_cost_sale'] is None
    assert result['summary']['unknown_purchase_cost_cards'] == 1


def test_settings_and_simulation_input_validation():
    for settings in ({'p30': 1.1}, {'listing_factor': float('nan')}, {'card_sigma': True}, {'unknown': 1}):
        with pytest.raises(ValueError):
            validate_settings(settings)
    for options in ({'trials': 10001}, {'trials': 1.2}, {'seed': -1}, {'card_ids': ['missing']},
                    {'card_ids': ['one', 'one']}, {'strategy': 'guaranteed'}, {'horizon_days': 0}):
        with pytest.raises(ValueError):
            simulate(report(), options)


def test_release_paths_validate_and_keep_age_as_context():
    options = dict(reference_price_cents=10000, purchase_cost_cents=2000, quantity=2,
                   days_since_release=10, trials=3, p30=1, **ZERO_SHOCKS)
    result = simulate_release(options)
    assert result['status'] == 'unvalidated_release_scenario'
    assert [row['terminal_reference_cents'] for row in result['scenarios']] == [6000, 8500, 12000]
    assert result['scenarios'][1]['simulation']['metrics']['gross_sales_cents']['p50'] == 17000
    older = simulate_release(dict(options, days_since_release=100))
    assert older['scenarios'] == result['scenarios']
    for changes in ({'reference_price_cents': 0}, {'low_factor': 2}, {'quantity': 101},
                    {'base_factor': math.inf}, {'purchase_cost_cents': -1}, {'name': ''}):
        with pytest.raises(ValueError):
            simulate_release(dict(options, **changes))
