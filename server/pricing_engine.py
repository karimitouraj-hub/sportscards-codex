"""Observed asking references and explicit, uncalibrated sale scenarios.

Money uses integer cents. Scenario quantiles are not confidence intervals.
"""
import datetime as dt
import hashlib
import json
import math
import random
import statistics
from urllib.parse import urlparse

from .analysis import DEFAULT_COSTS, analyse_card, proceeds, signature, normalize_costs
from .valuation import comparable_source

VERSION = 'pricing-scenarios-v1'
DEFAULT_SETTINGS = dict(listing_factor=.8, p30=.35, market_sigma=.15,
                        player_sigma=.15, product_sigma=.1, card_sigma=.2)
ASSUMPTIONS = [
    'Sale probabilities and price variation are assumptions. They are not fitted forecasts.',
    'Active asking prices are offers. They do not confirm a completed sale.',
    'Scenario quantiles describe the selected assumptions. They are not confidence intervals.',
    'Unsold cards remain inventory. Selling costs apply only when a sale occurs.',
    'Unknown card values remain unknown. They do not become zero-value cards.',
    'The constant sale hazard assumes P(sold by T) = 1 - (1 - p30) ** (T / 30).',
    'Price shocks share market, player, product, and exact-variant components.',
]


def _number(value, name, low, high, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number.')
    if not low <= value <= high or (integer and int(value) != value):
        raise ValueError(f'{name} must be {"an integer " if integer else ""}from {low} to {high}.')
    return int(value) if integer else float(value)


def validate_settings(settings=None):
    if settings is not None and not isinstance(settings, dict):
        raise ValueError('Settings must be an object.')
    values = dict(DEFAULT_SETTINGS)
    for key, value in (settings or {}).items():
        if key not in values:
            raise ValueError(f'Unknown pricing setting: {key}.')
        values[key] = _number(value, key, 0, 1 if key == 'p30' else 2)
    return values


def _costs(costs):
    result = dict(DEFAULT_COSTS, **(costs or {}))
    for key in ('percent', 'tax_percent'):
        result[key] = _number(result[key], key, 0, 50)
    for key in ('shipping_cents', 'packaging_cents', 'fixed_cents'):
        result[key] = _number(result[key], key, 0, 1000000, True)
    if not isinstance(result['dynamic_fixed'], bool):
        raise ValueError('dynamic_fixed must be true or false.')
    if result.get('currency') != 'USD':
        raise ValueError('The pricing engine requires USD selling costs.')
    return normalize_costs(result)


def _date(value):
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if value is not None:
        return dt.date.fromisoformat(value)
    return dt.datetime.now(dt.timezone.utc).date()


def _timestamp(value):
    try:
        result = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result.replace(tzinfo=dt.timezone.utc) if result.tzinfo is None else result.astimezone(dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def _quantiles(values, money=True):
    if not values:
        return None
    ordered = sorted(values)
    def percentile(fraction):
        position = (len(ordered)-1) * fraction
        lower = int(position)
        value = ordered[lower] + (ordered[min(lower+1, len(ordered)-1)]-ordered[lower]) * (position-lower)
        return round(value) if money else round(value, 4)
    return dict(p10=percentile(.1), p50=percentile(.5), p90=percentile(.9),
                mean=round(statistics.fmean(values), 2))


def _ask_quantiles(values):
    if not values:
        return None
    ordered = sorted(values)
    def percentile(fraction):
        position = (len(ordered)-1) * fraction
        lower = int(position)
        return round(ordered[lower]+(ordered[min(lower+1, len(ordered)-1)]-ordered[lower])*(position-lower))
    return dict(min=ordered[0], p25=percentile(.25), p50=percentile(.5), p75=percentile(.75), max=ordered[-1])


def _variant_key(card):
    fields = ('player', 'year', 'set', 'number', 'variant', 'grade', 'condition', 'sport', 'manufacturer', 'autograph', 'memorabilia')
    identity = {key: str(card.get(key, '')).strip().casefold() for key in fields}
    serial = str(card.get('serial_number', ''))
    identity['print_run'] = serial.rsplit('/', 1)[1] if '/' in serial else ''
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def _active_evidence(card, listings, today):
    records = [record for record in listings if record.get('card_id') == card['id']]
    floor = dt.datetime.min.replace(tzinfo=dt.timezone.utc)
    def rank(index):
        record = records[index]
        # A metadata correction retains the original observation date.
        # Its later creation date replaces the older immutable interpretation.
        digest = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        return (_timestamp(record.get('observed_at')) or floor,
                _timestamp(record.get('created_at')) or floor, str(record.get('id') or ''), digest)
    order = sorted(range(len(records)), key=rank)
    latest_source = {}
    for index in order:
        record = records[index]
        source = comparable_source(record.get('source_url', '')) or f'missing:{index}'
        if source not in latest_source or rank(index) > rank(latest_source[source]):
            latest_source[source] = index
    latest_copy = {}
    for index in latest_source.values():
        key = str(records[index].get('physical_copy_key') or '').strip().casefold()
        if key and (key not in latest_copy or rank(index) > rank(latest_copy[key])):
            latest_copy[key] = index
    included, excluded = [], []
    for index in order:
        record = records[index]
        reasons = []
        source = comparable_source(record.get('source_url', '')) or f'missing:{index}'
        copy = str(record.get('physical_copy_key') or '').strip().casefold()
        if latest_source[source] != index:
            reasons.append('A later observation replaces this listing snapshot.')
        if copy and latest_copy.get(copy) != index:
            reasons.append('A later observation represents the same physical card.')
        if not record.get('match_reviewed'):
            reasons.append('The exact card match has not been reviewed.')
        if record.get('identity_signature') != signature(card):
            reasons.append('Card details changed after this comparison.')
        if record.get('status') != 'active':
            reasons.append('The latest observation is not an active listing.')
        if record.get('buying_format') != 'fixed_price':
            reasons.append('An auction in progress is not a fixed asking price.')
        if record.get('currency') != 'USD':
            reasons.append('The asking price is not in USD.')
        if not record.get('shipping_known'):
            reasons.append('Buyer shipping is unknown.')
        observed = _timestamp(record.get('observed_at'))
        if observed is None or not 0 <= (today-observed.date()).days <= 14:
            reasons.append('The observation must be within the past 14 days.')
        parsed = urlparse(record.get('source_url', ''))
        if parsed.scheme not in ('https', 'http') or not parsed.hostname:
            reasons.append('The source URL is missing or invalid.')
        price = record.get('ask_cents', record.get('price_cents'))
        shipping = record.get('shipping_cents')
        try:
            price = _number(price, 'ask_cents', 1, 1000000000, True)
            shipping = _number(shipping, 'shipping_cents', 0, 1000000000, True)
        except ValueError:
            reasons.append('The asking price or shipping amount is invalid.')
        if reasons:
            excluded.append(dict(id=record.get('id'), reasons=reasons))
        else:
            included.append(dict(record, delivered_ask_cents=price+shipping))
    return included, excluded


def engine_report(cards, comparables, allocations, listings, costs=None, settings=None, today=None):
    """Keep observed sales, asking references, and provisional scenarios separate."""
    today, settings, costs = _date(today), validate_settings(settings), _costs(costs)
    rows = []
    for card in cards:
        sold = analyse_card(card, comparables, allocations, costs, today)
        active, excluded = _active_evidence(card, listings, today)
        asks = [record['delivered_ask_cents'] for record in active]
        ask = round(statistics.median(asks)) if asks else None
        provisional = round(ask * settings['listing_factor']) if ask is not None else None
        anchor = sold['market_value_cents'] if sold['market_value_cents'] is not None else provisional
        source = 'sold' if sold['market_value_cents'] is not None else 'active_listing' if ask is not None else 'unknown'
        net = proceeds(anchor, costs) if anchor is not None else None
        cost = sold['purchase_cost_cents']
        seller_names = {str(record.get('seller') or '').strip().casefold() for record in active} - {''}
        observed = [record['observed_at'] for record in active]
        first = [record.get('first_observed_at') or record['observed_at'] for record in active]
        row = {key: card.get(key, '') for key in ('player', 'year', 'set', 'variant', 'grade', 'number', 'sport', 'manufacturer')}
        row.update(card_id=card['id'], label=' '.join(str(card.get(key) or '') for key in ('year', 'player', 'set', 'variant')).strip(),
                   identity_signature=signature(card), variant_key=_variant_key(card), purchase_cost_cents=cost,
                   sold_value_cents=sold['market_value_cents'], sold_sample_count=sold['sample_count'],
                   sold_range_cents=sold['range_cents'], sold_included=sold['included'], sold_excluded=sold['excluded'],
                   sold_sources=[record for record in comparables if record.get('id') in sold['included']],
                   active_ask_cents=ask, active_sample_count=len(asks), active_seller_count=len(seller_names),
                   active_unknown_seller_count=sum(not str(record.get('seller') or '').strip() for record in active),
                   active_range_cents=[min(asks), max(asks)] if asks else None, active_quantiles_cents=_ask_quantiles(asks),
                   active_included=[record['id'] for record in active], active_excluded=excluded,
                   active_sources=active,
                   listing_scenario_cents=provisional, price_source=source, scenario_price_cents=anchor,
                   scenario_net_cents=net, scenario_profit_cents=net-cost if net is not None and cost is not None else None,
                   confidence=sold['confidence'] if source == 'sold' else 'Provisional asking reference' if asks else 'Insufficient',
                   latest_observed_at=max(observed, key=_timestamp) if observed else None,
                   first_observed_at=min(first, key=lambda value: _timestamp(value) or dt.datetime.max.replace(tzinfo=dt.timezone.utc)) if first else None)
        rows.append(row)
    modeled = [row for row in rows if row['scenario_price_cents'] is not None]
    sold_rows = [row for row in rows if row['price_source'] == 'sold']
    asking_rows = [row for row in rows if row['price_source'] == 'active_listing']
    def total(group, field):
        values = [row[field] for row in group if row[field] is not None]
        return sum(values) if values else None
    summary = dict(cards=len(rows), sold_supported_cards=len(sold_rows), listing_scenario_cards=len(asking_rows),
                   modeled_cards=len(modeled), unknown_cards=len(rows)-len(modeled), active_reference_cards=sum(row['active_ask_cents'] is not None for row in rows),
                   purchase_cost_cents=total(rows, 'purchase_cost_cents'), unknown_purchase_cost_cards=sum(row['purchase_cost_cents'] is None for row in rows),
                   modeled_purchase_cost_cents=total(modeled, 'purchase_cost_cents'), sold_value_cents=total(sold_rows, 'sold_value_cents'),
                   listing_scenario_cents=total(asking_rows, 'listing_scenario_cents'), scenario_price_cents=total(modeled, 'scenario_price_cents'),
                   scenario_net_cents=total(modeled, 'scenario_net_cents'), scenario_profit_cents=total(modeled, 'scenario_profit_cents'))
    return dict(version=VERSION, as_of=today.isoformat(), rows=rows, summary=summary, settings=settings, costs=costs,
                status='uncalibrated_scenario', assumptions=ASSUMPTIONS + ['Listing snapshots expire after 14 days. Sold evidence retains its existing 90-day rule.'])


SIM_DEFAULTS = dict(trials=10000, seed=42, horizon_days=90, strategy='individual',
                    bundle_size=5, bundle_price_factor=.85, bundle_p30=.35,
                    bundle_shipping_cents=700, bundle_packaging_cents=100,
                    markdown_after_days=30, markdown_price_factor=.85, markdown_p30=.35)


def _options(options, settings):
    if options is not None and not isinstance(options, dict):
        raise ValueError('Simulation options must be an object.')
    supplied = options or {}
    allowed = set(SIM_DEFAULTS) | set(DEFAULT_SETTINGS) | {'card_ids'}
    extra = set(supplied)-allowed
    if extra:
        raise ValueError('Unknown simulation option: ' + sorted(extra)[0] + '.')
    result = {**SIM_DEFAULTS, **settings, **supplied}
    result.update(validate_settings({key: result[key] for key in DEFAULT_SETTINGS}))
    ranges = dict(trials=(1, 10000), seed=(0, 2147483647), horizon_days=(1, 3650),
                  bundle_size=(2, 100), bundle_shipping_cents=(0, 1000000),
                  bundle_packaging_cents=(0, 1000000), markdown_after_days=(0, 3650))
    for key, (low, high) in ranges.items():
        result[key] = _number(result[key], key, low, high, True)
    for key in ('bundle_price_factor', 'markdown_price_factor'):
        result[key] = _number(result[key], key, 0, 2)
    for key in ('bundle_p30', 'markdown_p30'):
        result[key] = _number(result[key], key, 0, 1)
    if result['strategy'] not in ('individual', 'bundle', 'hold', 'markdown'):
        raise ValueError('The sale strategy is invalid.')
    if 'card_ids' in result:
        ids = result['card_ids']
        if not isinstance(ids, list) or any(not isinstance(value, str) for value in ids) or len(set(ids)) != len(ids):
            raise ValueError('card_ids must contain unique card IDs.')
    return result


def _probability(p30, days):
    return 1-(1-p30)**(max(days, 0)/30) if days > 0 else 0.0


def _split_cents(total, weights):
    """Allocate each order's cents without creating rounding gains or losses."""
    denominator = sum(weights)
    fractions = [weight / denominator for weight in weights] if denominator else [1/len(weights)] * len(weights)
    amounts = [math.floor(total*fraction) for fraction in fractions]
    for index in range(total-sum(amounts)):
        amounts[index % len(amounts)] += 1
    return amounts


def _sensitivity(rows, costs, horizon):
    result = []
    has_known_cost = any(row['purchase_cost_cents'] is not None for row in rows)
    has_modeled_cost = any(row['purchase_cost_cents'] is not None and row['scenario_price_cents'] is not None for row in rows)
    for factor in (.6, .8, 1.0):
        for p30 in (.2, .5, .8):
            probability = _probability(p30, horizon)
            gross, net, profit, modeled, retained = 0, 0, 0, 0, 0
            for row in rows:
                cost = row['purchase_cost_cents']
                if row['scenario_price_cents'] is None:
                    retained += cost or 0
                    continue
                anchor = round(row['active_ask_cents']*factor) if row['price_source'] == 'active_listing' else row['scenario_price_cents']
                card_net = proceeds(anchor, costs)
                gross += anchor*probability
                net += card_net*probability
                profit += (card_net-cost)*probability if cost is not None else 0
                retained += (cost or 0)*(1-probability)
                modeled += 1
            result.append(dict(listing_factor=factor, p30=p30, horizon_days=horizon, strategy='individual',
                               expected_sold_cards=round(modeled*probability, 2), expected_gross_sales_cents=round(gross),
                               expected_net_cash_cents=round(net), expected_realized_profit_cents=round(profit) if has_modeled_cost else None,
                               expected_retained_cost_cents=round(retained) if has_known_cost else None))
    return result


def simulate(report, options=None):
    """Run reproducible portfolio trials. Preserve unsold and unpriced inventory."""
    settings = validate_settings(report.get('settings'))
    options = _options(options, settings)
    costs = _costs(report.get('costs'))
    rows = sorted(report['rows'], key=lambda row: row['card_id'])
    if 'card_ids' in options:
        unknown = set(options['card_ids'])-{row['card_id'] for row in rows}
        if unknown:
            raise ValueError('Unknown card ID: ' + sorted(unknown)[0] + '.')
        rows = [row for row in rows if row['card_id'] in options['card_ids']]
    modeled = [row for row in rows if row['scenario_price_cents'] is not None]
    unpriced = [row for row in rows if row['scenario_price_cents'] is None]
    references = {}
    for row in modeled:
        anchor = round(row['active_ask_cents']*options['listing_factor']) if row['price_source'] == 'active_listing' else row['scenario_price_cents']
        references.setdefault(row['variant_key'], []).append((row['price_source'], anchor))
    # Exact duplicate variants share one market price in a trial.
    anchors, anchor_sources = {}, {}
    for key, values in references.items():
        sold = [amount for source, amount in values if source == 'sold']
        anchors[key] = round(statistics.median(sold or [amount for _, amount in values]))
        anchor_sources[key] = 'sold' if sold else values[0][0]
    players = sorted({str(row.get('player') or row['card_id']).casefold() for row in modeled})
    products = sorted({'|'.join(str(row.get(key, '')).casefold() for key in ('sport', 'year', 'manufacturer', 'set')) for row in modeled})
    variants = sorted(anchors)
    rng = random.Random(options['seed'])
    fields = ('gross_sales_cents', 'net_cash_cents', 'realized_profit_cents', 'retained_cost_cents', 'retained_model_value_cents', 'sold_count')
    totals = {field: [] for field in fields}
    per_card = {row['card_id']: dict(prices=[], net=[], profit=[], retained=[], sold=0) for row in rows}
    no_sale = loss = loss_denominator = 0
    groups = [modeled[index:index+options['bundle_size']] for index in range(0, len(modeled), options['bundle_size'])] if options['strategy'] == 'bundle' else [[row] for row in modeled]
    variance = sum(options[key]**2 for key in ('market_sigma', 'player_sigma', 'product_sigma', 'card_sigma'))
    probability = _probability(options['p30'], options['horizon_days'])
    bundle_probability = _probability(options['bundle_p30'], options['horizon_days'])
    first_days = min(options['horizon_days'], options['markdown_after_days'])
    first_probability = _probability(options['p30'], first_days)
    second_probability = _probability(options['markdown_p30'], options['horizon_days']-first_days)
    for _ in range(options['trials']):
        market = rng.gauss(0, options['market_sigma'])
        player_draws = {key: rng.gauss(0, options['player_sigma']) for key in players}
        product_draws = {key: rng.gauss(0, options['product_sigma']) for key in products}
        card_draws = {key: rng.gauss(0, options['card_sigma']) for key in variants}
        prices = {}
        for row in modeled:
            player = str(row.get('player') or row['card_id']).casefold()
            product = '|'.join(str(row.get(key, '')).casefold() for key in ('sport', 'year', 'manufacturer', 'set'))
            shock = market + player_draws[player] + product_draws[product] + card_draws[row['variant_key']]
            prices[row['card_id']] = max(0, round(anchors[row['variant_key']] * math.exp(shock-variance/2)))
        gross_total = net_total = profit_total = retained_total = retained_value = count = known_cost_sales = 0
        for group in groups:
            strategy = options['strategy']
            factor = 1.0
            if strategy == 'hold':
                sold = False
            elif strategy == 'bundle':
                sold = rng.random() < bundle_probability
                factor = options['bundle_price_factor']
            elif strategy == 'markdown':
                sold = rng.random() < first_probability
                if not sold and options['horizon_days'] > first_days:
                    sold = rng.random() < second_probability
                    factor = options['markdown_price_factor']
            else:
                sold = rng.random() < probability
            group_prices = [prices[row['card_id']] for row in group]
            gross = round(sum(group_prices)*factor)
            sale_costs = dict(costs, shipping_cents=options['bundle_shipping_cents'], packaging_cents=options['bundle_packaging_cents']) if strategy == 'bundle' else costs
            net = proceeds(gross, sale_costs) if sold else 0
            gross_parts = _split_cents(gross, group_prices)
            net_parts = _split_cents(net, group_prices)
            for index, row in enumerate(group):
                cost = row['purchase_cost_cents']
                entry = per_card[row['card_id']]
                entry['prices'].append(gross_parts[index])
                entry['net'].append(net_parts[index] if sold else 0)
                entry['sold'] += int(sold)
                if sold:
                    gross_total += gross_parts[index]
                    net_total += net_parts[index]
                    count += 1
                    if cost is not None:
                        realized = net_parts[index]-cost
                        profit_total += realized
                        known_cost_sales += 1
                        entry['profit'].append(realized)
                        entry['retained'].append(0)
                else:
                    retained_total += cost or 0
                    retained_value += prices[row['card_id']]
                    if cost is not None:
                        entry['profit'].append(0)
                        entry['retained'].append(cost)
            # Unknown costs remain excluded from profit, including sold cards.
        for row in unpriced:
            cost = row['purchase_cost_cents']
            retained_total += cost or 0
            entry = per_card[row['card_id']]
            entry['net'].append(0)
            if cost is not None:
                entry['profit'].append(0)
                entry['retained'].append(cost)
        values = (gross_total, net_total, profit_total, retained_total, retained_value, count)
        for field, value in zip(fields, values):
            totals[field].append(value)
        no_sale += int(count == 0)
        if known_cost_sales:
            loss_denominator += 1
            loss += int(profit_total < 0)
    metrics = {field: _quantiles(values, field != 'sold_count') for field, values in totals.items()}
    metrics.update(probability_no_sale=no_sale/options['trials'],
                   probability_realized_loss_given_known_cost_sale=loss/loss_denominator if loss_denominator else None,
                   loss_denominator_trials=loss_denominator)
    known_cost_rows = [row for row in rows if row['purchase_cost_cents'] is not None]
    if not known_cost_rows:
        metrics['realized_profit_cents'] = None
        metrics['retained_cost_cents'] = None
    card_results = []
    for row in rows:
        values = per_card[row['card_id']]
        card_results.append(dict(card_id=row['card_id'], label=row.get('label') or row.get('player') or row['card_id'],
                                 player=row.get('player', ''), price_source=row['price_source'],
                                 effective_price_source=anchor_sources.get(row.get('variant_key'), 'unknown'),
                                 sale_probability=values['sold']/options['trials'], price_cents=_quantiles(values['prices']),
                                 net_cash_cents=_quantiles(values['net']), realized_profit_cents=_quantiles(values['profit']),
                                 retained_cost_cents=_quantiles(values['retained'])))
    summary = dict(selected_cards=len(rows), modeled_cards=len(modeled), unknown_cards=len(unpriced),
                   known_purchase_cost_cents=sum(row['purchase_cost_cents'] for row in known_cost_rows),
                   modeled_purchase_cost_cents=sum(row['purchase_cost_cents'] or 0 for row in modeled),
                   unknown_purchase_cost_cards=len(rows)-len(known_cost_rows),
                   modeled_unknown_cost_cards=sum(row['purchase_cost_cents'] is None for row in modeled))
    assumptions = ASSUMPTIONS + [
        'Price variation uses mean-preserving lognormal shocks over the selected horizon. No automatic appreciation is assumed.',
        'Exact duplicate variants share a price draw. Their median sold reference takes priority over asking references.',
        'Individual sale events remain independent. Unknown-price cards remain outside the model, including copies of a modeled variant.',
        'Realized profit covers sold cards with known purchase costs. Unsold cards contribute zero realized profit.',
        'Loss probability uses trials with at least one known-cost sale. It excludes retained inventory and unknown purchase costs.',
        'Retained model value is a gross reference for priced unsold cards. Unknown card values are excluded.',
        'Bundle membership follows stable card-ID order. Review card compatibility before using a bundle scenario.',
        'Each bundle is one lot listing and one shipment. Its price, sale probability, and shipping costs are separate assumptions.',
        'A markdown changes price and uses its separate sale probability. It does not automatically make a sale more likely.',
        'The sensitivity grid uses individual sales, no price shocks, and the selected horizon.',
    ]
    return dict(version=VERSION, status='uncalibrated_scenario', options=options, costs=costs, assumptions=assumptions,
                summary=summary, metrics=metrics, cards=card_results,
                sensitivity=_sensitivity(rows, costs, options['horizon_days']))


def simulate_release(options, costs=None):
    """Compare explicit release paths. No historical release model is implied."""
    if not isinstance(options, dict):
        raise ValueError('Release options must be an object.')
    defaults = dict(name='New release', quantity=1, days_since_release=0,
                    purchase_cost_cents=None, low_factor=.6, base_factor=.85, high_factor=1.2)
    simulation_keys = {'trials', 'seed', 'horizon_days', 'p30', 'market_sigma', 'player_sigma', 'product_sigma', 'card_sigma'}
    extra = set(options)-(set(defaults) | simulation_keys | {'reference_price_cents'})
    if extra:
        raise ValueError('Unknown release option: ' + sorted(extra)[0] + '.')
    values = dict(defaults, **options)
    if not isinstance(values['name'], str) or not 1 <= len(values['name'].strip()) <= 120:
        raise ValueError('The release name must contain 1 to 120 characters.')
    values['name'] = values['name'].strip()
    values['reference_price_cents'] = _number(values.get('reference_price_cents'), 'reference_price_cents', 1, 1000000000, True)
    values['quantity'] = _number(values['quantity'], 'quantity', 1, 100, True)
    values['days_since_release'] = _number(values['days_since_release'], 'days_since_release', 0, 3650, True)
    if values['purchase_cost_cents'] is not None:
        values['purchase_cost_cents'] = _number(values['purchase_cost_cents'], 'purchase_cost_cents', 0, 1000000000, True)
    for key in ('low_factor', 'base_factor', 'high_factor'):
        values[key] = _number(values[key], key, 0, 5)
    if not values['low_factor'] <= values['base_factor'] <= values['high_factor']:
        raise ValueError('Release factors must satisfy low <= base <= high.')
    sim_options = _options({key: values[key] for key in simulation_keys if key in values}, DEFAULT_SETTINGS)
    values.update({key: sim_options[key] for key in simulation_keys})
    scenarios = []
    for label in ('low', 'base', 'high'):
        factor = values[label+'_factor']
        terminal = round(values['reference_price_cents']*factor)
        rows = [dict(card_id=f'release-{index+1}', player=values['name'], year='', set='Release scenario', sport='', manufacturer='',
                     variant_key='release', purchase_cost_cents=values['purchase_cost_cents'], price_source='release_reference',
                     scenario_price_cents=terminal, active_ask_cents=None) for index in range(values['quantity'])]
        report = dict(rows=rows, settings=DEFAULT_SETTINGS, costs=_costs(costs))
        result = simulate(report, {key: values[key] for key in simulation_keys})
        scenarios.append(dict(label=label, future_factor=factor, reference_price_cents=values['reference_price_cents'],
                              terminal_reference_cents=terminal, simulation=result))
    assumptions = [
        'This release model has no fitted historical release cohort. Each path is an unvalidated scenario.',
        'The reference price applies at the stated days since release. Future factors apply over the next selected horizon.',
        'Each path applies its future reference to sales during the horizon. The model does not calculate sale-date price changes.',
        'Low, base, and high paths have no assigned probabilities. They do not establish a forecast interval.',
        'The release age is context. It does not trigger an automatic price decline or increase.',
        'Purchase cost and reference price apply to one card. Quantity represents separate copies of that card.',
        'All paths use the same random seed. This isolates the effect of the selected future price factor.',
    ]
    return dict(version=VERSION, status='unvalidated_release_scenario', options=values, assumptions=assumptions, scenarios=scenarios)
