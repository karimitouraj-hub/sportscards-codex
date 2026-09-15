"""Fee boundaries use the public US non-Store trading-card schedule."""
from server.analysis import DEFAULT_COSTS, break_even, normalize_costs, proceeds
from server.pricing_engine import simulate_release


def test_default_fee_tier_boundaries_and_tax_basis():
    costs = dict(DEFAULT_COSTS, tax_percent=0, shipping_cents=0, packaging_cents=0)
    assert proceeds(750000, costs) == 650585  # 99,375 variable cents plus 40 fixed cents.
    assert proceeds(750001, costs) == 650586
    assert proceeds(1000000, costs) == 894710  # 99,375 + 5,875 variable cents plus 40 fixed cents.
    assert proceeds(1000000, DEFAULT_COSTS) == 892205  # Fee base includes 80,000 cents of assumed buyer tax.
    for gross in (749950, 749999, 750000, 750001, 750050, 751000, 1000000):
        variable = min(gross, 750000)*.1325 + max(gross-750000, 0)*.0235
        assert proceeds(gross, costs) == gross-round(variable)-40
    # Estimated buyer tax can cross the fee tier before the gross price reaches $7,500.
    for gross in (694443, 694444, 694445, 694446):
        base = gross+round(gross*.08)
        variable = min(base, 750000)*13.25/100+max(base-750000, 0)*2.35/100
        assert proceeds(gross, DEFAULT_COSTS) == gross-round(variable)-40-625


def test_low_price_results_and_order_fee_boundary_stay_unchanged():
    for gross in range(100001):
        tax = round(gross*.08)
        fixed = 30 if gross+tax <= 1000 else 40
        previous = gross-round((gross+tax)*13.25/100)-fixed-625
        assert proceeds(gross, DEFAULT_COSTS) == previous


def test_custom_percentage_is_explicitly_flat_above_the_tier():
    costs = normalize_costs(dict(DEFAULT_COSTS, percent=10))
    assert costs['fee_model'] == 'flat_percentage'
    assert costs['tier_threshold_cents'] is None
    assert costs['excess_percent'] is None
    assert proceeds(1000000, costs) == 891335
    assert 'not a verified account fee' in costs['basis']
    restored = normalize_costs(dict(costs, percent=13.25))
    assert restored['fee_model'] == 'ebay_us_non_store'
    assert restored['tier_threshold_cents'] == 750000
    assert restored['excess_percent'] == 2.35
    assert proceeds(1000000, restored) == 892205


def test_high_price_break_even_and_release_cost_reconciliation():
    for cost in (500000, 700000, 1000000, 10000000):
        gross = break_even(cost, DEFAULT_COSTS)
        assert proceeds(gross, DEFAULT_COSTS) >= cost
        assert proceeds(gross-1, DEFAULT_COSTS) < cost
    release = simulate_release(dict(reference_price_cents=1000000, purchase_cost_cents=500000,
                                    quantity=2, trials=1, p30=1, low_factor=1, base_factor=1, high_factor=1,
                                    market_sigma=0, player_sigma=0, product_sigma=0, card_sigma=0))
    outcome = release['scenarios'][1]['simulation']
    assert outcome['metrics']['net_cash_cents']['p50'] == 2*892205
    assert outcome['metrics']['realized_profit_cents']['p50'] == 2*892205-1000000
    assert outcome['costs']['fee_model'] == 'ebay_us_non_store'
