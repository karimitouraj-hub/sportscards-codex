"""Evidence-based collection decisions. All proceeds are estimates."""
import datetime as dt
import hashlib
import json
import math
import statistics
from .valuation import comparable_source, IDENTITY_FIELDS

VERSION = 'purchase-and-sales-v1'
CATEGORIES = ('hold', 'sell_now', 'patient_sale', 'bundle', 'discard_candidate', 'needs_evidence')
LABELS = dict(hold='Hold', sell_now='Sell now', patient_sale='Patient sale', bundle='Bulk, bundle, or donate', discard_candidate='Discard candidate', needs_evidence='Needs more evidence')
DEFAULT_COSTS = dict(percent=13.25, tax_percent=8.0, shipping_cents=550, packaging_cents=75,
                     fixed_cents=40, dynamic_fixed=True, currency='USD',
                     fee_model='ebay_us_non_store', tier_threshold_cents=750000, excess_percent=2.35,
                     source_url='https://www.ebay.com/help/selling/fees-credits-invoices/selling-fees?id=4822',
                     source_verified_at='2026-09-14',
                     basis='US non-Store trading cards: 13.25% through $7,500 per sold item, then 2.35% on the excess. The fee base includes buyer shipping and estimated tax. Other fee percentages use a flat-rate scenario. Shipping, packaging, and buyer tax are assumptions. No promoted-listing fee is assumed.')


def normalize_costs(costs=None):
    """Make the default eBay tier and custom flat-rate scenarios explicit."""
    result = {**DEFAULT_COSTS, **(costs or {})}
    standard = result['percent'] == DEFAULT_COSTS['percent']
    result.update(fee_model='ebay_us_non_store' if standard else 'flat_percentage',
                  tier_threshold_cents=750000 if standard else None,
                  excess_percent=2.35 if standard else None,
                  source_verified_at=DEFAULT_COSTS['source_verified_at'])
    result['basis'] = DEFAULT_COSTS['basis'] if standard else (
        f"Custom flat-rate scenario: {result['percent']}% of the full sale total including buyer shipping and estimated tax. "
        'This is an assumption, not a verified account fee. Shipping, packaging, and buyer tax are assumptions. '
        'Set the fee to 13.25% to use the standard eBay trading-card tiers. No promoted-listing fee is assumed.')
    return result

def signature(card):
    fields = IDENTITY_FIELDS + ('serial_number', 'sport', 'manufacturer', 'autograph', 'memorabilia')
    return hashlib.sha256(json.dumps({k: card.get(k, '') for k in fields}, sort_keys=True).encode()).hexdigest()

def proceeds(gross, costs):
    tax = round(gross * costs.get('tax_percent', 0) / 100)
    fee_base = gross + tax
    fixed = (30 if fee_base <= 1000 else 40) if costs.get('dynamic_fixed') else costs.get('fixed_cents', 40)
    # Each invocation represents one sold item or one bundle sold as a single lot.
    if costs['percent'] == DEFAULT_COSTS['percent']:
        variable = min(fee_base, 750000) * 13.25 / 100 + max(0, fee_base - 750000) * 2.35 / 100
    else:
        variable = fee_base * costs['percent'] / 100
    fee = round(variable) + fixed
    return gross - fee - costs['shipping_cents'] - costs.get('packaging_cents', 0)

def break_even(cost, costs):
    if cost is None:
        return None
    # Binary search preserves cent rounding and the order-fee threshold.
    ceiling = max(10000, (cost + costs['shipping_cents'] + costs.get('packaging_cents', 0) + 100) * 5)
    # The fixed fee rises by ten cents at $10. Search each monotonic interval.
    boundary = 0
    if costs.get('dynamic_fixed'):
        boundary = max(g for g in range(1001) if g + round(g * costs.get('tax_percent', 0) / 100) <= 1000)
    intervals = [(0, boundary), (boundary+1, ceiling)] if boundary else [(0, ceiling)]
    for lo, hi in intervals:
        if proceeds(hi, costs) < cost:
            continue
        while lo < hi:
            mid = (lo + hi) // 2
            if proceeds(mid, costs) >= cost:
                hi = mid
            else:
                lo = mid + 1
        return lo
    return None

def analyse_card(card, comparables, allocations, costs=None, today=None):
    today = today or dt.date.today()
    costs = normalize_costs(costs)
    own = [a for a in allocations if a['card_id'] == card['id']]
    cost = sum(a['cost_cents'] for a in own) if own else None
    fingerprint = signature(card)
    research = card.get('research', {})
    fresh = research.get('identity_signature') == fingerprint
    included, excluded, seen = [], [], set()
    for comp in comparables:
        if comp['card_id'] != card['id']:
            continue
        reasons = []
        if not comp.get('match_reviewed'):
            reasons.append('Comparable identity has not been reviewed.')
        if comp.get('identity_signature') != fingerprint:
            reasons.append('Card details changed after this comparison.')
        if comp.get('status') != 'sold':
            reasons.append('This is not confirmed sold evidence.')
        if comp.get('price_status') != 'known':
            reasons.append('The accepted price is not visible or verified.')
        if comp.get('currency') != 'USD':
            reasons.append('The sale is not in USD.')
        if not comp.get('shipping_known', False):
            reasons.append('Buyer shipping is unknown.')
        try:
            age = (today - dt.date.fromisoformat(comp['sold_date'])).days
            if not 0 <= age <= 90:
                reasons.append('The sale is outside the past 90 days.')
        except (ValueError, KeyError):
            reasons.append('Sale date is missing or invalid.')
        source = comparable_source(comp.get('source_url', ''))
        if source in seen:
            reasons.append('This sale is already included.')
        if reasons:
            excluded.append(dict(id=comp['id'], reasons=reasons))
        else:
            included.append(comp)
            seen.add(source)
    values = [c['price_cents'] + c['shipping_cents'] for c in included]
    count = len(values)
    market = round(statistics.median(values)) if values else None
    net = proceeds(market, costs) if market is not None else None
    category = 'needs_evidence'
    reason = 'No reviewed, recent sold price with a visible amount supports this exact card.'
    horizon = 'Before a sale decision'
    trigger = 'Add a recent exact-variant sold transaction with a visible price.'
    if values:
        if net < 500:
            category, reason = 'bundle', 'Estimated individual-sale proceeds are under $5 after the selected selling costs. Combine compatible cards to share postage.'
            horizon, trigger = 'Next collection sale', 'Reconsider an individual sale if net proceeds exceed $5 or a cheaper eligible shipping method is available.'
        else:
            category, reason = 'patient_sale', 'Use a fixed-price listing with a defined review date. The observed sales support a range, not a guaranteed price.'
            horizon, trigger = '30–60 days', 'Review after 30 days without a sale, or after a new exact-variant sold transaction.'
        if count >= 3 and max(values) <= min(values) * 1.5 and net >= 500:
            category, reason = 'sell_now', 'Several recent sales fall within a relatively narrow range. Pricing near the observed median supports a current sale attempt.'
            horizon, trigger = '7–30 days', 'Review after 14 days without a sale or after a material change in sold prices.'
    if fresh and research.get('category') in CATEGORIES:
        requested = research['category']
        # A positive disposal decision cannot bypass missing price evidence.
        if values and requested not in ('discard_candidate', 'needs_evidence'):
            category = requested
            reason = research.get('reason') or reason
            horizon = research.get('horizon') or horizon
            trigger = research.get('trigger') or trigger
    confidence = 'Limited' if count < 3 else 'Moderate' if count < 6 else 'Stronger sample'
    if not values:
        confidence = 'Insufficient'
    uncertainty = ['Prices are observed sale amounts, not guaranteed proceeds.',
                   'Postage, packaging, and buyer tax are estimates. Fees can vary by account and listing.']
    if card.get('condition_source') == 'User states that all cards remain in their purchased condition. No professional grade is inferred.':
        uncertainty.insert(1, 'The user states that condition is unchanged since purchase. No professional grade is inferred.')
    elif card.get('condition_source') == 'owner_confirmed_psa_label':
        uncertainty.insert(1, 'The owner confirmed the PSA label grade. This analysis does not regrade the card.')
    if count == 1:
        uncertainty.append('One sale is a reference point and does not establish a stable market range.')
    elif count == 2:
        uncertainty.append('Two sales provide a limited range. Review another sale before setting a firm price.')
    if research and not fresh:
        uncertainty.append('The saved research needs review because card identity changed.')
    return dict(card_id=card['id'], status='estimated' if count >= 3 else 'limited_evidence' if count else 'insufficient_evidence',
                market_value_cents=market, range_cents=[min(values), max(values)] if values else None,
                net_proceeds_cents=net, net_range_cents=[proceeds(min(values), costs), proceeds(max(values), costs)] if values else None,
                profit_cents=net-cost if net is not None and cost is not None else None,
                purchase_cost_cents=cost, break_even_cents=break_even(cost, costs),
                category=category, category_label=LABELS[category], recommendation=reason, horizon=horizon, trigger=trigger,
                confidence=confidence, sample_count=count, included=[c['id'] for c in included], excluded=excluded,
                uncertainty=uncertainty, costs=costs, research=research if fresh else {}, research_stale=bool(research and not fresh),
                stage='Valued' if count else 'Research reviewed' if fresh else 'Purchase matched' if own else 'Needs purchase match',
                version=VERSION)

def portfolio(cards, comparables, allocations, costs=None):
    costs = normalize_costs(costs)
    rows = [analyse_card(c, comparables, allocations, costs) for c in cards]
    valued = [r for r in rows if r['market_value_cents'] is not None]
    paired = [r for r in valued if r['purchase_cost_cents'] is not None]
    return dict(rows=rows, costs=costs, version=VERSION,
                summary=dict(cards=len(cards), matched=sum(r['purchase_cost_cents'] is not None for r in rows),
                             researched=sum(bool(r['research']) for r in rows), valued=len(valued),
                             purchase_cost_cents=sum(r['purchase_cost_cents'] or 0 for r in rows),
                             valued_purchase_cost_cents=sum(r['purchase_cost_cents'] for r in paired),
                             market_value_cents=sum(r['market_value_cents'] for r in valued) if valued else None,
                             net_proceeds_cents=sum(r['net_proceeds_cents'] for r in valued) if valued else None,
                             profit_cents=sum(r['profit_cents'] for r in paired) if paired else None,
                             unvalued=len(cards)-len(valued)))
