"""Conservative estimates from matching, recent, sold evidence."""
import datetime as dt
import statistics
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
import re

IDENTITY_FIELDS = ('player', 'year', 'set', 'number', 'variant', 'grade', 'condition')


def comparable_source(url):
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    item = re.search(r'/itm/(?:[^/]+/)?(\d+)', parsed.path)
    if (host == 'ebay.com' or host.endswith('.ebay.com')) and item:
        return 'ebay-item:' + item.group(1)
    query = [(k,v) for k,v in parse_qsl(parsed.query) if not k.lower().startswith('utm_') and k.lower() not in ('ref','referrer')]
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip('/'), '', urlencode(sorted(query)), ''))


def value_card(identity, comparables, fees=None, cost=None, today=None):
    today = today or dt.date.today()
    included, excluded = [], []
    complete = all(identity.get(k, '').strip() for k in IDENTITY_FIELDS)
    seen = set()
    for comp in comparables:
        reasons = []
        if not complete:
            reasons.append('Complete all identity and condition fields.')
        if comp.get('status') != 'sold':
            reasons.append('The source does not confirm a completed sale.')
        if comp.get('currency') != 'USD':
            reasons.append('The currency is not USD.')
        if any(comp.get(k, '').strip().casefold() != identity.get(k, '').strip().casefold() for k in IDENTITY_FIELDS):
            reasons.append('The identity, variant, grade, or condition differs.')
        try:
            age = (today-dt.date.fromisoformat(comp['sold_date'])).days
            if age < 0 or age > 90:
                reasons.append('The sale is outside the past 90 days.')
        except (ValueError, KeyError):
            reasons.append('The sale date is invalid.')
        source = comparable_source(comp.get('source_url', ''))
        if source in seen:
            reasons.append('This source is already included.')
        if reasons:
            excluded.append({'id': comp['id'], 'reasons': reasons})
        else:
            included.append(comp)
            seen.add(source)
    result = {'status': 'insufficient_evidence', 'market_value_cents': None, 'net_proceeds_cents': None,
              'profit_cents': None, 'included': [c['id'] for c in included], 'excluded': excluded,
              'recommendation': 'Add at least three matching, recent sold comparables.',
              'uncertainty': ['Source details are user-entered. The application does not verify marketplace sales.']}
    if len(included) >= 3:
        values = [c['price_cents'] + c['shipping_cents'] for c in included]
        market = round(statistics.median(values))
        result.update(status='estimated', market_value_cents=market, range_cents=[min(values), max(values)],
                      recommendation='Review the sold evidence before deciding whether to sell.')
        if fees is not None:
            net = market-round(market*fees['percent']/100)-fees['fixed_cents']-fees['shipping_cents']
            result.update(net_proceeds_cents=net, profit_cents=net-cost if cost is not None else None)
    return result
