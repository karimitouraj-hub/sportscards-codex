import datetime as dt
from server.analysis import analyse_card, portfolio, signature, proceeds, break_even, DEFAULT_COSTS

CARD = dict(id='card', player='Test Player', year='2025', set='Test', variant='Blue', number='1', grade='Raw', condition='Unchanged')
TODAY = dt.date(2026, 9, 14)

def comp(**changes):
    return dict(dict(id='comp', card_id='card', source_url='https://www.ebay.com/itm/123456789012',
                     sold_date='2026-09-01', status='sold', price_status='known', currency='USD',
                     price_cents=2000, shipping_cents=100, shipping_known=True,
                     match_reviewed=True, identity_signature=signature(CARD)), **changes)

def test_proceeds_and_break_even():
    assert proceeds(2000, DEFAULT_COSTS) == 1049  # 2160 fee basis; 286 variable + 40 fixed + 625 costs.
    costs = dict(DEFAULT_COSTS, percent=50, tax_percent=50)
    for cost in (0, 10, 1000, 1000000):
        total = break_even(cost, costs)
        assert proceeds(total, costs) >= cost
        assert total == 0 or proceeds(total-1, costs) < cost
    assert break_even(None, costs) is None
    for cost in range(115, 150):
        total = break_even(cost, DEFAULT_COSTS)
        expected = next(g for g in range(1200) if proceeds(g, DEFAULT_COSTS) >= cost)
        assert total == expected

def test_limited_reference_and_unknown_cost():
    result = analyse_card(CARD, [comp()], [], today=TODAY)
    assert result['status'] == 'limited_evidence'
    assert result['market_value_cents'] == 2100
    assert result['profit_cents'] is None
    assert result['confidence'] == 'Limited'

def test_exclusions_and_duplicate_source():
    records = [comp(), comp(id='dupe', source_url='https://www.ebay.com/itm/title/123456789012?x=1'),
               comp(id='offer', price_status='hidden_offer'), comp(id='old', sold_date='2026-01-01'),
               comp(id='identity', identity_signature='stale'), comp(id='currency', currency='AUD'),
               comp(id='shipping', shipping_known=False)]
    result = analyse_card(CARD, records, [], today=TODAY)
    assert result['included'] == ['comp']
    assert len(result['excluded']) == 6

def test_identity_change_invalidates_research_and_value():
    card = dict(CARD, research={'identity_signature':signature(CARD), 'category':'sell_now'}, variant='Red')
    result = analyse_card(card, [comp()], [], today=TODAY)
    assert result['market_value_cents'] is None
    assert result['category'] == 'needs_evidence'
    assert result['research_stale']

def test_unknown_values_are_not_zero_in_portfolio():
    current = dt.date.today().isoformat()
    cards = [CARD, dict(CARD, id='unknown')]
    allocations = [dict(card_id='card', cost_cents=1500), dict(card_id='unknown', cost_cents=5000)]
    result = portfolio(cards, [comp(sold_date=current)], allocations)['summary']
    assert result['purchase_cost_cents'] == 6500
    assert result['valued_purchase_cost_cents'] == 1500
    assert result['market_value_cents'] == 2100
    assert result['valued'] == 1 and result['unvalued'] == 1

def test_unresolved_research_does_not_override_new_sales():
    card = dict(CARD, research={'identity_signature':signature(CARD), 'category':'needs_evidence'})
    result = analyse_card(card, [comp()], [], today=TODAY)
    assert result['category'] == 'patient_sale'


def test_condition_statements_follow_the_saved_source():
    raw = dict(CARD, condition_source='User states that all cards remain in their purchased condition. No professional grade is inferred.')
    raw_notes = analyse_card(raw, [], [], today=TODAY)['uncertainty']
    assert any('unchanged since purchase' in note for note in raw_notes)

    graded = dict(CARD, grade='PSA 10', condition_source='owner_confirmed_psa_label')
    graded_notes = analyse_card(graded, [], [], today=TODAY)['uncertainty']
    assert 'The owner confirmed the PSA label grade. This analysis does not regrade the card.' in graded_notes
    assert not any('unchanged since purchase' in note or 'No professional grade is inferred' in note for note in graded_notes)

    for source in (None, '', 'unknown'):
        unsupported = dict(CARD, condition='Unchanged since purchase', condition_source=source)
        notes = analyse_card(unsupported, [], [], today=TODAY)['uncertainty']
        assert not any('unchanged since purchase' in note or 'owner confirmed' in note.lower() for note in notes)
